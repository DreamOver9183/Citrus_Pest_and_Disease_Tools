import time
from app.utils.device_probe import probe_all_devices
from app.services.model_service import model_manager

class DeviceService:
    def __init__(self):
        self.current_device = "auto"
        self._device_cache_data = None
        self._device_cache_time = 0

    def get_available_devices(self):
        now = time.time()
        if self._device_cache_data is None or (now - self._device_cache_time) > 30:
            self._device_cache_data = probe_all_devices()
            self._device_cache_time = now
        return self._device_cache_data

    def invalidate_cache(self):
        self._device_cache_data = None
        self._device_cache_time = 0

    def get_current_device(self):
        return self.current_device

    def set_current_device(self, device_id: str):
        devices = probe_all_devices()
        valid_ids = [d["id"] for d in devices] + ["auto"]
        if device_id not in valid_ids:
            raise ValueError("無效的裝置 ID")
        
        self.current_device = device_id
        
        # 觸發重新載入模型以應用新裝置 (如果有已載入的模型)
        if model_manager.current_path:
            model_manager.load_model(model_manager.current_path, device=self.current_device)
        
        self.invalidate_cache()

device_service = DeviceService()
