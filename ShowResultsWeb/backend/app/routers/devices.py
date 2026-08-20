from fastapi import APIRouter, Form, HTTPException
from app.services.device_service import device_service
from app.services.model_service import model_manager
from app.schemas import DevicesResponse, SetDeviceResponse

router = APIRouter()

@router.get("/devices", response_model=DevicesResponse, response_model_exclude_unset=True)
def get_devices():
    """取得系統所有可用推論裝置清單"""
    devices = device_service.get_available_devices()
    current_label = model_manager.get_current_device_label()

    return {
        "status": "success",
        "available_devices": devices,
        "current_device": device_service.get_current_device(),
        "current_device_label": current_label
    }

@router.post("/set-device", response_model=SetDeviceResponse, response_model_exclude_unset=True)
def set_device(device_id: str = Form(...)):
    """設定全域推論裝置"""
    try:
        device_service.set_current_device(device_id)
        return {
            "status": "success",
            "current_device": device_service.get_current_device(),
            "current_device_label": model_manager.get_current_device_label()
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
