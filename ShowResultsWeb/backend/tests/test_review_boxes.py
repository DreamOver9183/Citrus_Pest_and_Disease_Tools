"""
逐張檢視的標註解析與配對規則。

這些規則決定畫面上每個框的顏色。配錯不會有任何錯誤訊息，只會讓使用者對著一張
「看起來合理」的圖做出錯誤判斷，所以每一條都用最小案例鎖住。
"""
import pytest

from app.services.review_boxes import annotate, iou, match, parse_yolo_labels

BOX = [10.0, 10.0, 50.0, 50.0]
FAR = [200.0, 200.0, 240.0, 240.0]


def _gt(cls, box=BOX):
    return {"cls": cls, "box": list(box)}


def _pred(cls, conf, box=BOX):
    return {"cls": cls, "conf": conf, "box": list(box)}


def _status(entries):
    return [e["status"] for e in entries]


# --- 標註解析 -----------------------------------------------------------------

def test_parse_converts_normalized_center_format_to_pixel_corners():
    boxes, skipped = parse_yolo_labels("0 0.5 0.5 0.2 0.4\n", width=100, height=50)
    assert boxes == [{"cls": 0, "box": [40.0, 15.0, 60.0, 35.0]}]
    assert sum(skipped.values()) == 0


def test_parse_clamps_boxes_that_spill_past_the_image_edge():
    boxes, _ = parse_yolo_labels("1 0.95 0.5 0.2 0.2", width=100, height=100)
    assert boxes[0]["box"] == [85.0, 40.0, 100.0, 60.0]


def test_parse_skips_polygon_and_malformed_lines_without_failing_the_image():
    text = "\n".join([
        "0 0.1 0.1 0.2 0.1 0.2 0.2",  # 多邊形
        "abc 0.5 0.5 0.2 0.2",        # 非數字
        "0 0.5 0.5",                  # 欄數不足
        "0 0.5 0.5 0 0.2",            # 面積為 0
        "0 0.5 0.5 0.2 0.2",
    ])
    boxes, skipped = parse_yolo_labels(text, width=100, height=100)
    assert len(boxes) == 1
    assert skipped == {"polygon": 1, "malformed": 3, "class_out_of_range": 0}


def test_parse_skips_class_ids_outside_the_vocabulary():
    boxes, skipped = parse_yolo_labels("5 0.5 0.5 0.2 0.2\n-1 0.5 0.5 0.2 0.2", 100, 100, nc=2)
    assert boxes == []
    assert skipped["class_out_of_range"] == 2


def test_empty_label_file_is_a_negative_sample():
    assert parse_yolo_labels("", 100, 100) == ([], {"polygon": 0, "malformed": 0, "class_out_of_range": 0})


# --- IoU ----------------------------------------------------------------------

def test_iou_of_disjoint_and_identical_boxes():
    assert iou(BOX, FAR) == 0.0
    assert iou(BOX, BOX) == 1.0


# --- 配對 ---------------------------------------------------------------------

def test_matching_box_of_the_same_class_is_a_true_positive():
    result = match([_gt(0)], [_pred(0, 0.9)], conf=0.25)
    assert result["counts"] == {"tp": 1, "fp": 0, "wrong": 0, "fn": 0}
    assert result["preds"][0]["pair"] == 0 and result["gt"][0]["pair"] == 0


def test_any_prediction_on_a_negative_sample_is_a_false_positive():
    result = match([], [_pred(0, 0.9)], conf=0.25)
    assert result["counts"] == {"tp": 0, "fp": 1, "wrong": 0, "fn": 0}


def test_unmatched_ground_truth_is_a_miss():
    result = match([_gt(0)], [], conf=0.25)
    assert result["counts"] == {"tp": 0, "fp": 0, "wrong": 0, "fn": 1}


def test_overlapping_box_of_another_class_is_a_wrong_class_not_a_miss_plus_false_positive():
    result = match([_gt(0)], [_pred(1, 0.9)], conf=0.25)
    assert result["counts"] == {"tp": 0, "fp": 0, "wrong": 1, "fn": 0}
    assert _status(result["gt"]) == ["wrong"]
    assert result["gt"][0]["pair"] == 0, "類別錯的標註要記下配對，前端才能畫出對應的虛線框"


def test_one_ground_truth_is_matched_at_most_once():
    result = match([_gt(0)], [_pred(0, 0.6), _pred(0, 0.9)], conf=0.25)
    assert result["counts"] == {"tp": 1, "fp": 1, "wrong": 0, "fn": 0}
    by_id = {p["id"]: p["status"] for p in result["preds"]}
    assert by_id == {1: "tp", 0: "fp"}, "信心較高的預測先配對"


def test_correct_class_wins_over_a_more_confident_wrong_class():
    """
    兩段式配對的理由：一次掃完的話，高信心的錯類預測會先搶走標註，
    正確類別的預測反而被判成誤報。
    """
    result = match([_gt(0)], [_pred(1, 0.9), _pred(0, 0.5)], conf=0.25)
    by_id = {p["id"]: p["status"] for p in result["preds"]}
    assert by_id == {1: "tp", 0: "fp"}
    assert result["counts"] == {"tp": 1, "fp": 1, "wrong": 0, "fn": 0}


def test_result_does_not_depend_on_prediction_order():
    a = match([_gt(0), _gt(1, FAR)], [_pred(1, 0.8), _pred(0, 0.8, FAR)], conf=0.25)
    b = match([_gt(0), _gt(1, FAR)], [_pred(0, 0.8, FAR), _pred(1, 0.8)], conf=0.25)
    assert a["counts"] == b["counts"] == {"tp": 0, "fp": 0, "wrong": 2, "fn": 0}


def test_confidence_threshold_filters_before_matching():
    result = match([_gt(0)], [_pred(0, 0.2)], conf=0.25)
    assert result["preds"] == []
    assert result["counts"]["fn"] == 1


@pytest.mark.parametrize("box, expected", [
    ([10.0, 10.0, 50.0, 30.0], "tp"),   # IoU 恰為 0.5，含等號
    ([10.0, 10.0, 50.0, 29.0], "fp"),   # IoU 0.475
])
def test_iou_threshold_boundary(box, expected):
    result = match([_gt(0)], [_pred(0, 0.9, box)], conf=0.25)
    assert _status(result["preds"]) == [expected]


# --- 類別篩選 -----------------------------------------------------------------

def test_class_filter_keeps_only_boxes_of_selected_classes():
    out = annotate([_gt(0), _gt(1, FAR)], [], conf=0.25, classes=[0])
    assert [g["cls"] for g in out["gt"]] == [0]
    assert out["counts"]["fn"] == 1
    assert out["involved"] is True


def test_class_filter_keeps_a_wrong_class_pair_when_either_side_is_selected():
    """只看介殼蟲(1)時，被錯判成介殼蟲的蚜蟲(0)標註必須跟著留下，否則錯判會退化成誤報。"""
    out = annotate([_gt(0)], [_pred(1, 0.9)], conf=0.25, classes=[1])
    assert out["counts"] == {"tp": 0, "fp": 0, "wrong": 1, "fn": 0}
    assert len(out["gt"]) == 1 and out["gt"][0]["cls"] == 0


def test_image_without_selected_classes_is_not_involved():
    out = annotate([_gt(0)], [_pred(0, 0.9)], conf=0.25, classes=[3])
    assert out["involved"] is False
    assert out["errors"] == 0
