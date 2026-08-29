import { useState, useEffect, useCallback } from 'react';
import { apiGet, apiPost, errorMessage } from '../../api/client';

// 管理推論裝置清單與目前選用裝置的切換。
export const useDeviceControl = () => {
  const [availableDevices, setAvailableDevices] = useState([]);
  const [currentDevice, setCurrentDevice] = useState('auto');
  const [currentDeviceLabel, setCurrentDeviceLabel] = useState('Auto');
  const [deviceLoading, setDeviceLoading] = useState(false);
  const [deviceError, setDeviceError] = useState(null);

  const fetchDevices = useCallback(async () => {
    try {
      const data = await apiGet('/devices');
      setAvailableDevices(data.available_devices || []);
      setCurrentDevice(data.current_device || 'auto');
      setCurrentDeviceLabel(data.current_device_label || 'Auto');
      setDeviceError(null);
    } catch (err) {
      console.error('[useDeviceControl] Error fetching devices:', err);
      setDeviceError(errorMessage(err, '無法取得裝置清單'));
    }
  }, []);

  useEffect(() => {
    fetchDevices();
  }, [fetchDevices]);

  const switchDevice = async (deviceId) => {
    setDeviceLoading(true);
    try {
      const data = await apiPost('/set-device', { device_id: deviceId });
      setCurrentDevice(data.current_device);
      setCurrentDeviceLabel(data.current_device_label);
      setDeviceError(null);
      return true;
    } catch (err) {
      console.error('[useDeviceControl] Error switching device:', err);
      setDeviceError(errorMessage(err, '切換裝置失敗'));
      return false;
    } finally {
      setDeviceLoading(false);
    }
  };

  return {
    availableDevices,
    currentDevice,
    currentDeviceLabel,
    deviceLoading,
    deviceError,
    fetchDevices,
    switchDevice
  };
};
