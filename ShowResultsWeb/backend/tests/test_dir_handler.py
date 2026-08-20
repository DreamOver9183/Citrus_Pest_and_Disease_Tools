"""
目錄模型索引的測試。

重點在兩件事：
1. index_yolo_runs_in_dir() 與 ZIP 路徑的判定行為一致（同一份邏輯，兩個入口）
2. index_single_weight_in_place() 真的不動使用者的檔案
"""
import os

from app.utils.dir_handler import index_single_weight_in_place, index_yolo_runs_in_dir

ARGS_YAML = "epochs: 150\noptimizer: MuSGD\nmodel: yolo26n.pt\n"
RESULTS_CSV = "epoch,metrics/mAP50(B),metrics/precision(B)\n1,0.5,0.6\n150,0.803,0.828\n"


def _make_run(base, name="run_a", with_extras=True):
    run_dir = base / name
    (run_dir / "weights").mkdir(parents=True)
    (run_dir / "weights" / "best.pt").write_bytes(b"weights")
    (run_dir / "args.yaml").write_text(ARGS_YAML, encoding="utf-8")
    if with_extras:
        (run_dir / "results.csv").write_text(RESULTS_CSV, encoding="utf-8")
        (run_dir / "results.png").write_bytes(b"png")
        (run_dir / "confusion_matrix.png").write_bytes(b"png")
    return run_dir


# --- index_yolo_runs_in_dir --------------------------------------------------

def test_finds_valid_run_with_full_metadata(tmp_path):
    _make_run(tmp_path)
    runs = index_yolo_runs_in_dir(str(tmp_path))

    assert len(runs) == 1
    run = runs[0]
    assert run["weights_path"].endswith("run_a/weights/best.pt")
    assert run["epochs"] == 150
    assert run["optimizer"] == "MuSGD"
    assert run["model_cfg"] == "yolo26n.pt"
    # results.csv 取最後一行，且 header 的 metrics/ 與 (B) 都要被清掉
    assert run["metrics_summary"]["mAP50"] == "0.803"
    assert run["metrics_summary"]["precision"] == "0.828"
    assert run["results_png"] is not None
    assert run["confusion_matrix"] is not None


def test_finds_runs_at_arbitrary_depth(tmp_path):
    """真實訓練包常是 detect/<name>/ 這種巢狀結構。"""
    nested = tmp_path / "detect" / "deep"
    nested.mkdir(parents=True)
    _make_run(nested, "run_x")
    runs = index_yolo_runs_in_dir(str(tmp_path))
    assert len(runs) == 1
    assert "run_x" in runs[0]["dir_path"]


def test_finds_multiple_runs(tmp_path):
    _make_run(tmp_path, "run_a")
    _make_run(tmp_path, "run_b")
    assert len(index_yolo_runs_in_dir(str(tmp_path))) == 2


def test_ignores_dir_without_args_yaml(tmp_path):
    run_dir = tmp_path / "incomplete"
    (run_dir / "weights").mkdir(parents=True)
    (run_dir / "weights" / "best.pt").write_bytes(b"weights")
    assert index_yolo_runs_in_dir(str(tmp_path)) == []


def test_ignores_dir_without_best_pt(tmp_path):
    run_dir = tmp_path / "incomplete"
    (run_dir / "weights").mkdir(parents=True)
    (run_dir / "weights" / "last.pt").write_bytes(b"weights")
    (run_dir / "args.yaml").write_text(ARGS_YAML, encoding="utf-8")
    assert index_yolo_runs_in_dir(str(tmp_path)) == []


def test_missing_optional_artifacts_become_none(tmp_path):
    _make_run(tmp_path, "bare", with_extras=False)
    run = index_yolo_runs_in_dir(str(tmp_path))[0]
    assert run["results_png"] is None
    assert run["confusion_matrix"] is None
    assert run["metrics_summary"] == {}


def test_empty_dir_returns_empty_list(tmp_path):
    assert index_yolo_runs_in_dir(str(tmp_path)) == []


# --- index_single_weight_in_place -------------------------------------------

def test_in_place_does_not_copy_the_file(tmp_path):
    """最關鍵的一點：使用者的檔案不能被複製到別處。"""
    weight = tmp_path / "best.pt"
    weight.write_bytes(b"x" * 2048)
    before = {p.name for p in tmp_path.rglob("*")}

    info = index_single_weight_in_place(str(weight))

    after = {p.name for p in tmp_path.rglob("*")}
    assert before == after, "不應產生任何新檔案"
    assert os.path.abspath(info["weights_path"].replace("/", os.sep)) == str(weight)
    assert info["dir_path"].endswith(tmp_path.name)


def test_in_place_does_not_rename_pth(tmp_path):
    """
    index_single_weight()（複製版）會把 .pth 改名成 .pt；就地版本絕不能這樣做，
    因為那是使用者的檔案。
    """
    weight = tmp_path / "best_model.pth"
    weight.write_bytes(b"ssd-weights")

    info = index_single_weight_in_place(str(weight))

    assert info["weights_path"].endswith(".pth")
    assert weight.exists(), "原始 .pth 必須原封不動"
    assert not (tmp_path / "best_model.pt").exists(), "不應產生改名後的副本"


def test_in_place_returns_same_keys_as_copying_variant(tmp_path):
    """兩個版本的輸出形狀必須一致，才能共用下游註冊邏輯。"""
    from app.utils.zip_handler import index_single_weight

    src = tmp_path / "src" / "best.pt"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"weights")
    dest = tmp_path / "dest"
    dest.mkdir()

    copied = index_single_weight(str(src), str(dest))
    in_place = index_single_weight_in_place(str(src))

    assert set(copied.keys()) == set(in_place.keys())
