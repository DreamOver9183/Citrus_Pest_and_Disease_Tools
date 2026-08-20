import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';

// 管理推論裝置清單與目前選用裝置的切換。
export const useDeviceControl = () => {
  const [availableDevices, setAvailableDevices] = useState([]);
  const [currentDevice, setCurrentDevice] = useState('auto');
  const [currentDeviceLabel, setCurrentDeviceLabel] = useState('Auto');
  const [deviceLoading, setDeviceLoading] = useState(false);

  const fetchDevices = useCallback(async () => {
    try {
      const res = await axios.get('/api/devices');
      if (res.data.status === 'success') {
        setAvailableDevices(res.data.available_devices || []);
        setCurrentDevice(res.data.current_device || 'auto');
        setCurrentDeviceLabel(res.data.current_device_label || 'Auto');
      }
    } catch (err) {
      console.error('[useDeviceControl] Error fetching devices:', err);
    }
  }, []);

  useEffect(() => {
    fetchDevices();
  }, [fetchDevices]);

  const switchDevice = async (deviceId) => {
    setDeviceLoading(true);
    try {
      const formData = new FormData();
      formData.append('device_id', deviceId);

      const res = await axios.post('/api/set-device', formData);
      if (res.data.status === 'success') {
        setCurrentDevice(res.data.current_device);
        setCurrentDeviceLabel(res.data.current_device_label);
        return true;
      }
    } catch (err) {
      console.error('[useDeviceControl] Error switching device:', err);
    } finally {
      setDeviceLoading(false);
    }
    return false;
  };

  return {
    availableDevices,
    currentDevice,
    currentDeviceLabel,
    deviceLoading,
    fetchDevices,
    switchDevice
  };
};
