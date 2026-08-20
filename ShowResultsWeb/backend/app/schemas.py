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
