"""權重登錄簿的資料表定義。

三張表，一條主軸：**權重的身分是檔案內容的 SHA-256，不是 `session_id`。**

`session_id` 是 `run_<uuid8>`，每次掃描／上傳都重新產生，而且 LocalLibrary 來源的
session 依設計不落地。拿它當主鍵會讓同一顆 best.pt 每重掃一次就多一筆紀錄，帳本立刻
失去意義。用內容雜湊則有一個額外的好處：同一顆權重無論是從資料夾就地引用、還是從
ZIP 解壓出來，都會收斂到同一列。

    weights           一顆權重檔一列（身分、來源、類別表、首見／末見時間）
      └── training_runs   訓練當時的紀錄（完整 args.yaml + results.csv 最後一列），1:1
      └── evaluations     本系統實測出來的每一次評估，1:N

**型別限制**：只用 SQLAlchemy 通用型別。`JSON` 在 SQLite 上落成 TEXT、在 PostgreSQL 上
落成 json，兩邊都能用；`JSONB`／`ARRAY` 只有 Postgres 有，用了就毀掉雙軌。
"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# schema 有破壞性變更時才 +1。日後只做「加欄位」的相容變更（見 architecture.md
# 「刻意不引入 Alembic」），這個版號的用途是讓不相容的舊資料能被明確偵測到，
# 而不是靜默給出錯誤的查詢結果。
SCHEMA_VERSION = 1


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SchemaMeta(Base):
    """單列表，記錄建立這份資料庫的 schema 版號。"""

    __tablename__ = "schema_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class Weight(Base):
    """一顆權重檔。身分 = 檔案內容的 SHA-256。"""

    __tablename__ = "weights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    filename: Mapped[str | None] = mapped_column(String(512))
    display_name: Mapped[str | None] = mapped_column(String(512))
    format_label: Mapped[str | None] = mapped_column(String(128))
    model_arch: Mapped[str | None] = mapped_column(String(64), index=True)
    size_mb: Mapped[float | None] = mapped_column(Float)

    # 來源形態。這些欄位是**前端精確比對**的字面值（見 CLAUDE.md 硬規則 4），
    # 與 ACTIVE_SESSIONS 中的同名欄位保持一致，不要另創新字面值。
    source_type: Mapped[str | None] = mapped_column(String(64), index=True)
    source: Mapped[str | None] = mapped_column(String(64))
    source_path: Mapped[str | None] = mapped_column(Text)

    # checkpoint 內的類別表（若讀得到）。存的是排序後的名稱清單。
    class_names: Mapped[list | None] = mapped_column(JSON)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    training_run: Mapped["TrainingRun | None"] = relationship(
        back_populates="weight", cascade="all, delete-orphan", uselist=False
    )
    evaluations: Mapped[list["Evaluation"]] = relationship(
        back_populates="weight", cascade="all, delete-orphan"
    )


class TrainingRun(Base):
    """訓練當時的紀錄。

    `hyperparameters` 存**完整的 args.yaml**——在此之前系統只留下 epochs／optimizer／
    model 三個鍵，其餘（lr0、augment、mosaic、patience…）在解析當下就丟棄了，而那些
    正是消融研究要比較的東西。下面那些提升為欄位的鍵是「常被拿來排序」的子集，
    完整內容永遠以 `hyperparameters` 為準。
    """

    __tablename__ = "training_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    weight_id: Mapped[int] = mapped_column(
        ForeignKey("weights.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    hyperparameters: Mapped[dict | None] = mapped_column(JSON)
    final_metrics: Mapped[dict | None] = mapped_column(JSON)

    epochs: Mapped[int | None] = mapped_column(Integer)
    optimizer: Mapped[str | None] = mapped_column(String(64))
    model_cfg: Mapped[str | None] = mapped_column(String(256))
    imgsz: Mapped[int | None] = mapped_column(Integer)
    batch: Mapped[int | None] = mapped_column(Integer)
    lr0: Mapped[float | None] = mapped_column(Float)
    lrf: Mapped[float | None] = mapped_column(Float)
    momentum: Mapped[float | None] = mapped_column(Float)
    weight_decay: Mapped[float | None] = mapped_column(Float)
    patience: Mapped[int | None] = mapped_column(Integer)
    seed: Mapped[int | None] = mapped_column(Integer)

    # 訓練當時 results.csv 最後一列的指標。**與 evaluations 的同名欄位不是同一回事**：
    # 這是訓練時在當時那個 val split 上的數字，evaluations 是本系統重新跑出來的。
    map50: Mapped[float | None] = mapped_column(Float)
    map50_95: Mapped[float | None] = mapped_column(Float)
    precision: Mapped[float | None] = mapped_column(Float)
    recall: Mapped[float | None] = mapped_column(Float)

    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    weight: Mapped[Weight] = relationship(back_populates="training_run")


class Evaluation(Base):
    """本系統實測出來的一次評估（`model.val()` 的結果）。"""

    __tablename__ = "evaluations"
    __table_args__ = (UniqueConstraint("job_id", name="uq_evaluations_job_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    weight_id: Mapped[int] = mapped_column(
        ForeignKey("weights.id", ondelete="CASCADE"), index=True, nullable=False
    )

    dataset_name: Mapped[str | None] = mapped_column(String(512), index=True)
    dataset_format: Mapped[str | None] = mapped_column(String(64))
    split: Mapped[str | None] = mapped_column(String(64), index=True)
    image_count: Mapped[int | None] = mapped_column(Integer)

    map50: Mapped[float | None] = mapped_column(Float, index=True)
    map50_95: Mapped[float | None] = mapped_column(Float, index=True)
    precision: Mapped[float | None] = mapped_column(Float)
    recall: Mapped[float | None] = mapped_column(Float)
    f1: Mapped[float | None] = mapped_column(Float)
    fitness: Mapped[float | None] = mapped_column(Float)

    # 邊界框級別的 TP/FP/FN 與四項衍生指標（Precision/Recall/F1/Accuracy），
    # 公式依《效能指標定義與評測方法》§2 的 TN=0 簡化定義。
    # micro_accuracy 即 TP/(TP+FP+FN)，也就是 Micro-Accuracy / Jaccard index。
    # conf/iou 門檻必須一起存：這組指標是門檻相依的，沒有門檻就無法解讀或跨紀錄比較。
    micro_accuracy: Mapped[float | None] = mapped_column(Float, index=True)
    micro_precision: Mapped[float | None] = mapped_column(Float)
    micro_recall: Mapped[float | None] = mapped_column(Float)
    micro_f1: Mapped[float | None] = mapped_column(Float)
    micro_tp: Mapped[int | None] = mapped_column(Integer)
    micro_fp: Mapped[int | None] = mapped_column(Integer)
    micro_fn: Mapped[int | None] = mapped_column(Integer)
    conf_threshold: Mapped[float | None] = mapped_column(Float)
    iou_threshold: Mapped[float | None] = mapped_column(Float)

    speed_ms: Mapped[dict | None] = mapped_column(JSON)
    per_class: Mapped[list | None] = mapped_column(JSON)
    size_profile: Mapped[list | None] = mapped_column(JSON)

    vocab_status: Mapped[str | None] = mapped_column(String(32))
    vocab_message: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[str | None] = mapped_column(String(64))
    finished_at: Mapped[str | None] = mapped_column(String(64))
    elapsed_seconds: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    weight: Mapped[Weight] = relationship(back_populates="evaluations")


__all__ = ["Base", "Evaluation", "SCHEMA_VERSION", "SchemaMeta", "TrainingRun", "Weight"]
