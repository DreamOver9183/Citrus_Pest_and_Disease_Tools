"""權重登錄簿服務層測試。

跑在 tmp_path 底下的 SQLite，因此 CI 零設定即可執行。Docker 上的 PostgreSQL 走的是
同一份程式碼（差別只在 `DATABASE_URL`），CI 另有一輪把 `DATABASE_URL` 指向 Postgres
service container 的執行，證明雙軌都成立。

這裡守的三件事，每一件都是實際會被打破的：

1. **身分是 SHA-256 而不是 session_id** —— 重掃／重新上傳同一顆權重不得產生第二列。
2. **完整超參數要進得去** —— 系統原本只留 epochs/optimizer/model 三個鍵。
3. **資料庫不可用時所有寫入都是 no-op，且不拋例外** —— 這是「附加層」的定義。
"""
import pytest

from app.db import engine as db_engine
from app.services import registry_service


@pytest.fixture
def registry_db(tmp_path):
    url = "sqlite:///" + str(tmp_path / "registry.db").replace("\\", "/")
    assert db_engine.reset_for_tests(url)
    yield
    db_engine.dispose()


@pytest.fixture
def weight_file(tmp_path):
    path = tmp_path / "best.pt"
    path.write_bytes(b"fake-weights-content")
    return str(path).replace("\\", "/")


def _session(weights_path, **overrides):
    base = {
        "session_id": "run_abc12345",
        "weights_path": weights_path,
        "custom_name": "v5 - 150 epochs",
        "model_arch": "yolo",
        "format_label": "PyTorch",
        "source_type": "zip",
        "weights_size_mb": 5.24,
        "metrics_summary": {
            "mAP50": "0.803", "mAP50-95": "0.612",
            "precision": "0.85", "recall": "0.78",
        },
    }
    base.update(overrides)
    return base


ARGS_YAML = {
    "epochs": 150, "optimizer": "auto", "imgsz": 640, "batch": 16,
    "lr0": 0.01, "lrf": 0.01, "momentum": 0.937, "weight_decay": 0.0005,
    "patience": 100, "seed": 0, "model": "yolo11n.pt",
    "mosaic": 1.0, "fliplr": 0.5, "hsv_h": 0.015,
}


# --- 身分與冪等 -------------------------------------------------------------

def test_sha256_is_content_addressed(tmp_path, weight_file):
    same = tmp_path / "copy_under_another_name.pt"
    same.write_bytes(b"fake-weights-content")
    different = tmp_path / "other.pt"
    different.write_bytes(b"different-content")

    assert registry_service.sha256_of_file(weight_file) == registry_service.sha256_of_file(str(same))
    assert registry_service.sha256_of_file(weight_file) != registry_service.sha256_of_file(str(different))


def test_missing_file_hashes_to_none_without_raising():
    assert registry_service.sha256_of_file("nope/does-not-exist.pt") is None
    assert registry_service.sha256_of_file("") is None


def test_recording_the_same_weight_twice_updates_instead_of_duplicating(registry_db, weight_file):
    """重掃 LocalLibrary 是常態操作。每次都新增一列，帳本一週後就沒法看了。"""
    sha_a = registry_service.record_weight(_session(weight_file), ARGS_YAML)
    first = registry_service.query_weights()["weights"][0]

    sha_b = registry_service.record_weight(
        _session(weight_file, session_id="run_zzz99999", custom_name="改過的名字"), ARGS_YAML
    )

    assert sha_a == sha_b
    result = registry_service.query_weights()
    assert result["total"] == 1
    updated = result["weights"][0]
    assert updated["display_name"] == "改過的名字"
    assert updated["first_seen_at"] == first["first_seen_at"], "首見時間不該被覆寫"
    assert updated["last_seen_at"] >= first["last_seen_at"]


def test_different_weights_are_separate_rows(registry_db, tmp_path, weight_file):
    other = tmp_path / "other.pt"
    other.write_bytes(b"another-model-entirely")
    registry_service.record_weight(_session(weight_file), ARGS_YAML)
    registry_service.record_weight(_session(str(other), session_id="run_b"), ARGS_YAML)
    assert registry_service.query_weights()["total"] == 2


# --- 超參數與訓練指標 -------------------------------------------------------

