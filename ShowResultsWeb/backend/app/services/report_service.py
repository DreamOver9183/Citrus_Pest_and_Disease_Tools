"""
把評估結果打包成一份可交付的 HTML 報告。

設計目標是「一個檔案就是全部」：所有圖表以 base64 data URI 內嵌，因此報告可以離線
開啟、可以直接寄出、可以放進附錄，不會出現一堆破圖。這也是為什麼不用 <img src="/api/...">
——那種報告一離開這台機器就壞了。

**PDF 走瀏覽器列印**（模板內含 @media print 規則）。不引入 reportlab：它沒被安裝，
而為了一份報告增加一個相依套件不划算，何況瀏覽器的列印引擎對中文與網頁版面的支援
比手動排版好得多。UI 上必須把這件事講清楚，不要讓使用者去找一顆不存在的 PDF 按鈕。

Jinja2 已隨 torch 安裝（傳遞相依），不需要新增任何套件。

這是 REPORTS_DIR 這個設定項的第一個使用者——它在 config.py 定義了六處，但在本模組
出現之前沒有任何 importer，唯一的作用是開機時建立一個空資料夾。
"""
import base64
import json
import math
import mimetypes
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import REPORTS_DIR

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

_UNSAFE_NAME_CHARS = re.compile(r'[/\\:*?"<>|\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")

# 低於此 AP50 的類別在報告中標為需要注意
WEAK_AP_THRESHOLD = 0.5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_stem(name: str, fallback: str) -> str:
    cleaned = _UNSAFE_NAME_CHARS.sub("", name or "")
    cleaned = _WHITESPACE.sub("_", cleaned.strip()).strip("._")
    return cleaned[:60] if cleaned else fallback


def _data_uri(path: Optional[str]) -> Optional[str]:
    """把圖片檔轉成可內嵌的 data URI。讀不到就回 None，讓模板略過該區塊。"""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            payload = base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return None
    mime = mimetypes.guess_type(path)[0] or "image/png"
    return f"data:{mime};base64,{payload}"


# --------------------------------------------------------------------------- #
# AP × 框面積散點圖
# --------------------------------------------------------------------------- #

def scatter_svg(points: List[Dict[str, Any]], width: int = 720, height: int = 380) -> Optional[str]:
    """
    每類別的 AP50 對中位框面積散點圖——「為什麼需要 P2 檢測層」的那張圖。

    X 軸用 log10：實測這個資料集的中位框面積從 0.19%（潰瘍病）到 52%（煤煙病），
    跨越近三個數量級，線性軸會把所有小物件類別擠成左邊一團而看不出任何結構。

    手寫 SVG 而非 matplotlib：向量圖在列印成 PDF 時不會糊掉，且不需要處理 matplotlib
    在非主執行緒的後端設定問題。
    """
    usable = [p for p in points if p.get("median_area_pct") and p.get("ap50") is not None]
    if len(usable) < 2:
        return None

    pad_l, pad_r, pad_t, pad_b = 62, 24, 20, 52
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    # domain 對齊到整數次方，保證每個十倍刻度都落在範圍內而畫得出格線。
    # 若只取資料的極值，實測會出現「0.187% 到 52.2% 之間只有 1% 與 10% 兩條刻度」
    # 的情形——橫跨 280 倍卻只有兩個參考點，讀者無從判斷距離。
    xs = [math.log10(p["median_area_pct"]) for p in usable]
    x_min = math.floor(min(xs) - 0.15)
    x_max = math.ceil(max(xs) + 0.15)
    if x_max - x_min < 1:
        x_min, x_max = x_min - 1, x_max + 1

    def px(v):
        return pad_l + (math.log10(v) - x_min) / (x_max - x_min) * plot_w

    def py(v):
        return pad_t + (1 - max(0.0, min(1.0, v))) * plot_h

    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="每類別 AP50 對中位框面積散點圖">'
    ]

    # Y 格線（AP 0 ~ 1）
    for i in range(6):
        v = i / 5
        y = py(v)
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{pad_l - 10}" y="{y + 4:.1f}" class="tick tick-y">{v:.1f}</text>')

    # X 格線：每個整數次方一條（0.01% / 0.1% / 1% / 10% …）
    for e in range(math.floor(x_min), math.ceil(x_max) + 1):
        v = 10 ** e
        if not (x_min <= e <= x_max):
            continue
        x = px(v)
        parts.append(f'<line x1="{x:.1f}" y1="{pad_t}" x2="{x:.1f}" y2="{pad_t + plot_h}" class="grid"/>')
        label = f"{v:g}%"
        parts.append(f'<text x="{x:.1f}" y="{pad_t + plot_h + 18}" class="tick tick-x">{label}</text>')

    parts.append(
        f'<text x="{pad_l + plot_w / 2:.0f}" y="{height - 10}" class="axis-label">'
        f'中位標註框面積（佔整張影像，對數刻度）</text>'
    )
    parts.append(
        f'<text x="14" y="{pad_t + plot_h / 2:.0f}" class="axis-label" '
        f'transform="rotate(-90 14 {pad_t + plot_h / 2:.0f})">AP@50</text>'
    )

    for p in usable:
        x, y = px(p["median_area_pct"]), py(p["ap50"])
        weak = p["ap50"] < WEAK_AP_THRESHOLD
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" '
            f'class="{"dot dot-weak" if weak else "dot"}"><title>'
            f'{p["name"]}: AP50 {p["ap50"]:.3f}，中位框 {p["median_area_pct"]:.3f}%，'
            f'{p.get("boxes", 0)} 框</title></circle>'
        )
        # 靠近右邊界的點把標籤翻到左側，否則類別名會被畫布截掉
        if x > pad_l + plot_w * 0.72:
            parts.append(
                f'<text x="{x - 9:.1f}" y="{y + 4:.1f}" class="dot-label" '
                f'text-anchor="end">{p["name"]}</text>'
            )
        else:
            parts.append(f'<text x="{x + 9:.1f}" y="{y + 4:.1f}" class="dot-label">{p["name"]}</text>')

    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# 組裝
