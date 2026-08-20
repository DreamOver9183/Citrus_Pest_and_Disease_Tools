"""
資料集格式偵測。

只看虛擬樹的檔名結構（COCO/VOC 需要有限的內容 peek 才能確認），不解壓縮。

設計要點：對樹中**每一個目錄**評分，而不是只看根目錄。這讓巢狀包裝目錄
（例如 ZIP 內是 Datasets_YOLO26_v5/train/... 而非 train/...）自動被處理，
不需要特別的「往下鑽一層」邏輯。
"""
import posixpath
import zipfile
from typing import Dict, List, NamedTuple, Optional

from app.utils.dataset_zip import VirtualTree, peek_json_object
from app.utils.zip_handler import ZipIndexError

YOLO_YAML_NAMES = {"data.yaml", "data.yml", "dataset.yaml", "dataset.yml"}
SPLIT_DIR_NAMES = {"train", "valid", "val", "test", "training", "validation"}

# 分數越高優先度越高。YOLO(100) 必須高於 COCO(80)：Roboflow 匯出常同時含
# data.yaml 與 _annotations.coco.json，而本專案要求 YOLO 走深度分析路徑。
SCORE_YOLO_WITH_YAML = 100
SCORE_COCO = 80
SCORE_VOC_STRUCTURED = 70
SCORE_YOLO_NO_YAML = 60
SCORE_VOC_LOOSE = 50


class Detection(NamedTuple):
    format: str            # "yolo" | "coco" | "voc"
    root_prefix: str       # 資料集根目錄（含結尾斜線；根層為 ""）
    score: int
    evidence: str
    extra: Dict            # 各格式的附加線索（yaml 檔名、coco json 路徑等）


def _has_split_pair(tree: VirtualTree, dirpath: str) -> bool:
    """該目錄下是否同時存在 images/ 與 labels/ 子目錄。"""
    subs = tree.subdirs_in(dirpath)
    return "images" in subs and "labels" in subs


def _descendant_has_split_pair(tree: VirtualTree, dirpath: str) -> bool:
    """
    自身或任一後代目錄具備 images/+labels/ 配對。

    直接掃描全樹的 key 並比對前綴，避免遞迴；資料集目錄數量不大。
    """
    prefix = dirpath + "/" if dirpath else ""
    for candidate in tree.dirs:
        if candidate == dirpath or candidate.startswith(prefix):
            if _has_split_pair(tree, candidate):
                return True
    return False


def _find_split_dirs(tree: VirtualTree, root: str) -> List[str]:
    """
    找出 root 底下所有的 split 目錄（同時有 images/ 與 labels/ 者）。

    目錄名即 split 名，不依賴 data.yaml 的宣告——這是計數正確性的關鍵：
    data.yaml 的 val: 指向的是 valid/ 目錄，且其相對路徑基底可能無法解析。
    """
    prefix = root + "/" if root else ""
    found = []
    for candidate in tree.dirs:
        if candidate != root and not candidate.startswith(prefix):
            continue
        if _has_split_pair(tree, candidate):
            found.append(candidate)
    return sorted(found)


def _looks_like_coco(zip_ref: zipfile.ZipFile, tree: VirtualTree, dirpath: str) -> Optional[str]:
    """回傳第一個看起來像 COCO 標註的 json 路徑。"""
    for filename in sorted(tree.files_in(dirpath)):
        if not filename.lower().endswith(".json"):
            continue
        path = tree.join(dirpath, filename)
        parsed = peek_json_object(zip_ref, path)
        if parsed is None:
            continue
        if isinstance(parsed.get("images"), list) and isinstance(parsed.get("annotations"), list):
            return path
    return None


def _voc_xml_dir(tree: VirtualTree, dirpath: str) -> Optional[str]:
    """VOC 標準結構：Annotations/ 內有 xml，且同層有 JPEGImages/ 或 ImageSets/。"""
    subs = tree.subdirs_in(dirpath)
    if "Annotations" not in subs:
        return None
    ann_dir = tree.join(dirpath, "Annotations")
    has_xml = any(f.lower().endswith(".xml") for f in tree.files_in(ann_dir))
    if not has_xml:
        return None
    if "JPEGImages" in subs or "ImageSets" in subs:
        return ann_dir
    return None


