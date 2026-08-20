"""
評估服務的測試。

`_run_validation` 與 `peek_model_names` 是刻意留出的接縫，全部測試都 monkeypatch 它們
——真實評估需要真實的 checkpoint 與影像，兩者都被 .gitignore 排除（與 export_service
的測試策略一致）。

本檔最高價值的一組是類別詞彙比對：不一致時算出的每一個數字都是垃圾，而且**不會有
任何錯誤訊息**，ultralytics 只會照索引配對。沒有這組測試，那個 bug 會完全無聲無息。
"""
import os
import time

import pytest
import yaml

from app.services import evaluation_service as ev


@pytest.fixture(autouse=True)
def clean_jobs(tmp_path, monkeypatch):
    ev.EVAL_JOBS.clear()
    monkeypatch.setattr(ev, "EVAL_DIR", tmp_path / "evaluations")
    yield
    ev.EVAL_JOBS.clear()


# --- 類別詞彙比對 -------------------------------------------------------------

def test_identical_vocabularies_match():
    result = ev.compare_vocabularies({0: "Aphid", 1: "Canker"}, ["Aphid", "Canker"])
    assert result["status"] == "match"
    assert result["differences"] == []
    assert result["message"] is None


def test_different_class_counts_are_a_hard_mismatch():
    """
    類別數不同必須是硬性拒絕。

    這不是假想風險：model_service 的 SSD 類別表寫死 12 類、num_classes=13，而實際的
    v5 資料集是 8 類。若放行，ultralytics 會照索引配對出一組看起來合理但完全錯誤的
    指標，而且不會拋任何例外。
    """
    result = ev.compare_vocabularies({i: f"c{i}" for i in range(12)}, ["a", "b", "c"])
    assert result["status"] == "mismatch"
    assert result["model_nc"] == 12
    assert result["dataset_nc"] == 3
    assert "12" in result["message"] and "3" in result["message"]


def test_same_count_different_names_is_a_warning_not_a_failure():
    """數量相同、名稱不同時仍可算（索引配對），但必須警告使用者確認語意。"""
    result = ev.compare_vocabularies({0: "Aphid", 1: "Canker"}, ["蚜蟲", "Canker"])
    assert result["status"] == "name_drift"
    assert result["differences"] == [{"index": 0, "model": "Aphid", "dataset": "蚜蟲"}]
    assert "名稱不一致" in result["message"]


def test_vocabulary_order_follows_class_index_not_dict_order():
    """model.names 是 dict，迭代順序不保證；必須依索引排序才對得上標註的 class id。"""
    result = ev.compare_vocabularies({2: "c", 0: "a", 1: "b"}, ["a", "b", "c"])
    assert result["status"] == "match"
    assert result["model_names"] == ["a", "b", "c"]


# --- 標註尺寸剖面 -------------------------------------------------------------

def _write_labels(labels_dir, rows_by_file):
    labels_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in rows_by_file.items():
        (labels_dir / name).write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_box_size_profile_computes_median_area(tmp_path):
    labels = tmp_path / "labels"
    # class 0 的框面積：0.5*0.5=0.25、0.1*0.1=0.01、0.3*0.3=0.09 → 中位 0.09 → 9%
    _write_labels(labels, {
        "a.txt": ["0 .5 .5 .5 .5"],
        "b.txt": ["0 .5 .5 .1 .1"],
        "c.txt": ["0 .5 .5 .3 .3"],
    })
    profile = ev.box_size_profile(str(labels), ["Aphid", "Canker"])

    aphid = profile[0]
    assert aphid["boxes"] == 3
    assert aphid["median_area_pct"] == pytest.approx(9.0, abs=0.01)
    assert aphid["max_area_pct"] == pytest.approx(25.0, abs=0.01)


def test_box_size_profile_flags_tiny_boxes(tmp_path):
    """
    極小框佔比是「為什麼需要 P2 層」的量化依據。

    實測這個專案的資料集：Canker 有 31.5% 的框面積低於整張影像的 0.1%，
    而 Sooty_Mold 一個都沒有。
    """
    labels = tmp_path / "labels"
    _write_labels(labels, {
        "a.txt": ["0 .5 .5 .01 .01"],   # 面積 0.0001 → 極小
        "b.txt": ["0 .5 .5 .02 .02"],   # 面積 0.0004 → 極小
        "c.txt": ["0 .5 .5 .5 .5"],     # 面積 0.25   → 不是
        "d.txt": ["0 .5 .5 .4 .4"],
    })
    profile = ev.box_size_profile(str(labels), ["Aphid"])
    assert profile[0]["tiny_pct"] == pytest.approx(50.0)


