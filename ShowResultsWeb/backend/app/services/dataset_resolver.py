"""
把已註冊的資料集記錄解析成「磁碟上真實存在、可餵給 ultralytics 的 split 目錄」。

這是驗證評估與資料集分析之間的橋樑。分析階段刻意不解壓、只讀標註文字檔，因此
`ACTIVE_DATASETS` 裡留下的是統計數字而非影像位元組——要真的跑推論就必須先把
影像變回檔案系統上的路徑。

三種來源、三種結局：

| 來源 | `source_container` | 結局 |
|---|---|---|
| LocalLibrary 資料夾 | 真實目錄 | 直接回傳既有路徑，**不複製任何位元組** |
| LocalLibrary ZIP | `.zip` 檔路徑 | 只解出被評估的那一個 split 到受管目錄 |
| 上傳的 ZIP | `None` | 拒絕，並說明位元組已不存在 |

上傳 ZIP 的分析走的是 Starlette 的 `SpooledTemporaryFile`，請求結束檔案就消失
（見 `routers/datasets.py` 與 `dataset_analyzer` 的模組註解）。這不是可以補救的疏漏，
而是「不解壓縮」這個核心設計決策的必然代價，所以這裡回傳的是明確的說明而非錯誤碼。
"""
import os
import shutil
import zipfile
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.core.config import MAX_EVAL_IMAGES
from app.utils.dataset_zip import IMAGE_EXTENSIONS
from app.utils.zip_handler import ZipIndexError, is_member_within


class DatasetUnavailable(Exception):
    """資料集無法解析成實體檔案，`message` 是給使用者看的說明。"""


@dataclass
class ResolvedSplit:
    """一個可直接餵給 ultralytics 的 split。"""
    images_dir: str          # 絕對路徑，內含影像檔
    labels_dir: str          # 絕對路徑，內含同名 .txt
    image_count: int
    extracted: bool          # True 表示是為了本次評估解壓出來的（可清理）


def _split_dir_names(stats: dict) -> List[str]:
    return [s.get("name") for s in (stats.get("splits") or []) if s.get("name")]


def available_splits(stats: dict) -> List[str]:
    """回傳這個資料集有哪些 split 可以評估（依分析階段實際掃到的目錄）。"""
    return sorted(n for n in _split_dir_names(stats) if n)


def preferred_split(stats: dict) -> Optional[str]:
    """
    預設要評估哪個 split。

    偏好順序 test > valid > val > train：test 是「嚴格封印、僅用於最終泛化能力評估」的
    那一份（見 docs/柑橘病蟲害資料集_完整版.md），拿 train 當預設會給出過度樂觀的數字。
    """
    names = set(available_splits(stats))
    for candidate in ("test", "valid", "val", "train", "training", "validation"):
        if candidate in names:
            return candidate
    return next(iter(sorted(names)), None)


def describe_availability(stats: dict) -> Tuple[bool, Optional[str]]:
    """
    (可否評估, 不可評估的原因)。供 UI 在送出前就停用按鈕並說明原因用，
    比照匯出功能「顯示但停用並附原因」的既有慣例。
    """
    if not stats.get("source_container"):
        if stats.get("source_path"):
            return False, (
                "這筆資料集是舊版掃描留下的紀錄，缺少可開啟的來源位置。請重新掃描本機資料夾。"
            )
        return False, (
            "上傳的 ZIP 只保留統計結果，影像位元組在分析結束後即已釋放，無法用於評估。"
            "請把資料集放進本機資料夾後掃描載入。"
        )
    if not available_splits(stats):
        return False, "這個資料集沒有偵測到任何 split 目錄（train / valid / test）。"
    if str(stats.get("format")) != "yolo":
        return False, f"目前只支援 YOLO 格式的資料集，這筆是 {stats.get('format')}。"
    return True, None


