"""
成果報告的 API。

把一或多個已完成的評估打包成單一自足的 HTML 檔（圖表以 base64 內嵌），寫進 REPORTS_DIR。
多個評估並列即為「共同測試集上的公平比較」，也就是消融研究要交付的那張表。

PDF 由使用者在瀏覽器按 Ctrl+P 產生——模板已含 @media print 規則。詳見 report_service
的模組註解。
"""
from typing import List, Optional, Union

from fastapi import APIRouter, Body
from fastapi.responses import FileResponse

from app.schemas import ErrorResponse, ReportResponse, ReportsResponse
from app.services import evaluation_service, report_service
from app.services.dataset_manager import ACTIVE_DATASETS, DATASETS_LOCK

router = APIRouter()


@router.post("/reports", response_model=Union[ReportResponse, ErrorResponse], response_model_exclude_unset=True)
def create_report(job_ids: List[str] = Body(default=[], embed=True),
                  title: Optional[str] = Body(default=None, embed=True)):
    if not job_ids:
        return {"status": "error", "message": "請至少選擇一筆評估結果"}

    jobs = []
    plot_paths = {}
    with evaluation_service.EVAL_JOBS_LOCK:
        for jid in job_ids:
            raw = evaluation_service.EVAL_JOBS.get(jid)
            if raw is None or raw.get("state") != "done":
                continue
            jobs.append(evaluation_service._job_public(raw))
            plot_paths[jid] = dict(raw.get("plot_paths") or {})

    if not jobs:
        return {"status": "error", "message": "選取的評估結果都不存在或尚未完成"}

    # 只有在所有評估都用同一個資料集時才附上資料集組成，否則會誤導
    dataset_ids = {j.get("dataset_id") for j in jobs}
    dataset_stats = None
    if len(dataset_ids) == 1:
        with DATASETS_LOCK:
            found = ACTIVE_DATASETS.get(next(iter(dataset_ids)))
            dataset_stats = dict(found) if found else None

    try:
        meta = report_service.generate_report(jobs, plot_paths, dataset_stats, title)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": f"報告產生失敗：{exc}"}

    return {"status": "success", "report": meta, "message": None}


@router.get("/reports", response_model=ReportsResponse, response_model_exclude_unset=True)
def list_reports():
    return {"status": "success", "reports": report_service.list_reports()}


@router.get("/reports/{report_id}/download")
def download_report(report_id: str):
    """
    以附件形式回傳報告。

    走 FileResponse 讓 Starlette 產生 RFC 5987 的 Content-Disposition，中文檔名才能
    正確處理（與匯出下載同樣的理由）。
    """
    path = report_service.report_path(report_id)
    if path is None:
        return {"status": "error", "message": "找不到指定的報告"}
    return FileResponse(path, media_type="text/html", filename=path.split("/")[-1].split("\\")[-1])


@router.get("/reports/{report_id}/view")
def view_report(report_id: str):
    """同一份檔案，但不帶 filename 讓瀏覽器直接內嵌顯示（供 UI 預覽用）。"""
    path = report_service.report_path(report_id)
    if path is None:
        return {"status": "error", "message": "找不到指定的報告"}
    return FileResponse(path, media_type="text/html")


@router.post("/reports/{report_id}/delete", response_model=Union[ReportResponse, ErrorResponse], response_model_exclude_unset=True)
def delete_report(report_id: str):
    if not report_service.delete_report(report_id):
        return {"status": "error", "message": "找不到指定的報告"}
    return {"status": "success", "report": None, "message": "已刪除"}