def test_box_size_profile_reports_classes_with_no_boxes(tmp_path):
    """宣告了但測試集內沒有樣本的類別必須出現在剖面裡，否則表格會少一列。"""
    labels = tmp_path / "labels"
    _write_labels(labels, {"a.txt": ["0 .5 .5 .2 .2"]})
    profile = ev.box_size_profile(str(labels), ["Aphid", "Canker"])

    assert len(profile) == 2
    assert profile[1]["name"] == "Canker"
    assert profile[1]["boxes"] == 0
    assert profile[1]["median_area_pct"] is None


def test_box_size_profile_survives_malformed_lines(tmp_path):
    """標註檔可能有空行或殘缺行，不能讓整場評估掛掉。"""
    labels = tmp_path / "labels"
    _write_labels(labels, {"a.txt": ["0 .5 .5 .2 .2", "", "garbage", "0 .1"]})
    profile = ev.box_size_profile(str(labels), ["Aphid"])
    assert profile[0]["boxes"] == 1


def test_box_size_profile_ignores_classes_txt(tmp_path):
    labels = tmp_path / "labels"
    _write_labels(labels, {"a.txt": ["0 .5 .5 .2 .2"]})
    (labels / "classes.txt").write_text("Aphid\nCanker\n", encoding="utf-8")
    assert ev.box_size_profile(str(labels), ["Aphid"])[0]["boxes"] == 1


def test_box_size_profile_handles_missing_directory():
    assert ev.box_size_profile("/definitely/not/here", ["Aphid"])[0]["boxes"] == 0


# --- data.yaml 合成 -----------------------------------------------------------

def test_write_data_yaml_points_at_the_real_split(tmp_path):
    """
    合成的 data.yaml 必須完全從磁碟結構反推。

    刻意不重用資料集自帶的 data.yaml：實測那份的 path: 指向訓練當時他機的絕對路徑
    （f:\\115柑橘病蟲害專題\\...），沿用會讓 val() 掃到 0 張影像且極難追查。
    """
    images = tmp_path / "work" / "test" / "images"
    images.mkdir(parents=True)
    dest = ev.write_data_yaml(str(images), ["Aphid", "Canker"], tmp_path / "data.yaml")

    content = yaml.safe_load(dest.read_text(encoding="utf-8"))
    assert content["path"] == str(tmp_path / "work").replace("\\", "/")
    assert content["val"] == "test/images"
    assert content["names"] == {0: "Aphid", 1: "Canker"}
    assert "115" not in str(content), "不得混入資料集自帶 yaml 的他機路徑"


# --- job 生命週期 -------------------------------------------------------------

def _session(sid="run_x", arch="yolo"):
    return {"session_id": sid, "custom_name": "測試模型", "model_arch": arch,
            "weights_path": "/fake/best.pt"}


def _dataset(tmp_path, did="ds_x"):
    root = tmp_path / "mydata"
    for split in ("test",):
        (root / split / "images").mkdir(parents=True, exist_ok=True)
        (root / split / "labels").mkdir(parents=True, exist_ok=True)
        (root / split / "images" / "a.jpg").write_bytes(b"\xff\xd8\xff")
        (root / split / "labels" / "a.txt").write_text("0 .5 .5 .2 .2\n", encoding="utf-8")
    return {
        "dataset_id": did, "zip_name": "mydata", "format": "yolo",
        "source_container": str(root), "source_inner_prefix": "",
        "splits": [{"name": "test"}], "declared_names": ["Aphid", "Canker"],
    }


def _wait_for(job_id, states=("done", "failed"), timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = ev.get_job(job_id)
        if job and job["state"] in states:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} 未在 {timeout}s 內完成")


