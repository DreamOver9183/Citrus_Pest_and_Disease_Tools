"""Micro-Accuracy（Jaccard index）與其相關指標的計算測試。

公式依《效能指標定義與評測方法》§2（物件偵測 TN=0 簡化版）：

    Precision = TP / (TP + FP)
    Recall    = TP / (TP + FN)
    F1        = 2·P·R / (P + R)
    Accuracy  = TP / (TP + FP + FN) = 1 / (1/P + 1/R − 1)

這支測試餵的是**手算過答案的合成混淆矩陣**，所以不需要真實權重與影像（兩者都被
.gitignore 排除，CI 上根本不存在）。這正是把計算抽成純函式的理由。

矩陣慣例（ultralytics）：`matrix[預測類別][真實類別]`，最後一列／行是 background。
"""
import pytest

from app.services.evaluation_service import (
    CM_CONF_THRESHOLD,
    CM_IOU_THRESHOLD,
    accuracy_from_precision_recall,
    micro_accuracy_from_matrix,
)


# --- 基本情境 ---------------------------------------------------------------

def test_perfect_predictions_give_accuracy_one():
    # 兩個類別全部命中，沒有任何 background 誤判
    result = micro_accuracy_from_matrix([[5, 0, 0], [0, 3, 0], [0, 0, 0]])
    assert result["micro_accuracy"] == 1.0
    assert (result["tp"], result["fp"], result["fn"]) == (8, 0, 0)
    assert result["micro_precision"] == 1.0
    assert result["micro_recall"] == 1.0
    assert result["micro_f1"] == 1.0


def test_all_predictions_wrong_gives_accuracy_zero():
    # 類別完全對調：每個框同時是 FP 與 FN，一個 TP 都沒有
    result = micro_accuracy_from_matrix([[0, 5, 0], [3, 0, 0], [0, 0, 0]])
    assert result["micro_accuracy"] == 0.0
    assert result["tp"] == 0
    assert result["fp"] == 8
    assert result["fn"] == 8


def test_empty_matrix_returns_none_not_zero():
    """沒有任何預測也沒有任何標註時回 None。

    「沒有東西可算」與「算出來是零」是兩件不同的事。回 0.0 會在權重登錄簿裡留下一筆
    看起來像「這顆模型爛透了」的假紀錄。
    """
    result = micro_accuracy_from_matrix([[0, 0, 0], [0, 0, 0], [0, 0, 0]])
    assert result["micro_accuracy"] is None
    assert result["micro_precision"] is None
    assert result["micro_recall"] is None


def test_mixed_matrix_matches_hand_computed_values():
    """手算對照。

        matrix = [[4, 1, 2],
                  [0, 3, 1],
                  [1, 2, 0]]      # 最後一列／行是 background

        類別 0：TP=4，FP=(4+1+2)−4=3，FN=(4+0+1)−4=1
        類別 1：TP=3，FP=(0+3+1)−3=1，FN=(1+3+2)−3=3
        合計   ：TP=7，FP=4，FN=4  →  7/15 = 0.4667
    """
    result = micro_accuracy_from_matrix([[4, 1, 2], [0, 3, 1], [1, 2, 0]])
    assert (result["tp"], result["fp"], result["fn"]) == (7, 4, 4)
    assert result["micro_accuracy"] == pytest.approx(7 / 15, abs=1e-4)
    assert result["micro_precision"] == pytest.approx(7 / 11, abs=1e-4)
    assert result["micro_recall"] == pytest.approx(7 / 11, abs=1e-4)

    by_id = {c["class_id"]: c for c in result["per_class"]}
    assert (by_id[0]["tp"], by_id[0]["fp"], by_id[0]["fn"]) == (4, 3, 1)
    assert by_id[0]["accuracy"] == pytest.approx(4 / 8, abs=1e-4)
    assert (by_id[1]["tp"], by_id[1]["fp"], by_id[1]["fn"]) == (3, 1, 3)
    assert by_id[1]["accuracy"] == pytest.approx(3 / 7, abs=1e-4)


