import json
import os

import pytest

from app.services import dataset_manager


@pytest.fixture(autouse=True)
def clean_active_datasets():
    """ACTIVE_DATASETS 是模組層級 global，測試之間必須隔離。"""
    dataset_manager.ACTIVE_DATASETS.clear()
    yield
    dataset_manager.ACTIVE_DATASETS.clear()


def _stats(dataset_id, created_at="2026-01-01T00:00:00+00:00", schema=None):
    return {
        "schema_version": dataset_manager.DATASET_SCHEMA_VERSION if schema is None else schema,
        "dataset_id": dataset_id,
        "zip_name": f"{dataset_id}.zip",
        "created_at": created_at,
        "total_images": 10,
    }


def test_save_and_reload_round_trip(tmp_path, monkeypatch):
    target = tmp_path / "datasets.json"
    monkeypatch.setattr(dataset_manager, "DATASETS_FILE", str(target))

    dataset_manager.register_dataset(_stats("ds_aaa"))
    assert target.exists()

    dataset_manager.ACTIVE_DATASETS.clear()
    dataset_manager.load_datasets_from_disk()

    assert "ds_aaa" in dataset_manager.ACTIVE_DATASETS
    assert dataset_manager.ACTIVE_DATASETS["ds_aaa"]["total_images"] == 10


def test_load_drops_records_with_wrong_schema_version(tmp_path, monkeypatch):
    target = tmp_path / "datasets.json"
    payload = {
        "ds_good": _stats("ds_good"),
        "ds_old": _stats("ds_old", schema=0),
    }
    target.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(dataset_manager, "DATASETS_FILE", str(target))

    dataset_manager.load_datasets_from_disk()

    assert "ds_good" in dataset_manager.ACTIVE_DATASETS
    assert "ds_old" not in dataset_manager.ACTIVE_DATASETS


def test_load_missing_file_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset_manager, "DATASETS_FILE", str(tmp_path / "nope.json"))
    dataset_manager.load_datasets_from_disk()
    assert dataset_manager.ACTIVE_DATASETS == {}


def test_delete_dataset_touches_no_filesystem(tmp_path, monkeypatch):
    """
    回歸測試：session_manager.delete_session() 用字串切割從 dir_path 反推刪除目標，
    套用在 extracted_runs/datasets/<id> 上會算出 extracted_runs/datasets 並 rmtree
    整個根目錄。資料集採 stats-only 設計，刪除只能動 dict，絕不能碰檔案系統。
    """
    target = tmp_path / "datasets.json"
    monkeypatch.setattr(dataset_manager, "DATASETS_FILE", str(target))

    sentinels = [tmp_path / "weight", tmp_path / "images", tmp_path / "datasets"]
    for path in sentinels:
        path.mkdir()
        (path / "keepme.txt").write_text("important", encoding="utf-8")

    dataset_manager.register_dataset(_stats("ds_del"))
    snapshot = dataset_manager.delete_dataset("ds_del")

    assert snapshot == {}
    assert "ds_del" not in dataset_manager.ACTIVE_DATASETS
    for path in sentinels:
        assert path.exists(), f"{path} 不該被刪除"
        assert (path / "keepme.txt").read_text(encoding="utf-8") == "important"


def test_delete_unknown_dataset_raises_keyerror(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset_manager, "DATASETS_FILE", str(tmp_path / "datasets.json"))
    with pytest.raises(KeyError):
        dataset_manager.delete_dataset("ds_missing")


def test_max_datasets_evicts_oldest(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset_manager, "DATASETS_FILE", str(tmp_path / "datasets.json"))
    monkeypatch.setattr(dataset_manager, "MAX_DATASETS", 2)

    dataset_manager.register_dataset(_stats("ds_old", "2026-01-01T00:00:00+00:00"))
    dataset_manager.register_dataset(_stats("ds_mid", "2026-02-01T00:00:00+00:00"))
    dataset_manager.register_dataset(_stats("ds_new", "2026-03-01T00:00:00+00:00"))

    assert set(dataset_manager.ACTIVE_DATASETS) == {"ds_mid", "ds_new"}


def test_assert_within_containment():
    base = os.path.dirname(os.path.abspath(__file__))
    assert dataset_manager._assert_within(base, os.path.join(base, "sub", "file.txt"))
    assert not dataset_manager._assert_within(base, os.path.join(base, "..", "escape.txt"))