def _fake_validation(**overrides):
    result = {
        "model_names": {0: "Aphid", 1: "Canker"},
        "overall": {"map50": 0.8, "map50_95": 0.6, "precision": 0.75, "recall": 0.7},
        "per_class": [
            {"class_id": 0, "name": "Aphid", "precision": .8, "recall": .7, "ap50": .85, "ap50_95": .6},
            {"class_id": 1, "name": "Canker", "precision": .5, "recall": .3, "ap50": .32, "ap50_95": .2},
        ],
        "speed_ms": {"inference": 42.0},
        "plots": {},
    }
    result.update(overrides)
    return result


def test_successful_run_produces_metrics_and_size_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "peek_model_names", lambda w: {0: "Aphid", 1: "Canker"})
    monkeypatch.setattr(ev, "_run_validation", lambda *a, **k: _fake_validation())

    job = ev.submit_evaluation(_session(), _dataset(tmp_path), "test")
    done = _wait_for(job["job_id"])

    assert done["state"] == "done"
    assert done["overall"]["map50"] == 0.8
    assert done["image_count"] == 1
    assert done["vocab_check"]["status"] == "match"
    assert len(done["per_class"]) == 2
    assert len(done["size_profile"]) == 2, "尺寸剖面必須涵蓋每一個類別"
    assert done["elapsed_seconds"] is not None


def test_vocabulary_mismatch_fails_before_running_validation(tmp_path, monkeypatch):
    """
    最重要的一條：詞彙對不上時**不能**跑完整場評估再說。

    讓使用者等 60 秒才得知類別對不上是最糟的順序，而且更糟的是若不檢查就會產出
    一組看起來合理的錯誤數字。
    """
    called = []
    monkeypatch.setattr(ev, "peek_model_names", lambda w: {i: f"c{i}" for i in range(12)})
    monkeypatch.setattr(ev, "_run_validation",
                        lambda *a, **k: called.append(1) or _fake_validation())

    job = ev.submit_evaluation(_session(), _dataset(tmp_path), "test")
    failed = _wait_for(job["job_id"])

    assert failed["state"] == "failed"
    assert called == [], "詞彙不一致時絕不能進入 validation 階段"
    assert failed["vocab_check"]["status"] == "mismatch"
    assert "12" in failed["message"]


def test_name_drift_still_completes_but_carries_the_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "peek_model_names", lambda w: {0: "蚜蟲", 1: "Canker"})
    monkeypatch.setattr(ev, "_run_validation", lambda *a, **k: _fake_validation())

    job = ev.submit_evaluation(_session(), _dataset(tmp_path), "test")
    done = _wait_for(job["job_id"])

    assert done["state"] == "done"
    assert done["vocab_check"]["status"] == "name_drift"
    assert done["message"] is not None


def test_unavailable_dataset_fails_with_the_explanation(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "peek_model_names", lambda w: {0: "Aphid", 1: "Canker"})
    dataset = _dataset(tmp_path)
    dataset["source_container"] = None          # 模擬上傳 ZIP

    job = ev.submit_evaluation(_session(), dataset, "test")
    failed = _wait_for(job["job_id"])

    assert failed["state"] == "failed"
    assert "上傳" in failed["message"]


