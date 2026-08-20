"""
資料集解析器的測試。

最重要的一組是「上傳的 ZIP 無法評估」——那不是 bug 而是「分析階段完全不解壓縮」這個
核心設計決策的必然代價（見 dataset_analyzer 的模組註解）。測試要釘住的是它會給出
**可理解的說明**而不是神祕的失敗。
"""
import io
import os
import zipfile

import pytest

from app.services import dataset_resolver
from app.services.dataset_resolver import (
    DatasetUnavailable,
    available_splits,
    describe_availability,
    preferred_split,
    resolve_split,
)


def _stats(**overrides):
    base = {
        "format": "yolo",
        "source_path": None,
        "source_container": None,
        "source_inner_prefix": None,
        "splits": [{"name": "train"}, {"name": "valid"}, {"name": "test"}],
        "declared_names": ["Aphid", "Canker"],
    }
    base.update(overrides)
    return base


def _make_split_dir(base, split, images=3, labels=True):
    img_dir = base / split / "images"
    lbl_dir = base / split / "labels"
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)
    for i in range(images):
        (img_dir / f"{split}_{i:03d}.jpg").write_bytes(b"\xff\xd8\xff")
        if labels:
            (lbl_dir / f"{split}_{i:03d}.txt").write_text("0 .5 .5 .2 .2\n", encoding="utf-8")
    return img_dir, lbl_dir


# --- split 選擇 ---------------------------------------------------------------

def test_prefers_test_split_over_train():
    """
    預設必須是 test。

    train 的數字會因為模型見過那些影像而過度樂觀；專題文件也明確把 test 定義為
    「嚴格封印、僅用於最終泛化能力評估」。拿 train 當預設是會誤導使用者的預設值。
    """
    assert preferred_split(_stats()) == "test"


def test_falls_back_through_valid_when_no_test():
    assert preferred_split(_stats(splits=[{"name": "train"}, {"name": "valid"}])) == "valid"
    assert preferred_split(_stats(splits=[{"name": "train"}])) == "train"


def test_available_splits_ignores_unnamed():
    stats = _stats(splits=[{"name": "test"}, {"images": 5}])
    assert available_splits(stats) == ["test"]


# --- 可用性判定 ---------------------------------------------------------------

def test_uploaded_zip_is_unavailable_with_an_explanation():
    """上傳 ZIP 的位元組在請求結束就消失，必須給出說明而非神祕失敗。"""
    ok, reason = describe_availability(_stats())
    assert ok is False
    assert "上傳" in reason and "本機資料夾" in reason


def test_legacy_localibrary_record_asks_for_rescan():
    """舊版掃描留下的紀錄只有 source_path、沒有可開啟的容器。"""
    ok, reason = describe_availability(_stats(source_path="d:/x/mydata"))
    assert ok is False
    assert "重新掃描" in reason


def test_non_yolo_format_is_rejected(tmp_path):
    ok, reason = describe_availability(
        _stats(source_container=str(tmp_path), format="coco")
    )
    assert ok is False
    assert "YOLO" in reason


def test_dataset_without_splits_is_rejected(tmp_path):
    ok, reason = describe_availability(_stats(source_container=str(tmp_path), splits=[]))
    assert ok is False
    assert "split" in reason


def test_directory_source_is_available(tmp_path):
    ok, reason = describe_availability(_stats(source_container=str(tmp_path)))
    assert ok is True
    assert reason is None


# --- 資料夾來源 ---------------------------------------------------------------

def test_directory_split_is_referenced_in_place(tmp_path):
    """
    資料夾來源必須就地引用——一個位元組都不複製。

    這是 LocalLibrary 整個功能的核心保證；複製 4 GB 的資料集只為了跑評估是不能接受的。
    """
    root = tmp_path / "mydata"
    img_dir, lbl_dir = _make_split_dir(root, "test", images=4)
    dest = tmp_path / "should_stay_empty"

    resolved = resolve_split(_stats(source_container=str(root)), "test", str(dest))

    assert os.path.normcase(resolved.images_dir) == os.path.normcase(str(img_dir))
    assert os.path.normcase(resolved.labels_dir) == os.path.normcase(str(lbl_dir))
    assert resolved.image_count == 4
    assert resolved.extracted is False
    assert not dest.exists(), "資料夾來源不得寫入任何東西"


def test_directory_split_honours_inner_prefix(tmp_path):
    """ZIP 常見的包裝目錄在資料夾來源同樣可能出現。"""
    root = tmp_path / "container"
    _make_split_dir(root / "Citrus_v5", "test", images=2)

    resolved = resolve_split(
        _stats(source_container=str(root), source_inner_prefix="Citrus_v5"),
        "test", str(tmp_path / "dest"),
    )
    assert resolved.image_count == 2


