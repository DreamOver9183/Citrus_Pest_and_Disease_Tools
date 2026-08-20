"""
目錄來源 reader 的測試。

核心命題：同一份邏輯內容，不論來自 ZIP 或真實目錄，分析結果都必須一致——
這是 reader 抽象層存在的唯一理由，也是本檔最主要的驗證目標。
"""
import io
import zipfile

import pytest

from app.services.dataset_analyzer import analyze_dataset
from app.utils import dataset_dir as dataset_dir_mod
from app.utils.dataset_dir import DirArchiveReader, build_virtual_tree_from_dir
from app.utils.dataset_zip import ZipArchiveReader
from app.utils.zip_handler import ZipIndexError

YAML_2 = """\
train: train/images
val: valid/images
nc: 2
names:
- Aphid
- Canker
"""


def _entries(root=""):
    """一份同時可用於 ZIP 與目錄的內容定義。"""
    prefix = f"{root}/" if root else ""
    return {
        f"{prefix}data.yaml": YAML_2,
        f"{prefix}train/images/i1.jpg": b"",
        f"{prefix}train/labels/i1.txt": "0 .5 .5 .1 .1\n1 .5 .5 .1 .1\n",
        f"{prefix}train/images/i2.jpg": b"",
        f"{prefix}train/labels/i2.txt": "1 .5 .5 .1 .1\n",
        f"{prefix}valid/images/v1.jpg": b"",
        f"{prefix}valid/labels/v1.txt": "0 .5 .5 .1 .1\n",
    }


def _as_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content.encode("utf-8") if isinstance(content, str) else content)
    buf.seek(0)
    return zipfile.ZipFile(buf)


def _as_dir(tmp_path, entries):
    for name, content in entries.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            target.write_text(content, encoding="utf-8")
        else:
            target.write_bytes(content)
    return str(tmp_path)


# --- reader 對等性（本檔最主要的驗證目標）----------------------------------

@pytest.mark.parametrize("root", ["", "Datasets_YOLO26_v5"])
def test_zip_and_dir_readers_produce_identical_analysis(tmp_path, root):
    entries = _entries(root=root)

    with _as_zip(entries) as zf:
        zip_result = analyze_dataset(ZipArchiveReader(zf), "t.zip", zip_size_bytes=None)

    dir_result = analyze_dataset(DirArchiveReader(_as_dir(tmp_path, entries)), "t", zip_size_bytes=None)

    # 逐一比對所有與來源無關的統計欄位
    for key in ("format", "analysis_depth", "verified", "root_prefix",
                "total_images", "total_annotations", "total_label_files",
                "background_images", "declared_nc", "declared_names",
                "max_class_id_found", "member_count", "uncompressed_size_mb"):
        assert zip_result[key] == dir_result[key], f"{key} 不一致（root={root!r}）"

    assert [c["count"] for c in zip_result["classes"]] == [c["count"] for c in dir_result["classes"]]
    assert [(s["name"], s["images"], s["annotations"]) for s in zip_result["splits"]] == \
           [(s["name"], s["images"], s["annotations"]) for s in dir_result["splits"]]


def test_dir_reader_detects_nested_wrapper(tmp_path):
    result = analyze_dataset(
        DirArchiveReader(_as_dir(tmp_path, _entries(root="wrapper"))), "t", zip_size_bytes=None
    )
    assert result["format"] == "yolo"
    assert result["root_prefix"] == "wrapper/"


# --- TextBudget 地雷（最高價值測試）-----------------------------------------

def test_dir_source_still_enforces_text_budget(tmp_path, monkeypatch):
    """
    釘住 _DirEntryStat 必須有 .file_size 這件事。

    dataset_analyzer 的截斷檢查是
        info = tree.member_by_path.get(path)
        if info is not None and not budget.try_spend(info.file_size)
    若目錄來源把 member_by_path 的值塞成 None，這個 `is not None` 前置條件會讓整個
    TextBudget 保護悄悄失效——不報錯、只是永遠不截斷。沒有這個測試，那個 bug
    完全無聲無息。
    """
    entries = {"data.yaml": YAML_2}
    for i in range(6):
        entries[f"train/images/i{i}.jpg"] = b""
        entries[f"train/labels/i{i}.txt"] = "0 .5 .5 .1 .1\n" * 50

    monkeypatch.setattr("app.services.dataset_analyzer.MAX_DATASET_TEXT_MB", 0)
    result = analyze_dataset(DirArchiveReader(_as_dir(tmp_path, entries)), "t", zip_size_bytes=None)

    assert result["truncated"] is True
    assert any(i["code"] == "W_TRUNCATED" for i in result["issues"])


def test_member_by_path_values_expose_file_size(tmp_path):
    """直接檢查樹的值型別，與上面的行為測試互為表裡。"""
    _as_dir(tmp_path, _entries())
    tree = build_virtual_tree_from_dir(str(tmp_path))
    assert tree.member_by_path, "樹不應為空"
    for path, info in tree.member_by_path.items():
        assert info is not None, f"{path} 的值是 None——會讓 TextBudget 失效"
        assert isinstance(info.file_size, int)


# --- 目錄走訪細節 -----------------------------------------------------------

def test_noise_members_ignored(tmp_path):
    entries = _entries()
    entries["train/images/.DS_Store"] = b"junk"
    entries["__MACOSX/train/images/._i1.jpg"] = b"junk"
    result = analyze_dataset(DirArchiveReader(_as_dir(tmp_path, entries)), "t", zip_size_bytes=None)
    assert result["total_images"] == 3


def test_missing_directory_raises(tmp_path):
    with pytest.raises(ZipIndexError, match="找不到資料夾"):
        DirArchiveReader(str(tmp_path / "nope")).build_tree()


def test_read_missing_file_raises(tmp_path):
    _as_dir(tmp_path, _entries())
    with pytest.raises(ZipIndexError, match="找不到檔案"):
        DirArchiveReader(str(tmp_path)).read("does/not/exist.txt")


def test_read_respects_cap(tmp_path):
    (tmp_path / "big.txt").write_text("x" * 100, encoding="utf-8")
    with pytest.raises(ZipIndexError, match="過大"):
        DirArchiveReader(str(tmp_path)).read("big.txt", cap=4)


def test_rejects_too_many_files(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset_dir_mod, "MAX_DATASET_MEMBERS", 3)
    _as_dir(tmp_path, _entries())
    with pytest.raises(ZipIndexError, match="數量過多"):
        build_virtual_tree_from_dir(str(tmp_path))


def test_rejects_oversized_total(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset_dir_mod, "MAX_DATASET_UNCOMPRESSED_GB", 0)
    _as_dir(tmp_path, _entries())
    with pytest.raises(ZipIndexError, match="總大小過大"):
        build_virtual_tree_from_dir(str(tmp_path))


def test_unrecognized_directory_raises(tmp_path):
    (tmp_path / "readme.txt").write_text("hello", encoding="utf-8")
    with pytest.raises(ZipIndexError, match="無法辨識資料集格式"):
        analyze_dataset(DirArchiveReader(str(tmp_path)), "t", zip_size_bytes=None)
