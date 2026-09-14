"""推論解析度（imgsz）的共用規則。

即時診斷與逐張檢視共用同一組選項與驗證。App 端即時辨識用 320、拍照模式可能用 640，
而 `.pt` 不指定時會沿用訓練尺寸——看不到解析度的推論結果會高估小目標表現。

ultralytics 遇到非 stride 倍數的 imgsz 只會自動進位並印警告，所以這裡**明確拒絕**：
否則畫面標示的解析度與實際使用的會悄悄不同。
"""
from typing import Any, Optional

from app.core.envelope import ApiException

IMGSZ_CHOICES = (320, 416, 512, 640)
IMGSZ_MIN = 160
IMGSZ_MAX = 1280
IMGSZ_STRIDE = 32


def validate_imgsz(value: Optional[int]) -> Optional[int]:
    """None 代表沿用模型預設；其餘必須是 32 的倍數且在範圍內。"""
    if value is None:
        return None
    if value < IMGSZ_MIN or value > IMGSZ_MAX or value % IMGSZ_STRIDE != 0:
        raise ApiException(
            "validation_error",
            f"推論解析度必須是 {IMGSZ_STRIDE} 的倍數，且介於 {IMGSZ_MIN}–{IMGSZ_MAX}（收到 {value}）",
        )
    return value


def normalize_imgsz(value: Any) -> Optional[int]:
    """ultralytics 的 imgsz 可能是 int 或 [h, w]；統一成單一整數（取長邊），無法解讀時回 None。"""
    if isinstance(value, (list, tuple)):
        value = max(value) if value else None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def model_default_imgsz(model: Any) -> Optional[int]:
    """
    ultralytics 模型在未指定 imgsz 時實際使用的尺寸。

    `.pt` 取自 checkpoint 保留的訓練參數（`Model._reset_ckpt_args` 只留下
    imgsz/data/task/single_cls）。取不到時回 None，由畫面顯示「模型預設」而不是猜一個數字。
    """
    overrides = getattr(model, "overrides", None) or {}
    return normalize_imgsz(overrides.get("imgsz"))