# --------------------------------------------------------------------------- #

def _environment_info() -> Dict[str, Any]:
    """記錄產生報告當下的環境，讓數字日後仍可追溯。"""
    info = {"generated_at": _now_iso(), "torch": None, "ultralytics": None, "device": "cpu"}
    try:
        import torch
        info["torch"] = torch.__version__
        info["device"] = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        pass
    try:
        import ultralytics
        info["ultralytics"] = ultralytics.__version__
    except Exception:
        pass
    return info


def _build_job_view(job: Dict[str, Any], plot_paths: Dict[str, str]) -> Dict[str, Any]:
    """把一個 job 整理成模板要的形狀，並把逐類別指標與尺寸剖面併起來。"""
    size_by_id = {s["class_id"]: s for s in (job.get("size_profile") or [])}
    rows = []
    for entry in (job.get("per_class") or []):
        size = size_by_id.get(entry["class_id"], {})
        rows.append({
            **entry,
            "boxes": size.get("boxes"),
            "median_area_pct": size.get("median_area_pct"),
            "tiny_pct": size.get("tiny_pct"),
            "weak": entry.get("ap50", 1.0) < WEAK_AP_THRESHOLD,
        })
    rows.sort(key=lambda r: r.get("ap50") if r.get("ap50") is not None else 1.0)

    return {
        "job_id": job.get("job_id"),
        "session_name": job.get("session_name"),
        "dataset_name": job.get("dataset_name"),
        "split": job.get("split"),
        "image_count": job.get("image_count"),
        "elapsed_seconds": job.get("elapsed_seconds"),
        "overall": job.get("overall") or {},
        # 舊 manifest（本功能之前產生的）沒有 micro 欄位；給 {} 讓模板的
        # selectattr('micro') 直接把它濾掉，而不是在渲染時炸開。
        "micro": job.get("micro") or {},
        "speed_ms": job.get("speed_ms") or {},
        "vocab_check": job.get("vocab_check") or {},
        "rows": rows,
        "scatter": scatter_svg(rows),
        "plots": {key: _data_uri(path) for key, path in (plot_paths or {}).items()},
    }