def test_full_hyperparameters_are_stored(registry_db, weight_file):
    """完整 args.yaml 要進得去，不是只有 epochs/optimizer/model 三個鍵。"""
    registry_service.record_weight(_session(weight_file), ARGS_YAML)
    run = registry_service.query_weights()["weights"][0]["training_run"]

    assert run["hyperparameters"] == ARGS_YAML
    # 提升為欄位的子集必須與 JSON 內容一致
    assert run["epochs"] == 150
    assert run["optimizer"] == "auto"
    assert run["imgsz"] == 640
    assert run["batch"] == 16
    assert run["lr0"] == pytest.approx(0.01)
    assert run["momentum"] == pytest.approx(0.937)
    assert run["model_cfg"] == "yolo11n.pt"
    # 沒有被提升為欄位的鍵仍然查得到
    assert run["hyperparameters"]["mosaic"] == 1.0


def test_training_metrics_are_parsed_from_results_csv(registry_db, weight_file):
    registry_service.record_weight(_session(weight_file), ARGS_YAML)
    run = registry_service.query_weights()["weights"][0]["training_run"]
    assert run["map50"] == pytest.approx(0.803)
    assert run["map50_95"] == pytest.approx(0.612)
    assert run["precision"] == pytest.approx(0.85)
    assert run["recall"] == pytest.approx(0.78)


def test_weight_without_training_data_has_no_training_run(registry_db, weight_file):
    """散落的權重檔沒有 args.yaml 也沒有 results.csv——不該憑空生出一列空的訓練紀錄。"""
    registry_service.record_weight(
        _session(weight_file, source_type="single_weight", metrics_summary={}), None
    )
    assert registry_service.query_weights()["weights"][0]["training_run"] is None


# --- 評估紀錄 ---------------------------------------------------------------

def _job(job_id="eval_abc", **overrides):
    job = {
        "job_id": job_id,
        "dataset_name": "citrus_v5.zip",
        "dataset_format": "yolo",
        "split": "test",
        "image_count": 445,
        "overall": {"map50": 0.862, "map50_95": 0.66, "precision": 0.9,
                    "recall": 0.85, "f1": 0.874, "fitness": 0.68},
        "micro": {"micro_accuracy": 0.71, "micro_precision": 0.83, "micro_recall": 0.83,
                  "micro_f1": 0.83, "tp": 100, "fp": 20, "fn": 21,
                  "conf_threshold": 0.25, "iou_threshold": 0.45},
        "vocab_check": {"status": "match", "model_names": ["Canker", "Aphid"], "message": None},
        "speed_ms": {"inference": 435.0},
        "per_class": [{"class_id": 0, "name": "Canker", "ap50": 0.803}],
        "size_profile": [{"class_id": 0, "name": "Canker", "boxes": 120}],
        "started_at": "2026-08-30T00:00:00+00:00",
        "finished_at": "2026-08-30T00:04:00+00:00",
        "elapsed_seconds": 240.0,
    }
    job.update(overrides)
    return job


def test_evaluation_is_linked_to_its_weight(registry_db, weight_file):
    sha = registry_service.record_weight(_session(weight_file), ARGS_YAML)
    assert registry_service.record_evaluation(_job(), sha) is True

    detail = registry_service.get_weight_detail(sha)
    assert len(detail["evaluations"]) == 1
    row = detail["evaluations"][0]
    assert row["map50"] == pytest.approx(0.862)
    assert row["micro_accuracy"] == pytest.approx(0.71)
    assert (row["micro_tp"], row["micro_fp"], row["micro_fn"]) == (100, 20, 21)
    assert row["conf_threshold"] == 0.25 and row["iou_threshold"] == 0.45
    assert row["weight_sha256"] == sha


def test_recording_the_same_job_twice_updates_in_place(registry_db, weight_file):
    """啟動時的補寫會重跑已入帳的 job，不得因此變成兩列。"""
    sha = registry_service.record_weight(_session(weight_file), ARGS_YAML)
    registry_service.record_evaluation(_job(), sha)
    registry_service.record_evaluation(_job(overall={"map50": 0.9, "map50_95": 0.7,
                                                     "precision": 0.9, "recall": 0.9}), sha)
    evaluations = registry_service.query_evaluations()
    assert evaluations["total"] == 1
    assert evaluations["evaluations"][0]["map50"] == pytest.approx(0.9)


def test_evaluation_without_a_known_weight_is_not_recorded(registry_db):
    assert registry_service.record_evaluation(_job(), "0" * 64) is False
    assert registry_service.record_evaluation(_job(), None) is False
    assert registry_service.query_evaluations()["total"] == 0


