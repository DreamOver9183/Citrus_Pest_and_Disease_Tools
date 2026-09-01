"""資料庫連線與 session 工廠。

**設計核心：資料庫是可選的。** 這是一個單機離線展示工具，上傳一顆模型不該因為
PostgreSQL 容器還沒暖機完成而失敗。因此：

- `init_db()` 會重試若干次，全部失敗就把 `_AVAILABLE` 設為 False 並印警告，
  **應用程式照常啟動**。
- 所有寫入路徑在不可用時靜默略過（呼叫端不必判斷）。
- 讀取端點在不可用時回 503 + `dependency_unavailable`，而不是 500。

雙軌的實作差異只有兩點，都封裝在這裡：SQLite 需要 `check_same_thread=False`
（評估與匯出的 daemon worker 會從別的執行緒寫入），而 PostgreSQL 需要連線池的
`pool_pre_ping`（容器重啟後舊連線會變成殭屍）。
"""
import threading
import time
from contextlib import contextmanager
from typing import Optional

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import DATABASE_URL, DB_CONNECT_RETRIES, DB_CONNECT_RETRY_DELAY
from app.db.models import SCHEMA_VERSION, Base, SchemaMeta


class RegistryUnavailable(Exception):
    """資料庫在執行期變得不可用（容器被停掉、網路斷線、連線池全毀）。

    存在的理由：`is_available()` 只反映**啟動當下**的狀態。資料庫在啟動之後才掛掉時，
    那個旗標仍是 True，查詢會一路打到 psycopg 才炸開，最後被通用 handler 收成
    HTTP 500 `internal_error`——但那並不是伺服器出錯，而是一個可選相依不在了。
    把它變成具名例外，才能在路由層正確地翻成 503 `dependency_unavailable`。
    """


_ENGINE = None
_SESSION_FACTORY: Optional[sessionmaker] = None
_AVAILABLE = False
_INIT_LOCK = threading.Lock()
_LAST_ERROR: Optional[str] = None
# 測試用：模擬「資料庫真的連不上」。必須是獨立旗標而不是單純把 _AVAILABLE 設 False——
# 路由層在不可用時會自動嘗試重連（那是正式行為，讓資料庫回來後不必重啟應用），
# 只清旗標的話重連會成功，降級路徑就測不到了。
_FORCE_OFFLINE = False


def _name_from_url(url: str) -> str:
    return url.split(":", 1)[0].split("+", 1)[0] or "unknown"


def backend_name(url: Optional[str] = None) -> str:
    """給 /api/registry/stats 顯示用的引擎名稱（sqlite / postgresql / …）。

    **已經有 engine 時一律回報「實際連上的」那個，而不是 `DATABASE_URL` 的設定值。**
    兩者會不一致：`reset_for_tests()` 會把連線換掉而不動環境變數，於是 CI 的
    PostgreSQL 那一輪裡，engine 明明綁在 tmp SQLite 上，這裡卻回報 postgresql。
    這個值是前端「資料庫引擎」欄位的唯一來源，報錯的引擎比報「不知道」更糟。

    沒有 engine 時（還沒 init、或連不上而降級）才退回設定值——此時「我試著連的是
    什麼」正是呼叫端要的資訊，`routers/registry.py` 的 503 details 就依賴這個。
    """
    if url is not None:
        return _name_from_url(url)
    if _ENGINE is not None:
        return _ENGINE.dialect.name or "unknown"
    return _name_from_url(DATABASE_URL)


def _build_engine(url: str):
    if url.startswith("sqlite"):
        # 背景 worker（評估／匯出）會從非請求執行緒寫入，SQLite 預設會拒絕跨執行緒使用。
        return create_engine(url, future=True, connect_args={"check_same_thread": False})
    return create_engine(url, future=True, pool_pre_ping=True)


