"""Pydantic response models shared across routers.

These exist to make the API contract visible in /docs (Swagger UI). Fields that
carry heterogeneous data at runtime (e.g. `epochs` can be an int parsed from
YAML or the literal string "N/A") are intentionally typed loosely with `Any`
rather than forced into a narrow type — the goal here is a documented, stable
JSON shape, not strict validation that could reject/alter existing responses.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class SessionOut(BaseModel):
    session_id: str
    # "local_library" 代表來自本機資料夾掃描（不落地持久化）；一般上傳為 None
    source: Optional[str] = None
    zip_name: Optional[str] = None
    source_type: Optional[str] = None
    format_label: Optional[str] = None
    model_arch: Optional[str] = None
    custom_name: Optional[str] = None
    dir_path: Optional[str] = None
    weights_path: Optional[str] = None
    weights_size_mb: Optional[float] = None
    epochs: Optional[Any] = None
    optimizer: Optional[Any] = None
    model_cfg: Optional[Any] = None
    metrics_summary: Optional[Dict[str, Any]] = None
    metrics_csv_path: Optional[str] = None
    results_png: Optional[str] = None
    confusion_matrix: Optional[str] = None

    model_config = {"extra": "allow"}


class SessionsResponse(BaseModel):
    status: str
    sessions: Dict[str, SessionOut]


class UploadResponse(BaseModel):
    status: str
    registered_sessions: Optional[List[str]] = None
    sessions: Optional[Dict[str, SessionOut]] = None
    message: Optional[str] = None


class ErrorResponse(BaseModel):
    status: str = "error"
    message: str


class DeviceDetails(BaseModel):
    model_config = {"extra": "allow"}


class DeviceInfo(BaseModel):
    id: str
    label: str
    type: str
    available: bool
    details: Dict[str, Any] = {}


class DevicesResponse(BaseModel):
    status: str
    available_devices: List[DeviceInfo]
    current_device: str
    current_device_label: str


class SetDeviceResponse(BaseModel):
    status: str
    current_device: str
    current_device_label: str


class InferenceResponse(BaseModel):
    status: str
    url: str
    original_url: str
    counts: int
    detections: Dict[str, int]
    device_used: str


class MetricsResponse(BaseModel):
    status: str
    url: str
    source_path: str


# --- 資料集分析 ---
# 分析器一律輸出所有欄位（無值時給 None/0/[]）。原因：路由使用
# response_model_exclude_unset=True，任何條件式省略的 key 會直接從 JSON 消失，
# 在前端變成 undefined。
class DatasetIssue(BaseModel):
    level: str
    code: str
    message: str
    detail: Optional[str] = None
    samples: List[str] = []

    model_config = {"extra": "allow"}


class DatasetClassStat(BaseModel):
    id: Any
    name: str
    name_zh: Optional[str] = None
    count: int = 0
    pct: float = 0.0
    per_split: Dict[str, int] = {}

    model_config = {"extra": "allow"}


class DatasetSplitStat(BaseModel):
    name: str
    images: int = 0
    labels: int = 0
    annotations: int = 0
    background_images: int = 0
    images_without_label: int = 0
    labels_without_image: int = 0
    annotations_per_image: float = 0.0
    class_counts: Dict[str, int] = {}

    model_config = {"extra": "allow"}


class DatasetDefinition(BaseModel):
    kind: str
    filename: str
    text: str
    truncated: bool = False

    model_config = {"extra": "allow"}


class DatasetPrefixCheck(BaseModel):
    status: str
    checked: int = 0
    matched: int = 0
    mismatched: int = 0
    samples: List[str] = []

    model_config = {"extra": "allow"}


class DatasetStatsOut(BaseModel):
    schema_version: int
    dataset_id: str
    zip_name: Optional[str] = None
    created_at: Optional[str] = None
    format: Optional[str] = None
    analysis_depth: Optional[str] = None
    verified: bool = False
    unverified_note: Optional[str] = None
    root_prefix: str = ""
    detected_candidates: List[str] = []
    zip_size_mb: float = 0.0
    uncompressed_size_mb: float = 0.0
    member_count: int = 0
    analysis_ms: int = 0
    truncated: bool = False
    total_images: int = 0
    total_annotations: int = 0
    total_label_files: int = 0
    background_images: int = 0
    splits: List[DatasetSplitStat] = []
    declared_nc: Optional[int] = None
    declared_names: Optional[List[str]] = None
    max_class_id_found: Optional[int] = None
    classes: List[DatasetClassStat] = []
    prefix_check: Optional[DatasetPrefixCheck] = None
    definition: Optional[DatasetDefinition] = None
    # 來源目錄絕對路徑；僅本機資料夾掃描會有值。經 normcase，且 ZIP 來源時是
    # 「.zip 路徑 + 內層前綴」的黏合，不可直接開啟——要讀檔請用下面兩個欄位。
    source_path: Optional[str] = None
    # 可開啟的容器（資料夾或 .zip 檔）與資料集根目錄在其中的相對前綴
    source_container: Optional[str] = None
    source_inner_prefix: Optional[str] = None
    issues: List[DatasetIssue] = []

    model_config = {"extra": "allow"}


class DatasetsResponse(BaseModel):
    status: str
    datasets: Dict[str, DatasetStatsOut] = {}


class DatasetAnalyzeResponse(BaseModel):
    status: str
    dataset_id: Optional[str] = None
    dataset: Optional[DatasetStatsOut] = None
    datasets: Optional[Dict[str, DatasetStatsOut]] = None


# --- 模型格式匯出 ---
# 與資料集分析同樣的契約：export_service._job_public() 逐欄輸出所有欄位，
# 因為 response_model_exclude_unset=True 會把缺席的 key 從 JSON 剪掉。
class ExportFormatInfo(BaseModel):
    format: str
    label: str
    suffix: str
    description: Optional[str] = None
    available: bool = False
    reason: Optional[str] = None
    # "platform"（此平台不支援）或 "dependency"（套件未安裝）——前端據此給不同的下一步建議
    reason_kind: Optional[str] = None
    missing: List[str] = []
    warnings: List[str] = []

    model_config = {"extra": "allow"}


class ExportCapabilitiesResponse(BaseModel):
    status: str
    formats: List[ExportFormatInfo] = []
    any_available: bool = False


class ExportJobOut(BaseModel):
    job_id: str
    session_id: Optional[str] = None
    session_name: Optional[str] = None
    format: Optional[str] = None
    state: Optional[str] = None
    stage: Optional[str] = None
    stage_label: Optional[str] = None
    progress: int = 0
    message: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    artifact_name: Optional[str] = None
    artifact_size_mb: Optional[float] = None
    imgsz: Optional[Any] = None
    download_url: Optional[str] = None
    log_tail: List[str] = []

    model_config = {"extra": "allow"}


class ExportJobResponse(BaseModel):
    status: str
    job: Optional[ExportJobOut] = None


class ExportJobsResponse(BaseModel):
    status: str
    jobs: Dict[str, ExportJobOut] = {}


# --- 本機資料夾掃描 ---
class LocalLibraryInfoResponse(BaseModel):
    status: str
    path: str
    exists: bool


class LocalLibraryCandidate(BaseModel):
    """掃描到的一個可用項目。使用者勾選後才會真正註冊。"""
    candidate_id: str
    kind: str                       # "model" | "dataset"
    source_kind: str                # run_dir | weight_file | zip_run | dataset_dir | dataset_zip
    name: str
    rel_path: str
    size_mb: Optional[float] = None
    detail: Optional[str] = None
    already_registered: bool = False


class LocalLibraryScanResponse(BaseModel):
    """掃描結果。純唯讀——這個回應不代表任何東西已被註冊。"""
    status: str
    candidates: List[LocalLibraryCandidate] = []
    total_models: int = 0
    total_datasets: int = 0
    message: Optional[str] = None


class LocalLibraryRegisterRequest(BaseModel):
    candidate_ids: List[str] = []


class LocalLibraryRegisterResponse(BaseModel):
    status: str
    registered_sessions: List[str] = []
    registered_datasets: List[str] = []
    skipped: int = 0
    failed: List[str] = []
    message: Optional[str] = None
    sessions: Dict[str, SessionOut] = {}
    datasets: Dict[str, DatasetStatsOut] = {}


# --- 驗證評估 ---------------------------------------------------------------

class EvalVocabCheck(BaseModel):
    """模型與資料集的類別表比對結果。status: match | name_drift | mismatch"""
    status: str
    model_nc: int = 0
    dataset_nc: int = 0
    model_names: List[str] = []
    dataset_names: List[str] = []
    differences: List[Dict[str, Any]] = []
    message: Optional[str] = None


class EvalOverall(BaseModel):
    map50: float
    map50_95: float
    precision: float
    recall: float


class EvalClassResult(BaseModel):
    class_id: int
    name: str
    precision: float
    recall: float
    ap50: float
    ap50_95: float


class EvalSizeProfile(BaseModel):
    """每類別的標註框尺寸剖面，與 AP 並排即為小物件表現的證據。"""
    class_id: int
    name: str
    boxes: int
    median_area_pct: Optional[float] = None
    min_area_pct: Optional[float] = None
    max_area_pct: Optional[float] = None
    tiny_pct: Optional[float] = None


class EvalJobOut(BaseModel):
    job_id: str
    session_id: Optional[str] = None
    session_name: Optional[str] = None
    dataset_id: Optional[str] = None
    dataset_name: Optional[str] = None
    split: Optional[str] = None
    state: str
    stage: str
    stage_label: str
    progress: int = 0
    message: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    image_count: Optional[int] = None
    vocab_check: Optional[EvalVocabCheck] = None
    overall: Optional[EvalOverall] = None
    per_class: Optional[List[EvalClassResult]] = None
    size_profile: Optional[List[EvalSizeProfile]] = None
    speed_ms: Optional[Dict[str, float]] = None
    plot_urls: Optional[Dict[str, str]] = None
    log_tail: List[str] = []

    model_config = {"extra": "allow"}


class EvalTargetDataset(BaseModel):
    """可評估的資料集及其原因說明（不可評估時仍會列出，比照匯出的「顯示但停用」慣例）。"""
    dataset_id: str
    name: str
    format: Optional[str] = None
    available: bool
    reason: Optional[str] = None
    splits: List[str] = []
    default_split: Optional[str] = None


class EvalTargetsResponse(BaseModel):
    status: str
    datasets: List[EvalTargetDataset] = []
    sessions: List[Dict[str, Any]] = []
    message: Optional[str] = None


class EvalSubmitRequest(BaseModel):
    session_id: str
    dataset_id: str
    split: Optional[str] = None


class EvalJobResponse(BaseModel):
    status: str
    job: Optional[EvalJobOut] = None
    message: Optional[str] = None


class EvalJobsResponse(BaseModel):
    status: str
    jobs: List[EvalJobOut] = []


# --- 報告匯出 ---------------------------------------------------------------

class ReportOut(BaseModel):
    report_id: str
    filename: str
    title: str
    created_at: str
    size_kb: float
    job_ids: List[str] = []
    download_url: str


class ReportGenerateRequest(BaseModel):
    job_ids: List[str] = []
    title: Optional[str] = None


class ReportResponse(BaseModel):
    status: str
    report: Optional[ReportOut] = None
    message: Optional[str] = None


class ReportsResponse(BaseModel):
    status: str
    reports: List[ReportOut] = []
