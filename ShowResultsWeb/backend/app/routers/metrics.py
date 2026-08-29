"""訓練當時產出的指標圖：results.png 的網格裁切與獨立圖表。

注意這裡回傳的是**訓練當時**寫進 PNG 的舊值，不是本系統重新算出來的指標。
要當下的實測數字請走 /api/evaluations（見 architecture.md §7）。
"""
import os
import shutil

from fastapi import APIRouter

from app.core.config import TEMP_DIR
from app.core.envelope import ApiException, ApiResponse, ok
from app.schemas import MetricsPayload
from app.services.session_manager import ACTIVE_SESSIONS, SESSIONS_LOCK
from app.utils.image_cropper import crop_metric_image

router = APIRouter()

# 已是獨立檔案的圖表，不需要像素裁剪
STANDALONE_METRICS = {
    "confusion_matrix": "confusion_matrix.png",
    "confusion_matrix_normalized": "confusion_matrix_normalized.png",
    "BoxF1_curve": "BoxF1_curve.png",
    "BoxP_curve": "BoxP_curve.png",
    "BoxPR_curve": "BoxPR_curve.png",
    "BoxR_curve": "BoxR_curve.png",
}


@router.get("/metrics", response_model=ApiResponse[MetricsPayload])
def get_metrics(session_id: str, metric_type: str = "mAP50"):
    """依 session 與指標類型回傳可直接顯示的圖片 URL 與其原始實體路徑。"""
    with SESSIONS_LOCK:
        session_data = ACTIVE_SESSIONS.get(session_id)
        session_data = dict(session_data) if session_data else None

    if session_data is None:
        raise ApiException("not_found", "找不到指定的模型 Session")

    if metric_type in STANDALONE_METRICS:
        filename = STANDALONE_METRICS[metric_type]
        src = os.path.join(session_data["dir_path"], filename).replace("\\", "/")
        if not os.path.exists(src):
            raise ApiException("precondition_failed", f"該模型未產出獨立圖表：{filename}")

        target_name = f"{session_id}_{filename}"
        shutil.copy(src, os.path.join(TEMP_DIR, target_name))
        return ok({
            "url": f"/static/{target_name}",
            "source_path": os.path.abspath(src).replace("\\", "/"),
        })

    src = session_data.get("results_png")
    if not src or not os.path.exists(src):
        raise ApiException("precondition_failed", "該模型未產出結果指標圖表 results.png。")

    target_name = f"{session_id}_{metric_type}.png"
    crop_metric_image(src, os.path.join(TEMP_DIR, target_name), metric_type)
    return ok({
        "url": f"/static/{target_name}",
        "source_path": f"{os.path.abspath(src).replace(chr(92), '/')} (指標: {metric_type})",
    })