def test_validation_error_is_surfaced_not_swallowed(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr(ev, "peek_model_names", lambda w: {0: "Aphid", 1: "Canker"})
    monkeypatch.setattr(ev, "_run_validation", boom)

    job = ev.submit_evaluation(_session(), _dataset(tmp_path), "test")
    failed = _wait_for(job["job_id"])

    assert failed["state"] == "failed"
    assert "CUDA out of memory" in failed["message"]


def test_extracted_split_is_cleaned_up_after_the_run(tmp_path, monkeypatch):
    """ZIP 解出來的 split 只為該次評估存在，留著只會佔磁碟。"""
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("test/images/a.jpg", b"\xff\xd8\xff")
        zf.writestr("test/labels/a.txt", "0 .5 .5 .2 .2\n")
    zip_path = tmp_path / "ds.zip"
    zip_path.write_bytes(buf.getvalue())

    dataset = _dataset(tmp_path)
    dataset["source_container"] = str(zip_path)
    dataset["source_inner_prefix"] = ""

    monkeypatch.setattr(ev, "peek_model_names", lambda w: {0: "Aphid", 1: "Canker"})
    monkeypatch.setattr(ev, "_run_validation", lambda *a, **k: _fake_validation())

    job = ev.submit_evaluation(_session(), dataset, "test")
    done = _wait_for(job["job_id"])

    assert done["state"] == "done"
    job_dir = tmp_path / "evaluations" / job["job_id"]
    assert not (job_dir / "data").exists(), "解壓出來的 split 應該在收尾時清掉"


def test_elapsed_uses_monotonic_clock(tmp_path, monkeypatch):
    """
    回歸測試：混用 time.time() 與 time.monotonic() 曾直接產出「29785752 分 60 秒」。
    """
    monkeypatch.setattr(ev, "peek_model_names", lambda w: {0: "Aphid", 1: "Canker"})
    monkeypatch.setattr(ev, "_run_validation", lambda *a, **k: _fake_validation())

    job = ev.submit_evaluation(_session(), _dataset(tmp_path), "test")
    done = _wait_for(job["job_id"])
    assert 0 <= done["elapsed_seconds"] < 300


def test_job_deletion_removes_the_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "peek_model_names", lambda w: {0: "Aphid", 1: "Canker"})
    monkeypatch.setattr(ev, "_run_validation", lambda *a, **k: _fake_validation())

    job = ev.submit_evaluation(_session(), _dataset(tmp_path), "test")
    _wait_for(job["job_id"])
    job_dir = tmp_path / "evaluations" / job["job_id"]
    assert job_dir.exists()

    assert ev.delete_job(job["job_id"]) is True
    assert not job_dir.exists()
    assert ev.get_job(job["job_id"]) is None
    assert ev.delete_job(job["job_id"]) is False


def test_plot_path_rejects_paths_outside_the_job_dir(tmp_path, monkeypatch):
    """路徑包含檢查：圖表端點不能被誘導去讀 job 目錄以外的檔案。"""
    monkeypatch.setattr(ev, "peek_model_names", lambda w: {0: "Aphid", 1: "Canker"})
    outsider = tmp_path / "secret.png"
    outsider.write_bytes(b"\x89PNG")
    monkeypatch.setattr(
        ev, "_run_validation",
        lambda *a, **k: _fake_validation(plots={"confusion_matrix": str(outsider)}),
    )

    job = ev.submit_evaluation(_session(), _dataset(tmp_path), "test")
    _wait_for(job["job_id"])

    assert ev.plot_path(job["job_id"], "confusion_matrix") is None


def test_completed_evaluations_survive_restart(tmp_path, monkeypatch):
    """
    評估結果必須跨重啟存活，即使來源 session 已消失。

    這是與 export_service 刻意不同的地方：本專案絕大多數 session 來自 LocalLibrary
    掃描、依設計不落地，若比照匯出去過濾「session 還在嗎」，等於每次重啟都把所有
    測量結果刪光——而一次評估要跑數分鐘。
    """
    monkeypatch.setattr(ev, "peek_model_names", lambda w: {0: "Aphid", 1: "Canker"})
    monkeypatch.setattr(ev, "_run_validation", lambda *a, **k: _fake_validation())

    job = ev.submit_evaluation(_session(), _dataset(tmp_path), "test")
    done = _wait_for(job["job_id"])
    assert done["state"] == "done"

    # 模擬重啟：記憶體清空，session 也不會被還原（LocalLibrary 不落地）
    ev.EVAL_JOBS.clear()
    ev.load_jobs_from_disk()

    restored = ev.get_job(job["job_id"])
    assert restored is not None, "已完成的評估結果不該因為 session 消失而被刪除"
    assert restored["overall"]["map50"] == 0.8
    assert restored["per_class"], "逐類別結果必須一併還原"


def test_unfinished_evaluations_are_purged_on_restart(tmp_path, monkeypatch):
    """相對地，沒跑完的 job 沒有價值——重啟後不會有 worker 接手，必須清掉。"""
    eval_dir = tmp_path / "evaluations"
    stale = eval_dir / "eval_stale"
    stale.mkdir(parents=True)
    (stale / "manifest.json").write_text(
        '{"schema_version": 1, "state": "running", "job_id": "eval_stale"}', encoding="utf-8"
    )

    ev.load_jobs_from_disk()

    assert ev.get_job("eval_stale") is None
    assert not stale.exists()
