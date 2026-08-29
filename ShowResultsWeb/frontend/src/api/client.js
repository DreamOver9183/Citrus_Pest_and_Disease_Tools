/**
 * 統一的 API 客戶端。
 *
 * 後端所有 JSON 端點都回同一個信封（見 backend/app/core/envelope.py）：
 *
 *   { status, data, error: { code, message, details }, meta }
 *
 * 這一層做兩件事，讓呼叫端完全看不到信封：
 *
 * 1. 成功時直接回 `data`（需要 `meta` 的用 `apiGetWithMeta`）。
 * 2. 失敗時**丟出** ApiError。這是關鍵改變——在此之前後端用 HTTP 200 夾帶
 *    `{"status": "error"}`，axios 的錯誤路徑形同虛設，每個 hook 都得自己寫
 *    `if (res.data.status === 'success')` 再補一段 `err.response?.data?.detail ||
 *    err.message` 的 fallback。現在錯誤就是錯誤，一個 try/catch 全包。
 *
 * 於是 hook 裡的錯誤處理從「三種形狀各判一次」收斂成 `catch (err) { err.message }`。
 */
import axios from 'axios';

/** 呼叫端唯一需要認得的錯誤型別。`code` 供程式判斷，`message` 直接給使用者看。 */
export class ApiError extends Error {
  constructor({ code, message, details, status }) {
    super(message || '未知的錯誤');
    this.name = 'ApiError';
    this.code = code || 'unknown_error';
    this.details = details || null;
    this.status = status || 0;
  }
}

const http = axios.create({ baseURL: '/api' });

http.interceptors.response.use(
  (res) => res,
  (err) => {
    // 被 AbortController 取消的請求必須原樣穿透：useLiveDemoInference 依賴
    // axios.isCancel() 靜默忽略它們，包成 ApiError 會讓使用者看到假的錯誤訊息。
    if (axios.isCancel(err)) return Promise.reject(err);

    const body = err.response?.data;
    if (body && body.error) {
      return Promise.reject(new ApiError({ ...body.error, status: err.response.status }));
    }
    // 連不到後端、逾時、或回了非信封內容（例如反向代理的錯誤頁）
    return Promise.reject(
      new ApiError({
        code: err.response ? 'unexpected_response' : 'network_error',
        message: err.response
          ? `伺服器回應格式不正確（HTTP ${err.response.status}）`
          : '無法連線到後端 API',
        status: err.response?.status || 0,
      }),
    );
  },
);

function unwrap(res) {
  return res.data?.data ?? null;
}

export async function apiGet(path, config) {
  return unwrap(await http.get(path, config));
}

/** 需要分頁總數等資訊時用這支，回 { data, meta }。 */
export async function apiGetWithMeta(path, config) {
  const res = await http.get(path, config);
  return { data: res.data?.data ?? null, meta: res.data?.meta ?? null };
}

export async function apiPost(path, body, config) {
  return unwrap(await http.post(path, body, config));
}

export async function apiDelete(path, config) {
  return unwrap(await http.delete(path, config));
}

/**
 * 檔案上傳。三個端點（upload-model / upload-dataset / inference）刻意維持
 * multipart——二進位內容沒辦法塞進 JSON。附帶的參數一律放進同一份 FormData，
 * 不用 query string，這樣「POST 的參數都在 body 裡」才是一條沒有例外的規則。
 */
export async function apiUpload(path, formData, config = {}) {
  return unwrap(
    await http.post(path, formData, {
      ...config,
      headers: { 'Content-Type': 'multipart/form-data', ...(config.headers || {}) },
    }),
  );
}

/** 統一的錯誤訊息取用點，避免每個 catch 各自寫一套 fallback。 */
export function errorMessage(err, fallback = '操作失敗') {
  if (err instanceof ApiError) return err.message;
  return err?.message || fallback;
}

export { axios };
export default http;
