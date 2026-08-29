"""
資料集分析器。

輸入一個已開啟的 ZipFile，輸出統計 dict。全程不解壓縮任何影像——圖片數與
檔名取自 ZIP 中央目錄，只有標註文字檔會被讀取。

兩個貫穿全檔的原則：

1. **目錄探索是計數的唯一真相來源，data.yaml 只用於交叉驗證。**
   實測資料集 (Datasets_YOLO26_v5) 的 data.yaml 帶有
   `path: "f:\\115...\\Citrus_YOLO26_Detect"` 這種指向他機、且子目錄根本不存在
   的絕對路徑。若拿它解析 split 位置，結果會是「0 張圖片」而且極難追查。
   因此 yaml 對不上時只產生一則資訊，永遠不影響計數。

2. **所有 key 一律輸出。**
   即使無值也要顯式給 None / 0 / []，讓回應的形狀在任何輸入下都相同。
   （這條原本是為了對抗 `response_model_exclude_unset=True` 會靜默裁掉未賦值欄位；
   該選項已隨 API 信封正規化移除，但「形狀恆定」本身仍是前端最好處理的契約。）
"""
import json
import posixpath
import re
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yaml

from app.core.config import (
    MAX_DATASET_LABEL_FILES,
    MAX_DATASET_TEXT_MB,
    MAX_DATASET_XML_FILES,
)
from app.services.dataset_detector import detect_format, detected_candidates
from app.utils.dataset_zip import (
    JSON_MEMBER_CAP_BYTES,
    TextBudget,
    VirtualTree,
    decode_text,
)
from app.utils.zip_handler import ZipIndexError

SCHEMA_VERSION = 1

DEFINITION_TEXT_CAP = 64 * 1024   # 回傳給前端的定義檔內容上限
MAX_ISSUE_SAMPLES = 20

UNVERIFIED_NOTE = "此格式的解析結果未經真實資料驗證"

# 檔名中的類別提示。實測 v5 資料集使用 synth_aug_cls3_00042.jpg 這種命名，
# 4,098 個檔案比對結果 100% 命中，是可靠的交叉檢查訊號。
# 刻意只支援這種「數字即類別索引」的通用形式，不硬編任何專案特有的
# 語意前綴表（例如舊版 12 類的 H_MC_/P_AP_LD_）——那種對照表一旦資料集
# 改版就會變成主動錯誤的資訊。
CLASS_HINT_RE = re.compile(r"cls(\d+)", re.IGNORECASE)


def _issue(level: str, code: str, message: str, detail: Optional[str] = None,
           samples: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "level": level,
        "code": code,
        "message": message,
        "detail": detail,
        "samples": samples or [],
    }


