import { useState, useEffect, useCallback } from 'react';
import { apiGet, apiGetWithMeta, apiDelete, errorMessage, ApiError } from '../../api/client';

// 權重登錄簿的「耐久」狀態，由 Provider 掛載一次。
//
// 與其他耐久 hook 同樣的理由：App.jsx 用純 && 條件渲染，切走分頁等於整棵元件樹
// unmount。使用者在登錄簿排序、展開某顆權重的超參數之後切去別的分頁，再切回來時
// 這些選擇都應該還在——否則每次回來都要重排一次。
//
// 與其他 hook 不同的一點：登錄簿依賴資料庫，而資料庫是**可選**相依。所以這裡多了
// 一個 `registryAvailable` 狀態：後端在資料庫離線時回 503 + dependency_unavailable，
// UI 要顯示「登錄簿離線」而不是紅色錯誤——其他功能（載入模型、推論、評估）完全不受影響。
export const useRegistry = () => {
  const [registryStats, setRegistryStats] = useState(null);
  const [registryAvailable, setRegistryAvailable] = useState(true);
  const [weights, setWeights] = useState([]);
  const [weightsTotal, setWeightsTotal] = useState(0);
  const [ledger, setLedger] = useState([]);
  const [selectedSha, setSelectedSha] = useState(null);
  const [weightDetail, setWeightDetail] = useState(null);
  const [registryLoading, setRegistryLoading] = useState(true);
  const [registryError, setRegistryError] = useState(null);

  // 排序狀態要跨分頁存活，所以放在耐久層
  const [weightSort, setWeightSort] = useState({ order_by: 'last_seen_at', order: 'desc' });
  const [ledgerSort, setLedgerSort] = useState({ order_by: 'finished_at', order: 'desc' });
  const [query, setQuery] = useState('');

  const fetchStats = useCallback(async () => {
    try {
      const data = await apiGet('/registry/stats');
      setRegistryStats(data);
      setRegistryAvailable(!!data.available);
      return !!data.available;
    } catch (err) {
      console.error('[useRegistry] Error fetching stats:', err);
      setRegistryAvailable(false);
      return false;
    }
  }, []);

  const fetchWeights = useCallback(async () => {
    const params = new URLSearchParams({
      order_by: weightSort.order_by,
      order: weightSort.order,
      limit: '200',
    });
    if (query.trim()) params.set('q', query.trim());
    try {
      const { data, meta } = await apiGetWithMeta(`/registry/weights?${params}`);
      setWeights(data.weights || []);
      setWeightsTotal(meta?.total ?? (data.weights || []).length);
      setRegistryError(null);
      setRegistryAvailable(true);
    } catch (err) {
      if (err instanceof ApiError && err.code === 'dependency_unavailable') {
        setRegistryAvailable(false);
        setWeights([]);
        setWeightsTotal(0);
        return;
      }
      console.error('[useRegistry] Error fetching weights:', err);
      setRegistryError(errorMessage(err, '無法取得權重清單'));
    }
  }, [weightSort, query]);

  const fetchLedger = useCallback(async () => {
    const params = new URLSearchParams({
      order_by: ledgerSort.order_by,
      order: ledgerSort.order,
      limit: '300',
    });
    try {
      const data = await apiGet(`/registry/evaluations?${params}`);
      setLedger(data.evaluations || []);
    } catch (err) {
      if (err instanceof ApiError && err.code === 'dependency_unavailable') {
        setLedger([]);
        return;
      }
      console.error('[useRegistry] Error fetching ledger:', err);
    }
  }, [ledgerSort]);

  const refreshRegistry = useCallback(async () => {
    setRegistryLoading(true);
    const available = await fetchStats();
    if (available) {
      await Promise.all([fetchWeights(), fetchLedger()]);
    }
    setRegistryLoading(false);
  }, [fetchStats, fetchWeights, fetchLedger]);

  useEffect(() => {
    refreshRegistry();
  }, [refreshRegistry]);

  const selectWeight = async (sha256) => {
    if (!sha256 || sha256 === selectedSha) {
      setSelectedSha(null);
      setWeightDetail(null);
      return;
    }
    setSelectedSha(sha256);
    setWeightDetail(null);
    try {
      setWeightDetail(await apiGet(`/registry/weights/${sha256}`));
    } catch (err) {
      console.error('[useRegistry] Error fetching weight detail:', err);
      setRegistryError(errorMessage(err, '無法取得權重明細'));
    }
  };

  const deleteRegistryWeight = async (sha256) => {
    try {
      await apiDelete(`/registry/weights/${sha256}`);
      if (selectedSha === sha256) {
        setSelectedSha(null);
        setWeightDetail(null);
      }
      await refreshRegistry();
      return true;
    } catch (err) {
      console.error('[useRegistry] Error deleting weight:', err);
      setRegistryError(errorMessage(err, '刪除失敗'));
      return false;
    }
  };

  /** 點同一欄切換升降冪，點別欄則以降冪開始（數值指標最常見的意圖是「看最大的」）。 */
  const toggleWeightSort = (field) =>
    setWeightSort((prev) => ({
      order_by: field,
      order: prev.order_by === field && prev.order === 'desc' ? 'asc' : 'desc',
    }));

  const toggleLedgerSort = (field) =>
    setLedgerSort((prev) => ({
      order_by: field,
      order: prev.order_by === field && prev.order === 'desc' ? 'asc' : 'desc',
    }));

  return {
    registryStats,
    registryAvailable,
    registryWeights: weights,
    registryWeightsTotal: weightsTotal,
    registryLedger: ledger,
    registrySelectedSha: selectedSha,
    registryWeightDetail: weightDetail,
    registryLoading,
    registryError,
    setRegistryError,
    registryQuery: query,
    setRegistryQuery: setQuery,
    registryWeightSort: weightSort,
    registryLedgerSort: ledgerSort,
    toggleRegistryWeightSort: toggleWeightSort,
    toggleRegistryLedgerSort: toggleLedgerSort,
    refreshRegistry,
    selectRegistryWeight: selectWeight,
    deleteRegistryWeight,
  };
};