def test_background_row_and_column_are_counted_correctly():
    """漏檢（background 列）記 FN、多餘預測（background 行）記 FP，但兩者都不是類別。"""
    # 類別 0：命中 6；漏掉 2（落在 background 列）；多預測 3（落在 background 行）
    result = micro_accuracy_from_matrix([[6, 0, 3], [0, 0, 0], [2, 0, 0]])
    assert (result["tp"], result["fp"], result["fn"]) == (6, 3, 2)
    assert result["micro_accuracy"] == pytest.approx(6 / 11, abs=1e-4)
    # background 本身不該被當成一個類別列出
    assert [c["class_id"] for c in result["per_class"]] == [0, 1]


def test_class_names_are_attached_when_provided():
    result = micro_accuracy_from_matrix(
        [[3, 0, 0], [0, 2, 0], [0, 0, 0]], class_names=["Canker", "Aphid"]
    )
    assert [c["name"] for c in result["per_class"]] == ["Canker", "Aphid"]


def test_thresholds_are_always_reported():
    """門檻必須跟著指標一起回傳——沒有門檻的 Jaccard 無法解讀，也無法跨紀錄比較。"""
    for matrix in ([[1, 0], [0, 0]], None, [[0, 0], [0, 0]]):
        result = micro_accuracy_from_matrix(matrix)
        assert result["conf_threshold"] == CM_CONF_THRESHOLD
        assert result["iou_threshold"] == CM_IOU_THRESHOLD


# --- 降級路徑 ---------------------------------------------------------------

@pytest.mark.parametrize("bad", [None, [], "not-a-matrix", [[1, 2], [3]], [["a", "b"], ["c", "d"]]])
def test_malformed_input_degrades_instead_of_raising(bad):
    """取不到混淆矩陣（換一個 ultralytics 版本就可能發生）時要降級，不能讓整場評估失敗。"""
    result = micro_accuracy_from_matrix(bad)
    assert result["micro_accuracy"] is None
    assert result["per_class"] == []


def test_explicit_nc_limits_the_real_classes():
    """指定 nc 時只算前 nc 個類別，其餘視為 background 之類的非類別列。"""
    matrix = [[4, 0, 0], [0, 5, 0], [0, 0, 9]]
    assert micro_accuracy_from_matrix(matrix, nc=1)["tp"] == 4
    assert micro_accuracy_from_matrix(matrix, nc=2)["tp"] == 9


# --- 兩條公式路徑必須一致 ---------------------------------------------------

@pytest.mark.parametrize("matrix", [
    [[4, 1, 2], [0, 3, 1], [1, 2, 0]],
    [[6, 0, 3], [0, 0, 0], [2, 0, 0]],
    [[10, 2, 1], [3, 7, 4], [2, 1, 0]],
    [[1, 0, 0], [0, 1, 0], [0, 0, 0]],
])
def test_accuracy_identity_holds(matrix):
    """驗證規格文件的恆等式：TP/(TP+FP+FN) == 1/(1/P + 1/R − 1)。

    兩條路徑一致是這組實作正確的最強證據——它們用的是完全不同的算式，卻必須給出
    同一個數字。任何一邊寫錯（例如 FP/FN 的行列取反）都會讓這個測試立刻失敗。
    """
    result = micro_accuracy_from_matrix(matrix)
    derived = accuracy_from_precision_recall(
        result["micro_precision"], result["micro_recall"]
    )
    assert derived == pytest.approx(result["micro_accuracy"], abs=1e-4)


@pytest.mark.parametrize("precision,recall", [(0, 0.5), (0.5, 0), (None, 0.5), (0.5, None)])
def test_accuracy_from_precision_recall_is_undefined_at_zero(precision, recall):
    assert accuracy_from_precision_recall(precision, recall) is None


def test_accuracy_is_never_greater_than_precision_or_recall():
    """Jaccard 的分母恆大於等於 P 與 R 的分母，因此它必定是三者中最小的。"""
    result = micro_accuracy_from_matrix([[10, 2, 1], [3, 7, 4], [2, 1, 0]])
    assert result["micro_accuracy"] <= result["micro_precision"]
    assert result["micro_accuracy"] <= result["micro_recall"]