def _dataset_view(stats: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not stats:
        return None
    return {
        "name": stats.get("zip_name"),
        "format": stats.get("format"),
        "total_images": stats.get("total_images"),
        "total_annotations": stats.get("total_annotations"),
        "background_images": stats.get("background_images"),
        "declared_nc": stats.get("declared_nc"),
        "splits": stats.get("splits") or [],
        "classes": stats.get("classes") or [],
        "issues": [i for i in (stats.get("issues") or []) if i.get("level") in ("error", "warning")],
    }


def generate_report(
    jobs: List[Dict[str, Any]],
    plot_paths_by_job: Dict[str, Dict[str, str]],
    dataset_stats: Optional[Dict[str, Any]] = None,
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """
    渲染報告並寫入 REPORTS_DIR，回傳可放進 API 回應的中繼資料。

    `jobs` 必須都是已完成的評估。多個 job 會並列成對照表——那正是「共同測試集上的
    公平比較」的產出，也是這份報告存在的主要理由。
    """
    if not jobs:
        raise ValueError("沒有可放進報告的評估結果")

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report.html.j2")

    views = [_build_job_view(job, plot_paths_by_job.get(job["job_id"], {})) for job in jobs]
    splits = sorted({v["split"] for v in views if v["split"]})
    datasets = sorted({v["dataset_name"] for v in views if v["dataset_name"]})
    comparable = len(datasets) == 1 and len(splits) == 1

    report_title = title or f"柑橘病蟲害模型驗證報告（{datasets[0] if datasets else '多資料集'}）"
    html = template.render(
        title=report_title,
        env=_environment_info(),
        views=views,
        comparable=comparable,
        datasets=datasets,
        splits=splits,
        dataset=_dataset_view(dataset_stats),
        weak_threshold=WEAK_AP_THRESHOLD,
    )

    report_id = f"rep_{uuid.uuid4().hex[:8]}"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{_safe_stem(report_title, 'report')}_{stamp}.html"
    report_dir = Path(REPORTS_DIR) / report_id
    report_dir.mkdir(parents=True, exist_ok=True)
    target = report_dir / filename
    target.write_text(html, encoding="utf-8")

    meta = {
        "report_id": report_id,
        "filename": filename,
        "title": report_title,
        "created_at": _now_iso(),
        "size_kb": round(target.stat().st_size / 1024, 1),
        "job_ids": [v["job_id"] for v in views],
        "download_url": f"/api/reports/{report_id}/download",
    }
    with open(report_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


def list_reports() -> List[Dict[str, Any]]:
    """從磁碟列出既有報告。刻意不維護記憶體索引——報告數量少，檔案本身就是真相。"""
    base = Path(REPORTS_DIR)
    if not base.exists():
        return []
    reports = []
    for entry in base.iterdir():
        meta_file = entry / "meta.json"
        if not entry.is_dir() or not meta_file.exists():
            continue
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if (entry / meta.get("filename", "")).exists():
            reports.append(meta)
    reports.sort(key=lambda m: m.get("created_at") or "", reverse=True)
    return reports


def report_path(report_id: str) -> Optional[str]:
    """回傳報告 HTML 的實體路徑，並確認它確實落在 REPORTS_DIR 之內。"""
    base = Path(REPORTS_DIR)
    entry = base / report_id
    meta_file = entry / "meta.json"
    if not meta_file.exists():
        return None
    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    target = entry / meta.get("filename", "")
    try:
        base_real = os.path.realpath(base)
        target_real = os.path.realpath(target)
        if os.path.commonpath([base_real, target_real]) != base_real:
            return None
    except ValueError:
        return None
    return target_real if os.path.exists(target_real) else None


def delete_report(report_id: str) -> bool:
    entry = Path(REPORTS_DIR) / report_id
    if not (entry / "meta.json").exists():
        return False
    shutil.rmtree(entry, ignore_errors=True)
    return True
