"""
逐張檢視的純函式：YOLO 標註解析、IoU、標註框與預測框的配對。

**這是視覺化，不是評估指標。** 配對結果只用來替每個框上色、替每張圖計數，不得彙總成
mAP / Precision / Recall——工具包刻意不自行實作指標（architecture §7），那些數字一律
出自 model.val()。IoU 門檻固定 0.5，與 val() 混淆矩陣的 0.45 不同，也是另一個理由。

全部無 I/O、不依賴 ultralytics，讓配對規則能被 pytest 逐條鎖住。

框的形狀：
- 標註 `{"cls": int, "box": [x1, y1, x2, y2]}`（像素，已轉正方向）
- 預測 `{"cls": int, "conf": float, "box": [x1, y1, x2, y2]}`
"""
import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

IOU_THRESHOLD = 0.5


# --------------------------------------------------------------------------- #
# 標註解析
# --------------------------------------------------------------------------- #

def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def parse_yolo_labels(
    text: str, width: int, height: int, nc: Optional[int] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    YOLO 標註（每行 `cls cx cy w h`，正規化）→ 像素角點。

    壞行一律略過並計數，**不讓整張失敗**：
    - 超過 5 欄：多邊形（分割）格式，框偵測用不上
    - 欄數不足、非數字、非有限值、面積為 0：malformed
    - 類別 id 為負或超出詞彙表：class_out_of_range
    角點夾取到影像範圍內。空字串（空 label 檔）是合法的負樣本。
    """
    boxes: List[Dict[str, Any]] = []
    skipped = {"polygon": 0, "malformed": 0, "class_out_of_range": 0}

    for raw in text.splitlines():
        parts = raw.split()
        if not parts:
            continue
        if len(parts) > 5:
            skipped["polygon"] += 1
            continue
        if len(parts) < 5:
            skipped["malformed"] += 1
            continue
        try:
            cls_value = float(parts[0])
            cx, cy, w, h = (float(p) for p in parts[1:])
        except ValueError:
            skipped["malformed"] += 1
            continue
        if not all(math.isfinite(v) for v in (cls_value, cx, cy, w, h)) or cls_value != int(cls_value):
            skipped["malformed"] += 1
            continue

        cls = int(cls_value)
        if cls < 0 or (nc is not None and cls >= nc):
            skipped["class_out_of_range"] += 1
            continue

        x1 = _clamp01(cx - w / 2) * width
        y1 = _clamp01(cy - h / 2) * height
        x2 = _clamp01(cx + w / 2) * width
        y2 = _clamp01(cy + h / 2) * height
        if x2 <= x1 or y2 <= y1:
            skipped["malformed"] += 1
            continue

        boxes.append({"cls": cls, "box": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)]})

    return boxes, skipped


# --------------------------------------------------------------------------- #
# 配對
# --------------------------------------------------------------------------- #

def iou(a: List[float], b: List[float]) -> float:
    inter_w = min(a[2], b[2]) - max(a[0], b[0])
    inter_h = min(a[3], b[3]) - max(a[1], b[1])
    if inter_w <= 0 or inter_h <= 0:
        return 0.0
    inter = inter_w * inter_h
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _counts(gt_entries: Iterable[Dict], pred_entries: Iterable[Dict]) -> Dict[str, int]:
    preds = list(pred_entries)
    return {
        "tp": sum(1 for p in preds if p["status"] == "tp"),
        "fp": sum(1 for p in preds if p["status"] == "fp"),
        "wrong": sum(1 for p in preds if p["status"] == "wrong"),
        "fn": sum(1 for g in gt_entries if g["status"] == "fn"),
    }


def match(
    gt: List[Dict[str, Any]],
    preds: List[Dict[str, Any]],
    conf: float,
    iou_thr: float = IOU_THRESHOLD,
) -> Dict[str, Any]:
    """
    把門檻以上的預測配對到標註。**兩段式**，讓結果不依預測的輸入順序而變：

    1. 預測依信心降冪，各自找「同類別、尚未配對、IoU 最大且 ≥ 門檻」的標註 → tp
    2. 第 1 段沒配到的預測，對「剩下未配對的**其他類別**標註」找 IoU 最大且 ≥ 門檻 → wrong
       （該標註被佔用，不再算 fn）
    3. 其餘預測 → fp；沒被配到的標註 → fn

    分兩段是為了讓「低信心但類別正確」的預測優先於「高信心但類別錯」的預測：
    若一次掃完，高信心的錯類預測會先把標註搶走，正確的那個反而被判成誤報。

    每個標註最多配一次。回傳的 `id` 是原清單索引，`pair` 是另一側的原清單索引。
    門檻以下的預測不出現在結果裡。
    """
    active = sorted(
        (j for j, p in enumerate(preds) if p["conf"] >= conf),
        key=lambda j: (-preds[j]["conf"], j),
    )
    gt_pair: Dict[int, int] = {}
    gt_status = {i: "fn" for i in range(len(gt))}
    pred_status: Dict[int, str] = {}
    pred_pair: Dict[int, int] = {}
    pred_iou: Dict[int, float] = {}

    def best_gt(j: int, same_class: bool) -> Tuple[Optional[int], float]:
        chosen, chosen_iou = None, 0.0
        for i, g in enumerate(gt):
            if i in gt_pair or (g["cls"] == preds[j]["cls"]) != same_class:
                continue
            value = iou(g["box"], preds[j]["box"])
            if value >= iou_thr and (chosen is None or value > chosen_iou):
                chosen, chosen_iou = i, value
        return chosen, chosen_iou

    for same_class, status in ((True, "tp"), (False, "wrong")):
        for j in active:
            if j in pred_status:
                continue
            i, value = best_gt(j, same_class)
            if i is None:
                continue
            gt_pair[i], gt_status[i] = j, status
            pred_pair[j], pred_status[j], pred_iou[j] = i, status, value

    for j in active:
        pred_status.setdefault(j, "fp")

    gt_entries = [
        {"id": i, "status": gt_status[i], "pair": gt_pair.get(i)} for i in range(len(gt))
    ]
    pred_entries = [
        {
            "id": j,
            "status": pred_status[j],
            "pair": pred_pair.get(j),
            "iou": round(pred_iou[j], 4) if j in pred_iou else None,
        }
        for j in active
    ]
    return {"gt": gt_entries, "preds": pred_entries, "counts": _counts(gt_entries, pred_entries)}


def annotate(
    gt: List[Dict[str, Any]],
    preds: List[Dict[str, Any]],
    conf: float,
    classes: Optional[Iterable[int]] = None,
    iou_thr: float = IOU_THRESHOLD,
) -> Dict[str, Any]:
    """
    配對後合併框的內容，並依類別篩選。

    配對**先對所有類別做完**才篩選——否則只看介殼蟲時，一個被錯判成介殼蟲的蚜蟲標註會
    因為「不是介殼蟲」被丟掉，錯判預測就退化成誤報。類別錯的一對只要任一端命中就整對保留。

    `involved` 表示這張圖在篩選下是否有任何框（沒有選類別時永遠為 True）。
    """
    result = match(gt, preds, conf, iou_thr)
    selected = set(classes) if classes else None

    def keep(entry: Dict, own: List[Dict], other: List[Dict]) -> bool:
        if selected is None or own[entry["id"]]["cls"] in selected:
            return True
        return entry["status"] == "wrong" and other[entry["pair"]]["cls"] in selected

    gt_out = [{**gt[g["id"]], **g} for g in result["gt"] if keep(g, gt, preds)]
    pred_out = [{**preds[p["id"]], **p} for p in result["preds"] if keep(p, preds, gt)]
    counts = _counts(gt_out, pred_out)
    return {
        "gt": gt_out,
        "preds": pred_out,
        "counts": counts,
        "errors": counts["fp"] + counts["fn"] + counts["wrong"],
        "involved": selected is None or bool(gt_out or pred_out),
    }