def test_unknown_split_name_lists_the_available_ones(tmp_path):
    root = tmp_path / "mydata"
    _make_split_dir(root, "test")
    with pytest.raises(DatasetUnavailable) as exc:
        resolve_split(_stats(source_container=str(root)), "holdout", str(tmp_path / "d"))
    assert "holdout" in str(exc.value)
    assert "test" in str(exc.value)


def test_missing_split_directory_is_reported(tmp_path):
    root = tmp_path / "mydata"
    _make_split_dir(root, "train")
    with pytest.raises(DatasetUnavailable) as exc:
        resolve_split(_stats(source_container=str(root)), "test", str(tmp_path / "d"))
    assert "找不到" in str(exc.value)


# --- ZIP 來源 -----------------------------------------------------------------

def _dataset_zip(path, prefix="bundle", splits=("train", "test"), images=3):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{prefix}/data.yaml", "nc: 2\nnames: [Aphid, Canker]\n")
        for split in splits:
            for i in range(images):
                zf.writestr(f"{prefix}/{split}/images/{split}_{i}.jpg", b"\xff\xd8\xff")
                zf.writestr(f"{prefix}/{split}/labels/{split}_{i}.txt", "0 .5 .5 .2 .2\n")
    path.write_bytes(buf.getvalue())
    return path


def test_zip_source_extracts_only_the_requested_split(tmp_path):
    """
    整包資料集可能有數 GB（實測 4.3 GB），單一 split 只有數百 MB。
    只解出被評估的那一個是這個功能可用性的關鍵。
    """
    zip_path = _dataset_zip(tmp_path / "ds.zip", splits=("train", "valid", "test"), images=3)
    dest = tmp_path / "work"

    resolved = resolve_split(
        _stats(source_container=str(zip_path), source_inner_prefix="bundle"),
        "test", str(dest),
    )

    assert resolved.extracted is True
    assert resolved.image_count == 3
    assert sorted(os.listdir(dest)) == ["test"], "train / valid 不該被解出來"
    assert len(os.listdir(resolved.labels_dir)) == 3


def test_zip_source_flattens_and_pairs_images_with_labels(tmp_path):
    """ultralytics 由影像路徑推導標註路徑，images/ 與 labels/ 必須同名成對。"""
    zip_path = _dataset_zip(tmp_path / "ds.zip", splits=("test",), images=2)
    resolved = resolve_split(
        _stats(source_container=str(zip_path), source_inner_prefix="bundle"),
        "test", str(tmp_path / "work"),
    )
    stems_img = {os.path.splitext(n)[0] for n in os.listdir(resolved.images_dir)}
    stems_lbl = {os.path.splitext(n)[0] for n in os.listdir(resolved.labels_dir)}
    assert stems_img == stems_lbl


def test_zip_source_rejects_oversized_split(tmp_path, monkeypatch):
    """誤選一個超大 split 應該立即擋下，而不是解壓到磁碟爆掉。"""
    monkeypatch.setattr(dataset_resolver, "MAX_EVAL_IMAGES", 2)
    zip_path = _dataset_zip(tmp_path / "ds.zip", splits=("test",), images=5)
    with pytest.raises(DatasetUnavailable) as exc:
        resolve_split(
            _stats(source_container=str(zip_path), source_inner_prefix="bundle"),
            "test", str(tmp_path / "work"),
        )
    assert "上限" in str(exc.value)


def test_zip_source_reports_missing_split(tmp_path):
    zip_path = _dataset_zip(tmp_path / "ds.zip", splits=("train",))
    with pytest.raises(DatasetUnavailable):
        resolve_split(
            _stats(source_container=str(zip_path), source_inner_prefix="bundle",
                   splits=[{"name": "train"}, {"name": "test"}]),
            "test", str(tmp_path / "work"),
        )


def test_corrupt_zip_gives_a_readable_error(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(DatasetUnavailable) as exc:
        resolve_split(
            _stats(source_container=str(bad), source_inner_prefix=""),
            "test", str(tmp_path / "work"),
        )
    assert "損毀" in str(exc.value) or "無法讀取" in str(exc.value)


def test_vanished_source_is_reported(tmp_path):
    with pytest.raises(DatasetUnavailable) as exc:
        resolve_split(
            _stats(source_container=str(tmp_path / "gone")),
            "test", str(tmp_path / "work"),
        )
    assert "不存在" in str(exc.value)
