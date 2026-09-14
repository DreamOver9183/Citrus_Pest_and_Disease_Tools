"""
逐張檢視 job 的測試。

`_load_model` 與 `_predict_image` 是刻意留出的接縫（真實 checkpoint 被 .gitignore 排除）。
影像則**用 PIL 產生真的 JPEG**，而不是評估測試用的 3 位元組假檔——這裡要驗證的正是解碼、
EXIF 轉正與縮圖，假檔會讓那些路徑完全沒被執行到。
"""
import io
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.services import review_service as rs

# 100×80 影像上的 [10, 10, 50, 50]
LABEL_A = "0 0.3 0.375 0.4 0.5\n"
BOX_A = [10.0, 10.0, 50.0, 50.0]


@pytest.fixture(autouse=True)
def clean_jobs(tmp_path, monkeypatch):
    rs.REVIEW_JOBS.clear()
    rs._ITEMS_CACHE.clear()
    monkeypatch.setattr(rs, "REVIEW_DIR", tmp_path / "reviews")
    yield
    rs.REVIEW_JOBS.clear()
    rs._ITEMS_CACHE.clear()


def _jpeg_bytes(size=(100, 80), orientation=None):
    buf = io.BytesIO()
    kwargs = {}
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        kwargs["exif"] = exif
    Image.new("RGB", size, (120, 160, 90)).save(buf, "JPEG", **kwargs)
    return buf.getvalue()


def _dataset(tmp_path, files=None, folder="mydata"):
    """files: {檔名: (影像位元組, 標註文字或 None)}"""
    root = tmp_path / folder
    images = root / "test" / "images"
    labels = root / "test" / "labels"
    images.mkdir(parents=True)
    labels.mkdir(parents=True)
    files = files if files is not None else {"a.jpg": (_jpeg_bytes(), LABEL_A)}
    for name, (payload, label) in files.items():
        (images / name).write_bytes(payload)
        if label is not None:
            (labels / f"{Path(name).stem}.txt").write_text(label, encoding="utf-8")
    return {
        "dataset_id": "ds_x", "zip_name": folder, "format": "yolo",
        "source_container": str(root), "source_inner_prefix": "",
        "splits": [{"name": "test"}], "declared_names": ["Aphid", "Canker"],
    }


def _session(weights="/fake/best.pt"):
    return {"session_id": "run_x", "custom_name": "測試模型", "model_arch": "yolo",
            "weights_path": weights}


def _stub(monkeypatch, names=None, preds=None, delay=0.0):
    model = SimpleNamespace(names=names or {0: "Aphid", 1: "Canker"}, overrides={"imgsz": 640})
    monkeypatch.setattr(rs, "_load_model", lambda w: model)
    calls = []

    def fake_predict(m, image, imgsz):
        calls.append({"size": image.size, "imgsz": imgsz})
        if delay:
            time.sleep(delay)
        return [dict(p) for p in (preds if preds is not None else [{"cls": 0, "conf": 0.9, "box": BOX_A}])]

    monkeypatch.setattr(rs, "_predict_image", fake_predict)
    return calls


def _wait_for(job_id, states=("done", "failed"), timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = rs.get_job(job_id)
        if job and job["state"] in states:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} 未在 {timeout}s 內完成")


def _wait_idle(timeout=10):
    """state 先於收尾（刪目錄）改變；要檢查收尾結果就得等 worker 真的做完這個 job。"""
    deadline = time.monotonic() + timeout
    while rs._QUEUE.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.05)


def _wait_manifest(job_id, timeout=5):
    """state=done 先於 manifest 寫入。"""
    path = rs.REVIEW_DIR / job_id / "manifest.json"
    deadline = time.monotonic() + timeout
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    return path


# --- 基本流程 -----------------------------------------------------------------

def test_run_stores_boxes_and_answers_queries(tmp_path, monkeypatch):
    _stub(monkeypatch)
    dataset = _dataset(tmp_path, {
        "a.jpg": (_jpeg_bytes(), LABEL_A),
        "b.jpg": (_jpeg_bytes(), None),        # 沒有 label 檔：負樣本，其上的預測是誤報
    })
    job = rs.submit_review(_session(), dataset, "test", None)
    done = _wait_for(job["job_id"])

    assert done["state"] == "done", done["message"]
    assert done["image_count"] == 2 and done["processed"] == 2
    assert done["imgsz_used"] == 640, "未指定時回報模型預設尺寸"
    assert done["label_issues"]["missing"] == 1
    assert done["image_set_key"]

    result = rs.query_items(job["job_id"], conf=0.25)
    assert result["summary"]["tp"] == 1 and result["summary"]["fp"] == 1
    by_name = {item["name"]: item for item in result["items"]}
    assert by_name["a.jpg"]["gt"][0]["status"] == "tp"
    assert by_name["b.jpg"]["label_missing"] is True
    assert result["items"][0]["name"] == "b.jpg", "預設依錯誤數排序"

    assert rs.image_path(job["job_id"], 0, "thumb")
    assert rs.image_path(job["job_id"], 0, "full").endswith("a.jpg")


