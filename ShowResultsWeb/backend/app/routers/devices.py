"""推論裝置的列舉與切換。"""
from fastapi import APIRouter

from app.core.envelope import ApiException, ApiResponse, ok
from app.schemas import DevicesPayload, SetDevicePayload, SetDeviceRequest
from app.services.device_service import device_service
from app.services.model_service import model_manager

router = APIRouter()


@router.get("/devices", response_model=ApiResponse[DevicesPayload])
def get_devices():
    """取得系統所有可用推論裝置清單。"""
    return ok({
        "available_devices": device_service.get_available_devices(),
        "current_device": device_service.get_current_device(),
        "current_device_label": model_manager.get_current_device_label(),
    })


@router.post("/set-device", response_model=ApiResponse[SetDevicePayload])
def set_device(payload: SetDeviceRequest):
    """設定全域推論裝置。"""
    try:
        device_service.set_current_device(payload.device_id)
    except ValueError as exc:
        # 裝置字串本身格式正確、只是這台機器沒有那個裝置——語意上的拒絕，不是格式錯誤
        raise ApiException("precondition_failed", str(exc))

    return ok({
        "current_device": device_service.get_current_device(),
        "current_device_label": model_manager.get_current_device_label(),
    })