def init_db(url: Optional[str] = None, retries: Optional[int] = None) -> bool:
    """建立 engine 與資料表。回傳是否可用；**永不拋例外**。"""
    global _ENGINE, _SESSION_FACTORY, _AVAILABLE, _LAST_ERROR

    if _FORCE_OFFLINE:
        return False

    target = url or DATABASE_URL
    attempts = DB_CONNECT_RETRIES if retries is None else retries

    with _INIT_LOCK:
        for attempt in range(1, max(attempts, 1) + 1):
            try:
                engine = _build_engine(target)
                Base.metadata.create_all(engine)
                factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
                with factory() as session:
                    _ensure_schema_meta(session)
                _ENGINE, _SESSION_FACTORY, _AVAILABLE, _LAST_ERROR = engine, factory, True, None
                print(f"[Registry] Database ready ({backend_name(target)})")
                return True
            except SQLAlchemyError as exc:
                _LAST_ERROR = str(exc)
                if attempt < attempts:
                    print(f"[Registry] Database not ready (attempt {attempt}/{attempts}): {exc}")
                    time.sleep(DB_CONNECT_RETRY_DELAY)
            except Exception as exc:  # noqa: BLE001 — 連 driver 缺失也不能讓應用起不來
                _LAST_ERROR = str(exc)
                break

        _ENGINE, _SESSION_FACTORY, _AVAILABLE = None, None, False
        print(
            f"[Registry] Database unavailable, registry features disabled: {_LAST_ERROR}"
        )
        return False


def _ensure_schema_meta(session: Session) -> None:
    existing = session.execute(select(SchemaMeta).limit(1)).scalar_one_or_none()
    if existing is None:
        session.add(SchemaMeta(version=SCHEMA_VERSION))
        session.commit()
    elif existing.version != SCHEMA_VERSION:
        print(
            f"[Registry] Schema version mismatch: database is v{existing.version}, "
            f"code expects v{SCHEMA_VERSION}. Delete the database file/volume to rebuild."
        )


def is_available() -> bool:
    return _AVAILABLE


def last_error() -> Optional[str]:
    return _LAST_ERROR


def reset_for_tests(url: str) -> bool:
    """測試專用：把全域狀態指向另一個資料庫。正式路徑不該呼叫。"""
    global _FORCE_OFFLINE
    dispose()
    _FORCE_OFFLINE = False
    return init_db(url=url, retries=1)


def disable_for_tests() -> None:
    """測試專用：模擬資料庫**真的連不上**（連重連都失敗）的降級路徑。"""
    global _FORCE_OFFLINE
    dispose()
    _FORCE_OFFLINE = True


def dispose() -> None:
    global _ENGINE, _SESSION_FACTORY, _AVAILABLE, _FORCE_OFFLINE
    if _ENGINE is not None:
        try:
            _ENGINE.dispose()
        except Exception:  # noqa: BLE001
            pass
    _ENGINE, _SESSION_FACTORY, _AVAILABLE = None, None, False
    _FORCE_OFFLINE = False


@contextmanager
def session_scope():
    """交易範圍。

    資料庫**啟動時**就不可用 → yield None，呼叫端只需 `if session is None: return`。
    資料庫**執行期**才掛掉 → 丟 RegistryUnavailable，由路由層翻成 503。
    """
    global _AVAILABLE, _LAST_ERROR

    if not _AVAILABLE or _SESSION_FACTORY is None:
        yield None
        return

    try:
        session = _SESSION_FACTORY()
    except SQLAlchemyError as exc:
        _AVAILABLE, _LAST_ERROR = False, str(exc)
        raise RegistryUnavailable(str(exc)) from exc

    try:
        yield session
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        # 連線層級的失敗代表資料庫真的不在了——把旗標拉下來，後續請求就能走
        # 「不可用」的快路徑，而不是每一個都等到 TCP 逾時。路由層會在下次呼叫時
        # 嘗試重連（見 routers/registry.py 的 _require_db）。
        _AVAILABLE, _LAST_ERROR = False, str(exc)
        raise RegistryUnavailable(str(exc)) from exc
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


__all__ = [
    "RegistryUnavailable",
    "backend_name",
    "disable_for_tests",
    "dispose",
    "init_db",
    "is_available",
    "last_error",
    "reset_for_tests",
    "session_scope",
]