def test_threshold_is_applied_at_query_time_without_rerunning(tmp_path, monkeypatch):
    calls = _stub(monkeypatch, preds=[{"cls": 0, "conf": 0.3, "box": BOX_A}])
    job = rs.submit_review(_session(), _dataset(tmp_path), "test", None)
    _wait_for(job["job_id"])

    assert rs.query_items(job["job_id"], conf=0.25)["summary"]["tp"] == 1
    assert rs.query_items(job["job_id"], conf=0.5)["summary"]["fn"] == 1
    assert len(calls) == 1, "調門檻不得重新推論"


def test_requested_imgsz_reaches_every_prediction(tmp_path, monkeypatch):
    calls = _stub(monkeypatch)
    job = rs.submit_review(_session(), _dataset(tmp_path), "test", 320)
    done = _wait_for(job["job_id"])

    assert done["imgsz_used"] == 320
    assert [c["imgsz"] for c in calls] == [320]


def test_exif_rotated_image_is_measured_after_transpose(tmp_path, monkeypatch):
    """
    EXIF Orientation=6 的 100×80 影像，瀏覽器會顯示成 80×100。寬高與餵給模型的影像都必須
    是轉正後的，否則標註換算與疊框位置會整個錯開。
    """
    calls = _stub(monkeypatch, preds=[])
    dataset = _dataset(tmp_path, {"r.jpg": (_jpeg_bytes((100, 80), orientation=6), None)})
    job = rs.submit_review(_session(), dataset, "test", None)
    _wait_for(job["job_id"])

    item = rs.query_items(job["job_id"], conf=0.25)["items"][0]
    assert (item["width"], item["height"]) == (80, 100)
    assert calls[0]["size"] == (80, 100)


def test_chinese_folder_names_are_read(tmp_path, monkeypatch):
    _stub(monkeypatch)
    job = rs.submit_review(_session(), _dataset(tmp_path, folder="柑橘資料集"), "test", None)
    done = _wait_for(job["job_id"])
    assert done["state"] == "done", done["message"]
    assert done["image_count"] == 1


def test_unreadable_image_is_skipped_not_fatal(tmp_path, monkeypatch):
    _stub(monkeypatch)
    dataset = _dataset(tmp_path, {
        "a.jpg": (_jpeg_bytes(), LABEL_A),
        "broken.jpg": (b"\xff\xd8\xff", None),
    })
    job = rs.submit_review(_session(), dataset, "test", None)
    done = _wait_for(job["job_id"])

    assert done["state"] == "done"
    assert done["unreadable"] == ["broken.jpg"]
    assert rs.query_items(job["job_id"], conf=0.25)["total"] == 1


def test_polygon_label_lines_are_counted(tmp_path, monkeypatch):
    _stub(monkeypatch)
    label = LABEL_A + "1 0.1 0.1 0.2 0.1 0.2 0.2\n"
    job = rs.submit_review(_session(), _dataset(tmp_path, {"a.jpg": (_jpeg_bytes(), label)}), "test", None)
    done = _wait_for(job["job_id"])
    assert done["label_issues"]["polygon"] == 1


# --- 失敗與前置檢查 -----------------------------------------------------------

def test_vocabulary_mismatch_fails_before_predicting(tmp_path, monkeypatch):
    calls = _stub(monkeypatch, names={i: f"c{i}" for i in range(12)})
    job = rs.submit_review(_session(), _dataset(tmp_path), "test", None)
    failed = _wait_for(job["job_id"])

    assert failed["state"] == "failed"
    assert calls == [], "詞彙不一致時絕不能開始逐張推論"
    _wait_idle()
    assert not (rs.REVIEW_DIR / job["job_id"]).exists(), "失敗的 job 不留檔案"


def test_tflite_requested_size_must_match_the_exported_input(tmp_path, monkeypatch):
    _stub(monkeypatch)
    monkeypatch.setattr(rs, "_fixed_input_size", lambda w: 320)
    job = rs.submit_review(_session("/fake/model.tflite"), _dataset(tmp_path), "test", 640)
    failed = _wait_for(job["job_id"])

    assert failed["state"] == "failed"
    assert "320" in failed["message"]