def _dir_split(container: str, inner_prefix: str, split: str) -> ResolvedSplit:
    """資料夾來源：就地引用，一個位元組都不複製。"""
    parts = [p for p in (inner_prefix or "").split("/") if p]
    base = os.path.join(container, *parts, split)
    images_dir = os.path.join(base, "images")
    labels_dir = os.path.join(base, "labels")

    if not os.path.isdir(images_dir):
        raise DatasetUnavailable(f"找不到 split 目錄：{images_dir}")

    count = sum(
        1 for name in os.listdir(images_dir)
        if os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS
    )
    return ResolvedSplit(images_dir, labels_dir, count, extracted=False)


def _zip_split(container: str, inner_prefix: str, split: str, dest_root: str) -> ResolvedSplit:
    """
    ZIP 來源：**只解出這一個 split**。

    整包資料集可能有數 GB（實測 4.3 GB），但單一 split 通常只有數百 MB。逐一比對前綴
    而非 extractall，既省時間也省磁碟。
    """
    prefix_parts = [p for p in (inner_prefix or "").split("/") if p]
    member_prefix = "/".join(prefix_parts + [split]) + "/"
    dest_base = os.path.join(dest_root, split)

    images_dir = os.path.join(dest_base, "images")
    labels_dir = os.path.join(dest_base, "labels")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(labels_dir, exist_ok=True)

    image_count = 0
    try:
        with zipfile.ZipFile(container) as zf:
            members = [
                info for info in zf.infolist()
                if not info.is_dir() and info.filename.replace("\\", "/").startswith(member_prefix)
            ]
            if not members:
                raise DatasetUnavailable(f"ZIP 內找不到 split：{member_prefix}")

            images = [
                m for m in members
                if os.path.splitext(m.filename)[1].lower() in IMAGE_EXTENSIONS
            ]
            if len(images) > MAX_EVAL_IMAGES:
                raise DatasetUnavailable(
                    f"這個 split 有 {len(images):,} 張影像，超過單次評估上限 {MAX_EVAL_IMAGES:,} 張。"
                )

            for info in members:
                rel = info.filename.replace("\\", "/")[len(member_prefix):]
                if not rel:
                    continue
                ext = os.path.splitext(rel)[1].lower()
                if ext in IMAGE_EXTENSIONS:
                    target_dir, is_image = images_dir, True
                elif ext == ".txt":
                    target_dir, is_image = labels_dir, False
                else:
                    continue  # 其餘檔案（快取、README…）評估用不到

                # 攤平成 images/<basename>，同時擋下路徑穿越
                basename = os.path.basename(rel)
                if not basename or not is_member_within(target_dir, basename):
                    raise ZipIndexError(f"ZIP 檔包含不安全路徑: {info.filename}")

                with zf.open(info) as src, open(os.path.join(target_dir, basename), "wb") as dst:
                    shutil.copyfileobj(src, dst)
                if is_image:
                    image_count += 1
    except zipfile.BadZipFile as exc:
        raise DatasetUnavailable("ZIP 檔案損毀或格式不正確") from exc
    except OSError as exc:
        raise DatasetUnavailable(f"解壓 split 時發生系統錯誤：{exc}") from exc

    return ResolvedSplit(images_dir, labels_dir, image_count, extracted=True)


def resolve_split(stats: dict, split: str, dest_root: str) -> ResolvedSplit:
    """
    把資料集記錄 + split 名稱解析成磁碟上的實體目錄。

    `dest_root` 只在 ZIP 來源時會被寫入；資料夾來源完全不碰它。
    """
    ok, reason = describe_availability(stats)
    if not ok:
        raise DatasetUnavailable(reason)

    if split not in available_splits(stats):
        raise DatasetUnavailable(
            f"這個資料集沒有名為「{split}」的 split，可用的有：{'、'.join(available_splits(stats))}"
        )

    container = stats["source_container"]
    inner = stats.get("source_inner_prefix") or ""

    if os.path.isdir(container):
        return _dir_split(container, inner, split)
    if os.path.isfile(container) and container.lower().endswith(".zip"):
        return _zip_split(container, inner, split, dest_root)
    raise DatasetUnavailable(f"來源已不存在或無法讀取：{container}")