def detect_format(zip_ref: zipfile.ZipFile, tree: VirtualTree) -> Detection:
    """
    偵測資料集格式，回傳最高分的判定。

    平手時取最淺的目錄，再取字典序，確保結果具決定性。
    """
    candidates: List[Detection] = []

    for dirpath in tree.dirs:
        files_lower = {f.lower(): f for f in tree.files_in(dirpath)}

        # --- YOLO：有 data.yaml 且自身或後代具備 images/+labels/ ---
        yaml_name = next((files_lower[n] for n in YOLO_YAML_NAMES if n in files_lower), None)
        if yaml_name and _descendant_has_split_pair(tree, dirpath):
            candidates.append(Detection(
                "yolo", dirpath, SCORE_YOLO_WITH_YAML,
                f"找到 {yaml_name} 與 images/labels 目錄結構",
                {"yaml_path": tree.join(dirpath, yaml_name)},
            ))

        # --- COCO ---
        coco_path = _looks_like_coco(zip_ref, tree, dirpath)
        if coco_path:
            candidates.append(Detection(
                "coco", dirpath, SCORE_COCO,
                f"找到含 images/annotations 的 JSON：{posixpath.basename(coco_path)}",
                {"json_path": coco_path},
            ))

        # --- VOC（標準結構） ---
        ann_dir = _voc_xml_dir(tree, dirpath)
        if ann_dir:
            candidates.append(Detection(
                "voc", dirpath, SCORE_VOC_STRUCTURED,
                "找到 Annotations/*.xml 與 JPEGImages/ImageSets 結構",
                {"annotations_dir": ann_dir},
            ))

        # --- YOLO（無 yaml，但有 train/valid/test 且各含 images+labels） ---
        if not yaml_name:
            split_children = [s for s in tree.subdirs_in(dirpath) if s.lower() in SPLIT_DIR_NAMES]
            if any(_has_split_pair(tree, tree.join(dirpath, s)) for s in split_children):
                candidates.append(Detection(
                    "yolo", dirpath, SCORE_YOLO_NO_YAML,
                    "找到 train/valid/test 的 images+labels 結構（無 data.yaml）",
                    {"yaml_path": None},
                ))

        # --- VOC（寬鬆：任何含 xml 的目錄，內容確認留待解析階段） ---
        if any(f.lower().endswith(".xml") for f in tree.files_in(dirpath)):
            candidates.append(Detection(
                "voc", dirpath, SCORE_VOC_LOOSE,
                "找到 XML 標註檔",
                {"annotations_dir": dirpath},
            ))

    if not candidates:
        raise ZipIndexError("無法辨識資料集格式：找不到 YOLO / COCO / Pascal VOC 的結構特徵")

    def sort_key(d: Detection):
        depth = d.root_prefix.count("/") if d.root_prefix else 0
        return (-d.score, depth, d.root_prefix)

    candidates.sort(key=sort_key)
    return candidates[0]


def detected_candidates(zip_ref: zipfile.ZipFile, tree: VirtualTree) -> List[str]:
    """
    回傳所有被偵測到的格式（去重，依分數排序）。

    用於在 UI 顯示「同時偵測到 COCO」這類資訊，而不是把次要判定藏起來。
    """
    seen: Dict[str, int] = {}
    for dirpath in tree.dirs:
        files_lower = {f.lower() for f in tree.files_in(dirpath)}
        if any(n in files_lower for n in YOLO_YAML_NAMES) and _descendant_has_split_pair(tree, dirpath):
            seen["yolo"] = max(seen.get("yolo", 0), SCORE_YOLO_WITH_YAML)
        elif _find_split_dirs(tree, dirpath):
            seen["yolo"] = max(seen.get("yolo", 0), SCORE_YOLO_NO_YAML)
        if _looks_like_coco(zip_ref, tree, dirpath):
            seen["coco"] = max(seen.get("coco", 0), SCORE_COCO)
        if _voc_xml_dir(tree, dirpath):
            seen["voc"] = max(seen.get("voc", 0), SCORE_VOC_STRUCTURED)
    return [fmt for fmt, _ in sorted(seen.items(), key=lambda kv: -kv[1])]
