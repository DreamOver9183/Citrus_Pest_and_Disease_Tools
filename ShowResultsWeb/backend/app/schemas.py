"""各路由共用的 Pydantic 模型。

分成三類：

- **payload 模型**（`*Payload`）——放進 `ApiResponse.data` 的東西。**不含 `status`**，
  因為狀態由信封的外層負責（見 `app/core/envelope.py`）。
- **request 模型**（`*Request`）——POST/PUT 的 JSON body。除了三個真正的檔案上傳
  端點（upload-model / upload-dataset / inference）仍走 multipart 之外，所有寫入
  端點都吃 JSON。
- **元素模型**——出現在 payload 內部的個別項目（`SessionOut`、`EvalJobOut` …）。

執行期形狀異質的欄位（例如 `epochs` 可能是 YAML 解析出的 int，也可能是字串 "N/A"）
刻意用 `Any` 寬鬆標註：這裡的目的是讓 `/docs` 呈現穩定的 JSON 契約，而不是嚴格驗證到
會改寫或拒絕既有回應。

**所有欄位都必須有預設值。** 路由不再使用 `response_model_exclude_unset=True`，
未賦值的欄位會以預設值出現在 JSON 中（而不是消失成 `undefined`），這是刻意的改變。
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# --- Session ---------------------------------------------------------------

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
    # 權重檔內容的 SHA-256，也是權重登錄簿的主鍵。註冊時計算，失敗時為 None。
    weight_sha256: Optional[str] = None

    model_config = {"extra": "allow"}


class SessionsPayload(BaseModel):
    sessions: Dict[str, SessionOut] = {}


class UploadPayload(BaseModel):
    registered_sessions: List[str] = []
    sessions: Dict[str, SessionOut] = {}
    message: Optional[str] = None


class UpdateSessionNameRequest(BaseModel):
    session_id: str
    custom_name: str


# --- 裝置 -------------------------------------------------------------------

class DeviceInfo(BaseModel):
    id: str
    label: str
    type: str
    available: bool
    details: Dict[str, Any] = {}


class DevicesPayload(BaseModel):
    available_devices: List[DeviceInfo] = []
    current_device: str
    current_device_label: str


class SetDeviceRequest(BaseModel):
    device_id: str


class SetDevicePayload(BaseModel):
    current_device: str
    current_device_label: str


# --- 推論與指標圖 -----------------------------------------------------------

class InferencePayload(BaseModel):
    url: str
    original_url: str
    counts: int
    detections: Dict[str, int] = {}
    device_used: str


class MetricsPayload(BaseModel):
    url: str
    source_path: str


# --- 資料集分析 -------------------------------------------------------------

class DatasetIssue(BaseModel):
    level: str
    code: str
    message: str
    detail: Optional[str] = None
    samples: List[str] = []

    model_config = {"extra": "allow"}


class DatasetClassStat(BaseModel):
    id: Any = None
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
    schema_version: int = 0
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


class DatasetsPayload(BaseModel):
    datasets: Dict[str, DatasetStatsOut] = {}


class DatasetAnalyzePayload(BaseModel):
    dataset_id: Optional[str] = None
    dataset: Optional[DatasetStatsOut] = None
    datasets: Dict[str, DatasetStatsOut] = {}


# --- 模型格式匯出 -----------------------------------------------------------

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


class ExportCapabilitiesPayload(BaseModel):
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


class ExportSubmitRequest(BaseModel):
    session_id: str
    format: str = "onnx"


class ExportJobPayload(BaseModel):
    job: Optional[ExportJobOut] = None


class ExportJobsPayload(BaseModel):
    jobs: Dict[str, ExportJobOut] = {}


# --- 本機資料夾掃描 ---------------------------------------------------------

class LocalLibraryInfoPayload(BaseModel):
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


class LocalLibraryScanPayload(BaseModel):
    """掃描結果。純唯讀——這個回應不代表任何東西已被註冊。"""
    candidates: List[LocalLibraryCandidate] = []
    total_models: int = 0
    total_datasets: int = 0
    message: Optional[str] = None


class LocalLibraryRegisterRequest(BaseModel):
    candidate_ids: List[str] = []


class LocalLibraryRegisterPayload(BaseModel):
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
    # 由 P/R 導出的調和平均，與 mAP 同為門檻無關的巨觀指標
    f1: Optional[float] = None
    # ultralytics 的綜合分數：0.1·mAP50 + 0.9·mAP50-95
    fitness: Optional[float] = None


class EvalMicroAccuracy(BaseModel):
    """邊界框級別的 TP/FP/FN 與其四項衍生指標，依《效能指標定義與評測方法》§2。

    `micro_accuracy` 即 TP/(TP+FP+FN)——TN=0 簡化下的 Accuracy，也就是 Jaccard index。

    **門檻相依**：這些數字由 ultralytics 的混淆矩陣導出，而該矩陣是在固定的 conf / IoU
    門檻下累積的（見 conf_threshold / iou_threshold 兩欄）。與對所有門檻積分的 mAP
    不是同一類指標，並列解讀前務必看清楚門檻。
    """
    micro_accuracy: Optional[float] = None
    micro_precision: Optional[float] = None
    micro_recall: Optional[float] = None
    micro_f1: Optional[float] = None
    tp: int = 0
    fp: int = 0
    fn: int = 0
    conf_threshold: Optional[float] = None
    iou_threshold: Optional[float] = None
    per_class: List[Dict[str, Any]] = []


class EvalClassResult(BaseModel):
    class_id: int
    name: str
    precision: float
    recall: float
    ap50: float
    ap50_95: float
    # 該類別在混淆矩陣門檻下的 Accuracy（Jaccard index）。沒有混淆矩陣時為 None。
    accuracy: Optional[float] = None


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
    weight_sha256: Optional[str] = None
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
    micro: Optional[EvalMicroAccuracy] = None
    per_class: List[EvalClassResult] = []
    size_profile: List[EvalSizeProfile] = []
    speed_ms: Dict[str, float] = {}
    plot_urls: Dict[str, str] = {}
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


class EvalTargetSession(BaseModel):
    session_id: str
    name: str
    model_arch: Optional[str] = None
    epochs: Optional[Any] = None
    available: bool = False
    reason: Optional[str] = None


class EvalTargetsPayload(BaseModel):
    datasets: List[EvalTargetDataset] = []
    sessions: List[EvalTargetSession] = []


class EvalSubmitRequest(BaseModel):
    session_id: str
    dataset_id: str
    split: Optional[str] = None


class EvalJobPayload(BaseModel):
    job: Optional[EvalJobOut] = None
    message: Optional[str] = None


class EvalJobsPayload(BaseModel):
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


class ReportPayload(BaseModel):
    report: Optional[ReportOut] = None
    message: Optional[str] = None


class ReportsPayload(BaseModel):
    reports: List[ReportOut] = []


# --- 權重登錄簿 -------------------------------------------------------------

class RegistryTrainingRun(BaseModel):
    """訓練當時的紀錄：完整超參數 + results.csv 最後一列。"""
    hyperparameters: Dict[str, Any] = {}
    final_metrics: Dict[str, Any] = {}
    epochs: Optional[Any] = None
    optimizer: Optional[str] = None
    model_cfg: Optional[str] = None
    imgsz: Optional[Any] = None
    batch: Optional[Any] = None
    lr0: Optional[float] = None
    lrf: Optional[float] = None
    momentum: Optional[float] = None
    weight_decay: Optional[float] = None
    patience: Optional[Any] = None
    seed: Optional[Any] = None
    map50: Optional[float] = None
    map50_95: Optional[float] = None
    precision: Optional[float] = None
    recall: Optional[float] = None
    recorded_at: Optional[str] = None


class RegistryEvaluation(BaseModel):
    """本系統實測出來的一次評估。與 EvalJobOut 的差別：這是已落地的長期紀錄。"""
    job_id: str
    weight_sha256: Optional[str] = None
    weight_name: Optional[str] = None
    dataset_name: Optional[str] = None
    dataset_format: Optional[str] = None
    split: Optional[str] = None
    image_count: Optional[int] = None
    map50: Optional[float] = None
    map50_95: Optional[float] = None
    precision: Optional[float] = None
    recall: Optional[float] = None
    f1: Optional[float] = None
    fitness: Optional[float] = None
    micro_accuracy: Optional[float] = None
    micro_precision: Optional[float] = None
    micro_recall: Optional[float] = None
    micro_f1: Optional[float] = None
    micro_tp: Optional[int] = None
    micro_fp: Optional[int] = None
    micro_fn: Optional[int] = None
    conf_threshold: Optional[float] = None
    iou_threshold: Optional[float] = None
    speed_ms: Dict[str, Any] = {}
    per_class: List[Dict[str, Any]] = []
    size_profile: List[Dict[str, Any]] = []
    vocab_status: Optional[str] = None
    vocab_message: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    elapsed_seconds: Optional[float] = None


class RegistryWeight(BaseModel):
    sha256: str
    filename: Optional[str] = None
    display_name: Optional[str] = None
    format_label: Optional[str] = None
    model_arch: Optional[str] = None
    size_mb: Optional[float] = None
    source_type: Optional[str] = None
    source: Optional[str] = None
    source_path: Optional[str] = None
    class_names: List[str] = []
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    evaluation_count: int = 0
    # 該權重歷次評估中的最佳值，供清單直接排序
    best_map50: Optional[float] = None
    best_map50_95: Optional[float] = None
    best_micro_accuracy: Optional[float] = None
    training_run: Optional[RegistryTrainingRun] = None


class RegistryWeightsPayload(BaseModel):
    weights: List[RegistryWeight] = []


class RegistryWeightDetailPayload(BaseModel):
    weight: Optional[RegistryWeight] = None
    training_run: Optional[RegistryTrainingRun] = None
    evaluations: List[RegistryEvaluation] = []


class RegistryEvaluationsPayload(BaseModel):
    evaluations: List[RegistryEvaluation] = []


class RegistryBestEntry(BaseModel):
    metric: str
    value: Optional[float] = None
    weight_sha256: Optional[str] = None
    weight_name: Optional[str] = None
    dataset_name: Optional[str] = None
    split: Optional[str] = None


class RegistryStatsPayload(BaseModel):
    backend: str = "unknown"
    available: bool = False
    total_weights: int = 0
    total_training_runs: int = 0
    total_evaluations: int = 0
    datasets_evaluated: List[str] = []
    best: List[RegistryBestEntry] = []


class RegistryDeletePayload(BaseModel):
    sha256: str
    deleted_evaluations: int = 0