def _base_result(zip_name: str) -> Dict[str, Any]:
    """所有欄位的預設值。條件式省略欄位會被 exclude_unset 剪掉，故一律顯式給值。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": f"ds_{uuid.uuid4().hex[:8]}",
        "zip_name": zip_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "format": None,
        "analysis_depth": "basic",
        "verified": False,
        "unverified_note": None,
        "root_prefix": "",
        "detected_candidates": [],
        "zip_size_mb": 0.0,
        "uncompressed_size_mb": 0.0,
        "member_count": 0,
        "analysis_ms": 0,
        "truncated": False,
        "total_images": 0,
        "total_annotations": 0,
        "total_label_files": 0,
        "background_images": 0,
        "splits": [],
        "declared_nc": None,
        "declared_names": None,
        "max_class_id_found": None,
        "classes": [],
        "prefix_check": {
            "status": "not_applicable",
            "checked": 0,
            "matched": 0,
            "mismatched": 0,
            "samples": [],
        },
        "definition": None,
        # 來源目錄的絕對路徑。僅 LocalLibrary 掃描會填值；ZIP 上傳恆為 None。
        # 同時作為去重鍵與「不寫入 datasets.json」的持久化過濾標記。
        # 注意它經過 normcase 且對 ZIP 來源是「檔案路徑 + 內層前綴」的黏合，不可直接開啟——
        # 要真正讀取檔案請用下面兩個欄位。
        "source_path": None,
        # 可開啟的容器（資料夾路徑或 .zip 檔路徑）與資料集根目錄在容器內的相對前綴。
        # 兩者同樣只有 LocalLibrary 來源會填值。
        "source_container": None,
        "source_inner_prefix": None,
        "issues": [],
    }


# --------------------------------------------------------------------------- #
# YOLO
# --------------------------------------------------------------------------- #

def _parse_data_yaml(reader, yaml_path: str,
                     issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    """解析 data.yaml。任何失敗都降級為警告，不中斷分析。"""
    out = {"nc": None, "names": None, "raw_text": None, "filename": posixpath.basename(yaml_path)}
    try:
        raw = reader.read(yaml_path)
    except ZipIndexError as exc:
        issues.append(_issue("warning", "W_NO_DATA_YAML", "無法讀取 data.yaml", str(exc)))
        return out

    text = decode_text(raw)
    out["raw_text"] = text
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        issues.append(_issue("warning", "W_NO_DATA_YAML", "data.yaml 格式錯誤，已略過其宣告內容", str(exc)))
        return out

    if not isinstance(parsed, dict):
        issues.append(_issue("warning", "W_NO_DATA_YAML", "data.yaml 內容不是有效的設定物件"))
        return out

    # nc 可能被寫成字串
    nc = parsed.get("nc")
    if nc is not None:
        try:
            out["nc"] = int(nc)
        except (TypeError, ValueError):
            issues.append(_issue("warning", "W_NO_DATA_YAML", f"data.yaml 的 nc 無法解析為整數: {nc!r}"))

    # names 可能是 list，也可能是新版 Ultralytics 的 {0: 'a', 1: 'b'} dict
    names = parsed.get("names")
    if isinstance(names, list):
        out["names"] = [str(n) for n in names]
    elif isinstance(names, dict):
        try:
            out["names"] = [str(names[k]) for k in sorted(names, key=lambda x: int(x))]
        except (TypeError, ValueError):
            out["names"] = [str(v) for v in names.values()]

    # path: 常指向訓練當下的機器路徑，在此無法解析屬正常現象
    if parsed.get("path"):
        issues.append(_issue(
            "info", "I_YAML_KEY_DIR_MAPPING",
            "data.yaml 的 path 指向訓練當時的本機絕對路徑，已忽略",
            str(parsed.get("path")),
        ))

    # 記錄 yaml key 與實際目錄名的差異（val: -> valid/ 是最常見的一種）
    for key in ("train", "val", "test"):
        value = parsed.get(key)
        if isinstance(value, str) and value:
            head = value.replace("\\", "/").strip("/").split("/")[0]
            if head and head != key:
                issues.append(_issue(
                    "info", "I_YAML_KEY_DIR_MAPPING",
                    f"data.yaml 的 {key}: 指向 {head}/ 目錄（鍵名與目錄名不同，屬正常）",
                    value,
                ))
    return out


def _scan_label_file(text: str, malformed: List[str], rel_path: str) -> Optional[List[int]]:
    """
    解析單一 YOLO 標註檔，回傳其中的 class id 清單。

    空檔回傳 []（代表負樣本／背景影像），呼叫端據此累計 background_images。
    """
    stripped = text.strip()
    if not stripped:
        return []

    ids: List[int] = []
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        try:
            class_id = int(parts[0])
        except (ValueError, IndexError):
            if len(malformed) < MAX_ISSUE_SAMPLES:
                malformed.append(f"{rel_path}: {line[:60]}")
            continue
        # bbox 需 5 欄；多邊形需 1+偶數個座標且至少 3 點
        if len(parts) < 5 or (len(parts) > 5 and (len(parts) % 2 == 0 or len(parts) < 7)):
            if len(malformed) < MAX_ISSUE_SAMPLES:
                malformed.append(f"{rel_path}: 欄位數 {len(parts)}")
            continue
        ids.append(class_id)
    return ids


def _analyze_yolo(reader, tree: VirtualTree, detection,
                  result: Dict[str, Any]) -> None:
    from app.services.dataset_detector import _find_split_dirs

    issues: List[Dict[str, Any]] = result["issues"]
    root = detection.root_prefix
    budget = TextBudget(MAX_DATASET_TEXT_MB * 1024 * 1024)

    # --- data.yaml（只用於交叉驗證） ---
    yaml_path = detection.extra.get("yaml_path")
    if yaml_path:
        parsed = _parse_data_yaml(reader, yaml_path, issues)
        result["declared_nc"] = parsed["nc"]
        result["declared_names"] = parsed["names"]
        if parsed["raw_text"] is not None:
            text = parsed["raw_text"]
            result["definition"] = {
                "kind": "yaml",
                "filename": parsed["filename"],
                "text": text[:DEFINITION_TEXT_CAP],
                "truncated": len(text) > DEFINITION_TEXT_CAP,
            }
    else:
        issues.append(_issue(
            "warning", "W_NO_DATA_YAML",
            "找不到 data.yaml，類別名稱將以標註檔中出現的 class id 代替",
        ))

    # --- 逐 split 掃描（目錄探索為準） ---
    split_dirs = _find_split_dirs(tree, root)
    grand_counts: Counter = Counter()
    malformed: List[str] = []
    hint_checked = hint_matched = hint_mismatched = 0
    hint_samples: List[str] = []
    label_files_read = 0
    max_class_id = -1

    for split_dir in split_dirs:
        images_dir = tree.join(split_dir, "images")
        labels_dir = tree.join(split_dir, "labels")

        image_files = tree.list_images(images_dir)
        label_files = tree.list_labels(labels_dir)
        image_stems = {posixpath.splitext(f)[0] for f in image_files}
        label_stems = {posixpath.splitext(f)[0] for f in label_files}

        split_counts: Counter = Counter()
        split_annotations = 0
        split_background = 0

        for label_name in label_files:
            if label_files_read >= MAX_DATASET_LABEL_FILES:
                result["truncated"] = True
                break
            member_path = tree.join(labels_dir, label_name)
            info = tree.member_by_path.get(member_path)
            if info is not None and not budget.try_spend(info.file_size):
                result["truncated"] = True
                break
            try:
                raw = reader.read(member_path)
            except ZipIndexError as exc:
                if len(malformed) < MAX_ISSUE_SAMPLES:
                    malformed.append(f"{member_path}: {exc}")
                continue
            label_files_read += 1

            ids = _scan_label_file(decode_text(raw), malformed, member_path)
            if not ids:
                split_background += 1
                continue

            split_counts.update(ids)
            split_annotations += len(ids)
            max_class_id = max(max_class_id, max(ids))

            # 檔名類別提示交叉檢查：用「包含」而非「等於」。一張影像可能
            # 同時含有多個類別，只要提示的類別確實出現就算通過。
            hint = CLASS_HINT_RE.search(label_name)
            if hint:
                hint_checked += 1
                expected = int(hint.group(1))
                if expected in ids:
                    hint_matched += 1
                else:
                    hint_mismatched += 1
                    if len(hint_samples) < MAX_ISSUE_SAMPLES:
                        hint_samples.append(f"{label_name} 期望 {expected}，實際 {sorted(set(ids))}")

        images_without_label = len(image_stems - label_stems)
        labels_without_image = len(label_stems - image_stems)

        result["splits"].append({
            "name": posixpath.basename(split_dir) or split_dir,
            "images": len(image_files),
            "labels": len(label_files),
            "annotations": split_annotations,
            "background_images": split_background,
            "images_without_label": images_without_label,
            "labels_without_image": labels_without_image,
            "annotations_per_image": round(split_annotations / len(image_files), 2) if image_files else 0.0,
            "class_counts": {str(k): v for k, v in sorted(split_counts.items())},
        })

        grand_counts.update(split_counts)
        result["total_images"] += len(image_files)
        result["total_annotations"] += split_annotations
        result["total_label_files"] += len(label_files)
        result["background_images"] += split_background

        if images_without_label:
            issues.append(_issue(
                "warning", "W_MISSING_LABEL_FILE",
                f"{posixpath.basename(split_dir)}: 有 {images_without_label} 張影像沒有對應標註檔",
            ))
        if labels_without_image:
            issues.append(_issue(
                "warning", "W_ORPHAN_LABEL_FILE",
                f"{posixpath.basename(split_dir)}: 有 {labels_without_image} 個標註檔沒有對應影像",
            ))

    result["max_class_id_found"] = max_class_id if max_class_id >= 0 else None

    # --- 類別彙整 ---
    names = result["declared_names"] or []
    class_id_universe = sorted(set(grand_counts) | set(range(len(names))))
    total = result["total_annotations"] or 1
    for class_id in class_id_universe:
        count = grand_counts.get(class_id, 0)
        result["classes"].append({
            "id": class_id,
            "name": names[class_id] if 0 <= class_id < len(names) else f"class_{class_id}",
            "name_zh": None,
            "count": count,
            "pct": round(100.0 * count / total, 2),
            "per_split": {
                s["name"]: s["class_counts"].get(str(class_id), 0) for s in result["splits"]
            },
        })

    # --- 交叉驗證 ---
    declared_nc = result["declared_nc"]
    if declared_nc is not None and max_class_id >= declared_nc:
        issues.append(_issue(
            "error", "E_CLASS_ID_OUT_OF_RANGE",
            f"標註檔出現超出宣告範圍的 class id：最大為 {max_class_id}，但 data.yaml 宣告 nc={declared_nc}",
            "此為多來源資料集合併後最典型的 ID 錯位徵兆，會導致訓練時類別對應錯誤",
        ))
    if declared_nc is not None and names and len(names) != declared_nc:
        issues.append(_issue(
            "error", "E_NC_NAMES_MISMATCH",
            f"data.yaml 的 nc={declared_nc} 與 names 長度 {len(names)} 不一致",
        ))
    if malformed:
        issues.append(_issue(
            "error", "E_MALFORMED_LABEL_LINE",
            f"有 {len(malformed)} 筆（取樣）標註行格式不正確",
            samples=malformed,
        ))

    # 空標註檔是刻意保留的負樣本（背景影像），用於降低模型假陽性，並非資料損壞
    if result["background_images"]:
        issues.append(_issue(
            "info", "I_BACKGROUND_IMAGES",
            f"有 {result['background_images']} 張影像為空標註（負樣本／背景影像）",
            "空標註檔通常是刻意保留用於降低假陽性的健康樣本，並非資料缺漏",
        ))
    zero_classes = [c["name"] for c in result["classes"] if c["count"] == 0]
    if zero_classes:
        issues.append(_issue(
            "info", "I_CLASS_ZERO_INSTANCES",
            f"有 {len(zero_classes)} 個宣告的類別沒有任何標註實例",
            "若這些類別僅作為負樣本對照則屬正常",
            samples=zero_classes[:MAX_ISSUE_SAMPLES],
        ))

    if hint_checked:
        result["prefix_check"] = {
            "status": "mismatch" if hint_mismatched else "ok",
            "checked": hint_checked,
            "matched": hint_matched,
            "mismatched": hint_mismatched,
            "samples": hint_samples,
        }
        if hint_mismatched:
            issues.append(_issue(
                "warning", "W_PREFIX_CLASS_MISMATCH",
                f"有 {hint_mismatched} 個檔名帶有類別提示，但標註內容不含該類別",
                "檔名形如 *_cls3_* 代表預期類別 3；不符可能代表重新命名與 ID 重寫沒有對齊",
                samples=hint_samples,
            ))

    if result["truncated"]:
        issues.append(_issue(
            "warning", "W_TRUNCATED",
            "資料集過大，僅分析了部分標註檔，統計為近似值",
        ))


# --------------------------------------------------------------------------- #
# COCO / VOC（基本解析，未經真實資料驗證）
# --------------------------------------------------------------------------- #

def _analyze_coco(reader, tree: VirtualTree, detection,
                  result: Dict[str, Any]) -> None:
    issues: List[Dict[str, Any]] = result["issues"]
    json_path = detection.extra.get("json_path")

    try:
        raw = reader.read(json_path, JSON_MEMBER_CAP_BYTES)
    except ZipIndexError as exc:
        result["truncated"] = True
        issues.append(_issue("warning", "W_TRUNCATED", "COCO 標註檔過大或無法讀取，改以檔案清單估算", str(exc)))
        result["total_images"] = len(tree.list_images(detection.root_prefix))
        return

    text = decode_text(raw)
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ZipIndexError(f"COCO 標註檔 JSON 格式錯誤: {exc}") from exc

    images = data.get("images") or []
    annotations = data.get("annotations") or []
    categories = data.get("categories") or []

    result["total_images"] = len(images)
    result["total_annotations"] = len(annotations)
    result["total_label_files"] = 1
    result["definition"] = {
        "kind": "json",
        "filename": posixpath.basename(json_path),
        "text": text[:DEFINITION_TEXT_CAP],
        "truncated": len(text) > DEFINITION_TEXT_CAP,
    }

    name_by_id = {c.get("id"): str(c.get("name", c.get("id"))) for c in categories if isinstance(c, dict)}
    result["declared_nc"] = len(categories) or None
    result["declared_names"] = [name_by_id[k] for k in sorted(name_by_id)] if name_by_id else None

    counts = Counter(a.get("category_id") for a in annotations if isinstance(a, dict))
    total = result["total_annotations"] or 1
    ids_seen = [cid for cid in counts if cid is not None]
    result["max_class_id_found"] = max(ids_seen) if ids_seen else None

    for category_id in sorted(set(name_by_id) | set(ids_seen), key=lambda x: (x is None, x)):
        if category_id is None:
            continue
        count = counts.get(category_id, 0)
        result["classes"].append({
            "id": category_id,
            "name": name_by_id.get(category_id, f"category_{category_id}"),
            "name_zh": None,
            "count": count,
            "pct": round(100.0 * count / total, 2),
            "per_split": {},
        })

    images_with_ann = {a.get("image_id") for a in annotations if isinstance(a, dict)}
    result["background_images"] = max(0, len(images) - len(images_with_ann))
    result["splits"].append({
        "name": posixpath.basename(json_path.rsplit("/", 1)[0]) or "all",
        "images": result["total_images"],
        "labels": 1,
        "annotations": result["total_annotations"],
        "background_images": result["background_images"],
        "images_without_label": result["background_images"],
        "labels_without_image": 0,
        "annotations_per_image": round(result["total_annotations"] / len(images), 2) if images else 0.0,
        "class_counts": {str(k): v for k, v in counts.items() if k is not None},
    })


def _analyze_voc(reader, tree: VirtualTree, detection,
                 result: Dict[str, Any]) -> None:
    issues: List[Dict[str, Any]] = result["issues"]
    ann_dir = detection.extra.get("annotations_dir")
    budget = TextBudget(MAX_DATASET_TEXT_MB * 1024 * 1024)

    xml_files = sorted(f for f in tree.files_in(ann_dir) if f.lower().endswith(".xml"))
    counts: Counter = Counter()
    total_annotations = 0
    parsed_files = 0
    rejected: List[str] = []
    background = 0

    for xml_name in xml_files:
        if parsed_files >= MAX_DATASET_XML_FILES:
            result["truncated"] = True
            break
        member_path = tree.join(ann_dir, xml_name)
        info = tree.member_by_path.get(member_path)
        if info is not None and not budget.try_spend(info.file_size):
            result["truncated"] = True
            break
        try:
            raw = reader.read(member_path)
        except ZipIndexError:
            continue

        # expat 對 entity expansion（billion laughs / quadratic blowup）沒有防護，
        # 且環境無 defusedxml。合法的 VOC 標註不會有 DOCTYPE，直接拒絕。
        head = raw[:4096].decode("ascii", errors="ignore").casefold()
        if "<!doctype" in head or "<!entity" in head:
            if len(rejected) < MAX_ISSUE_SAMPLES:
                rejected.append(xml_name)
            continue

        try:
            root_el = ET.fromstring(decode_text(raw))
        except ET.ParseError:
            continue
        parsed_files += 1

        objects = root_el.findall("object")
        if not objects:
            background += 1
        for obj in objects:
            name_el = obj.find("name")
            label = (name_el.text or "").strip() if name_el is not None else ""
            if label:
                counts[label] += 1
                total_annotations += 1

    if rejected:
        issues.append(_issue(
            "error", "E_XML_DOCTYPE_REJECTED",
            f"有 {len(rejected)} 個 XML 含 DOCTYPE/ENTITY 宣告，基於安全考量已略過",
            "XML 外部實體展開可能造成資源耗盡攻擊，合法的 VOC 標註不需要 DOCTYPE",
            samples=rejected,
        ))

    image_dir_candidates = [
        tree.join(detection.root_prefix, name)
        for name in ("JPEGImages", "images")
        if name in tree.subdirs_in(detection.root_prefix)
    ]
    total_images = sum(len(tree.list_images(d)) for d in image_dir_candidates) or parsed_files

    result["total_images"] = total_images
    result["total_annotations"] = total_annotations
    result["total_label_files"] = parsed_files
    result["background_images"] = background
    result["declared_nc"] = len(counts) or None
    result["declared_names"] = sorted(counts) or None

    total = total_annotations or 1
    for index, label in enumerate(sorted(counts)):
        result["classes"].append({
            "id": index,
            "name": label,
            "name_zh": None,
            "count": counts[label],
            "pct": round(100.0 * counts[label] / total, 2),
            "per_split": {},
        })

    result["splits"].append({
        "name": posixpath.basename(detection.root_prefix) or "all",
        "images": total_images,
        "labels": parsed_files,
        "annotations": total_annotations,
        "background_images": background,
        "images_without_label": max(0, total_images - parsed_files),
        "labels_without_image": 0,
        "annotations_per_image": round(total_annotations / total_images, 2) if total_images else 0.0,
        "class_counts": {str(i): counts[label] for i, label in enumerate(sorted(counts))},
    })

    if result["truncated"]:
        issues.append(_issue("warning", "W_TRUNCATED", "XML 標註檔數量過多，僅分析了部分檔案"))


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #

def analyze_dataset(reader, zip_name: str,
                    zip_size_bytes: Optional[int] = None) -> Dict[str, Any]:
    """分析資料集 ZIP，回傳統計 dict。失敗時拋出 ZipIndexError。"""
    started = time.monotonic()
    result = _base_result(zip_name)

    tree = reader.build_tree()
    if not tree.member_by_path:
        raise ZipIndexError("ZIP 內沒有任何可分析的檔案")

    detection = detect_format(reader, tree)

    result["format"] = detection.format
    result["root_prefix"] = detection.root_prefix + "/" if detection.root_prefix else ""
    result["detected_candidates"] = detected_candidates(reader, tree)
    result["member_count"] = len(tree.member_by_path)
    result["uncompressed_size_mb"] = round(tree.total_uncompressed / 1024 / 1024, 2)
    result["zip_size_mb"] = round(zip_size_bytes / 1024 / 1024, 2) if zip_size_bytes else 0.0

    if detection.format == "yolo":
        result["analysis_depth"] = "deep"
        result["verified"] = True
        _analyze_yolo(reader, tree, detection, result)
    elif detection.format == "coco":
        result["unverified_note"] = UNVERIFIED_NOTE
        _analyze_coco(reader, tree, detection, result)
    else:
        result["unverified_note"] = UNVERIFIED_NOTE
        _analyze_voc(reader, tree, detection, result)

    result["analysis_ms"] = int((time.monotonic() - started) * 1000)
    return result