def test_tflite_uses_its_fixed_size_when_none_is_requested(tmp_path, monkeypatch):
    calls = _stub(monkeypatch)
    monkeypatch.setattr(rs, "_fixed_input_size", lambda w: 320)
    job = rs.submit_review(_session("/fake/model.tflite"), _dataset(tmp_path), "test", None)
    done = _wait_for(job["job_id"])

    assert done["imgsz_used"] == 320 and done["weight_format"] == "tflite"
    assert calls[0]["imgsz"] == 320


def test_session_gate(monkeypatch):
    assert rs.session_review_gate(_session())[0] is True
    assert rs.session_review_gate({**_session(), "model_arch": "ssdlite_mobilenet_v3_large"})[0] is False
    assert "ONNX" in rs.session_review_gate(_session("/fake/model.onnx"))[1]

    monkeypatch.setattr(rs.export_capabilities, "_find_spec", lambda name: False)
    available, reason = rs.session_review_gate(_session("/fake/model.tflite"))
    assert available is False and "Docker" in reason


# --- 保存與生命週期 -----------------------------------------------------------

def test_zip_source_keeps_images_for_viewing(tmp_path, monkeypatch):
    _stub(monkeypatch)
    zip_path = tmp_path / "ds.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("test/images/a.jpg", _jpeg_bytes())
        zf.writestr("test/labels/a.txt", LABEL_A)
    dataset = _dataset(tmp_path)
    dataset["source_container"] = str(zip_path)

    job = rs.submit_review(_session(), dataset, "test", None)
    done = _wait_for(job["job_id"])

    assert done["state"] == "done", done["message"]
    full = rs.image_path(job["job_id"], 0, "full")
    assert full and Path(full).is_file(), "ZIP 來源的影像要留著，否則完成後就看不到原圖"
    assert not (rs.REVIEW_DIR / job["job_id"] / "data" / "test" / "labels").exists()


def test_deleting_a_running_job_stops_it(tmp_path, monkeypatch):
    calls = _stub(monkeypatch, delay=0.2)
    files = {f"{i}.jpg": (_jpeg_bytes(), LABEL_A) for i in range(6)}
    job = rs.submit_review(_session(), _dataset(tmp_path, files), "test", None)
    job_id = job["job_id"]

    deadline = time.monotonic() + 10
    while (rs.get_job(job_id) or {}).get("processed", 0) < 1 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert rs.delete_job(job_id)

    _wait_idle()
    assert len(calls) < 6, "刪除後應在下一張之前停下"
    assert not (rs.REVIEW_DIR / job_id).exists()


def test_done_jobs_survive_restart(tmp_path, monkeypatch):
    _stub(monkeypatch)
    job = rs.submit_review(_session(), _dataset(tmp_path), "test", None)
    _wait_for(job["job_id"])
    assert _wait_manifest(job["job_id"]).exists()

    rs.REVIEW_JOBS.clear()
    rs._ITEMS_CACHE.clear()
    rs.load_jobs_from_disk()

    restored = rs.get_job(job["job_id"])
    assert restored and restored["state"] == "done"
    assert rs.query_items(job["job_id"], conf=0.25)["summary"]["tp"] == 1
    assert rs.image_path(job["job_id"], 0, "full")


def test_image_path_rejects_indexes_outside_the_job(tmp_path, monkeypatch):
    _stub(monkeypatch)
    job = rs.submit_review(_session(), _dataset(tmp_path), "test", None)
    _wait_for(job["job_id"])
    assert rs.image_path(job["job_id"], 5, "full") is None
    assert rs.image_path(job["job_id"], -1, "thumb") is None


def test_status_filter_and_class_filter(tmp_path, monkeypatch):
    # a.jpg：類別 0 被正確抓到；c.jpg：類別 1 的標註沒被抓到
    _stub(monkeypatch)
    dataset = _dataset(tmp_path, {
        "a.jpg": (_jpeg_bytes(), LABEL_A),
        "c.jpg": (_jpeg_bytes(), "1 0.8 0.8 0.2 0.2\n" + LABEL_A),
    })
    job = rs.submit_review(_session(), dataset, "test", None)
    _wait_for(job["job_id"])

    missed = rs.query_items(job["job_id"], conf=0.25, status="fn")
    assert [i["name"] for i in missed["items"]] == ["c.jpg"]
    assert missed["summary"]["with_fn"] == 1 and missed["summary"]["images"] == 2

    only_class_1 = rs.query_items(job["job_id"], conf=0.25, classes=[1])
    assert [i["name"] for i in only_class_1["items"]] == ["c.jpg"]
    assert all(box["cls"] == 1 for box in only_class_1["items"][0]["gt"])