def test_class_names_are_backfilled_from_the_evaluation(registry_db, weight_file):
    """註冊時讀不到 checkpoint 的類別表（要載入模型才有），評估時順手補上。"""
    sha = registry_service.record_weight(_session(weight_file), ARGS_YAML)
    assert registry_service.query_weights()["weights"][0]["class_names"] == []

    registry_service.record_evaluation(_job(), sha)
    assert registry_service.query_weights()["weights"][0]["class_names"] == ["Canker", "Aphid"]


def test_best_metrics_aggregate_across_evaluations(registry_db, weight_file):
    sha = registry_service.record_weight(_session(weight_file), ARGS_YAML)
    registry_service.record_evaluation(_job("eval_1"), sha)
    registry_service.record_evaluation(
        _job("eval_2", overall={"map50": 0.91, "map50_95": 0.70,
                                "precision": 0.9, "recall": 0.9}), sha
    )
    weight = registry_service.query_weights()["weights"][0]
    assert weight["evaluation_count"] == 2
    assert weight["best_map50"] == pytest.approx(0.91)


# --- 查詢 -------------------------------------------------------------------

def test_filter_and_sort_weights(registry_db, tmp_path):
    for idx, (name, arch, epochs) in enumerate(
        [("alpha", "yolo", 50), ("beta", "yolo", 300), ("gamma", "ssdlite_mobilenet_v3_large", 10)]
    ):
        path = tmp_path / f"{name}.pt"
        path.write_bytes(f"content-{idx}".encode())
        registry_service.record_weight(
            _session(str(path), custom_name=name, model_arch=arch),
            {**ARGS_YAML, "epochs": epochs},
        )

    assert registry_service.query_weights(model_arch="yolo")["total"] == 2
    assert registry_service.query_weights(q="bet")["weights"][0]["display_name"] == "beta"

    by_epochs = registry_service.query_weights(order_by="epochs", order="desc")["weights"]
    assert [w["display_name"] for w in by_epochs] == ["beta", "alpha", "gamma"]

    paged = registry_service.query_weights(limit=2, offset=0)
    assert len(paged["weights"]) == 2 and paged["total"] == 3


def test_unknown_order_by_falls_back_instead_of_raising(registry_db, weight_file):
    registry_service.record_weight(_session(weight_file), ARGS_YAML)
    assert registry_service.query_weights(order_by="; DROP TABLE weights")["total"] == 1


def test_stats_reports_totals_and_best(registry_db, weight_file):
    sha = registry_service.record_weight(_session(weight_file), ARGS_YAML)
    registry_service.record_evaluation(_job(), sha)

    stats = registry_service.stats()
    assert stats["available"] is True
    assert stats["backend"] == "sqlite"
    assert stats["total_weights"] == 1
    assert stats["total_training_runs"] == 1
    assert stats["total_evaluations"] == 1
    assert stats["datasets_evaluated"] == ["citrus_v5.zip"]
    best = {entry["metric"]: entry for entry in stats["best"]}
    assert best["mAP@50"]["value"] == pytest.approx(0.862)
    assert best["Micro-Accuracy (Jaccard)"]["value"] == pytest.approx(0.71)


def test_delete_weight_cascades_to_evaluations(registry_db, weight_file):
    sha = registry_service.record_weight(_session(weight_file), ARGS_YAML)
    registry_service.record_evaluation(_job(), sha)

    removed = registry_service.delete_weight(sha)
    assert removed == {"sha256": sha, "deleted_evaluations": 1}
    assert registry_service.query_weights()["total"] == 0
    assert registry_service.query_evaluations()["total"] == 0
    assert registry_service.delete_weight(sha) is None


# --- 降級：資料庫不可用 -----------------------------------------------------

def test_writes_are_silent_no_ops_when_database_is_down(weight_file):
    """這是「資料庫是附加層」這句話的實作定義。

    上傳一顆模型不該因為 PostgreSQL 沒起來而失敗。record_weight 仍要回傳 sha
    （雜湊是純本地計算），只是不寫任何東西。
    """
    db_engine.disable_for_tests()
    try:
        sha = registry_service.record_weight(_session(weight_file), ARGS_YAML)
        assert sha is not None, "雜湊不依賴資料庫，仍應算得出來"
        assert registry_service.record_evaluation(_job(), sha) is False
        assert registry_service.query_weights() == {"weights": [], "total": 0}
        assert registry_service.query_evaluations() == {"evaluations": [], "total": 0}
        assert registry_service.get_weight_detail(sha) is None
        assert registry_service.delete_weight(sha) is None
        assert registry_service.stats()["available"] is False
    finally:
        db_engine.dispose()
