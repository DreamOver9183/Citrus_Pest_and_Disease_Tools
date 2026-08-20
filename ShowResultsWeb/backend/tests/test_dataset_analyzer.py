import io
import zipfile

import pytest

from app.services import dataset_analyzer as analyzer_mod
from app.services.dataset_analyzer import analyze_dataset
from app.utils import dataset_zip as dataset_zip_mod
from app.utils.dataset_zip import ZipArchiveReader
from app.utils.zip_handler import ZipIndexError

YAML_8 = """\
train: train/images
val: valid/images
test: test/images
nc: 2
names:
- Aphid
- Canker
"""


def _zip(entries: dict) -> zipfile.ZipFile:
    """entries: {arcname: bytes|str}"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            if isinstance(content, str):
                content = content.encode("utf-8")
            zf.writestr(name, content)
    buf.seek(0)
    return zipfile.ZipFile(buf)


def _yolo_entries(root="", yaml_text=YAML_8, splits=("train",)):
    prefix = f"{root}/" if root else ""
    entries = {f"{prefix}data.yaml": yaml_text} if yaml_text is not None else {}
    for split in splits:
        entries[f"{prefix}{split}/images/a_0001.jpg"] = b""
        entries[f"{prefix}{split}/labels/a_0001.txt"] = "0 0.5 0.5 0.1 0.1\n"
    return entries


def _run(entries):
    with _zip(entries) as zf:
        return analyze_dataset(ZipArchiveReader(zf, zip_size_bytes=1234), "t.zip", 1234)


# --- 格式偵測 ---------------------------------------------------------------

def test_detects_yolo_under_nested_wrapper():
    """真實 ZIP 內含一層包裝目錄（Datasets_YOLO26_v5/train/...），必須自動下鑽。"""
    result = _run(_yolo_entries(root="Datasets_YOLO26_v5"))
    assert result["format"] == "yolo"
    assert result["root_prefix"] == "Datasets_YOLO26_v5/"
    assert result["analysis_depth"] == "deep"
    assert result["verified"] is True


def test_detects_yolo_at_zip_root():
    result = _run(_yolo_entries(root=""))
    assert result["format"] == "yolo"
    assert result["root_prefix"] == ""


def test_detects_yolo_without_data_yaml():
    result = _run(_yolo_entries(root="ds", yaml_text=None))
    assert result["format"] == "yolo"
    assert any(i["code"] == "W_NO_DATA_YAML" for i in result["issues"])


def test_yolo_wins_when_yaml_and_coco_json_both_present():
    """Roboflow 匯出常同時帶兩種格式；YOLO 必須勝出，且 COCO 仍列入候選。"""
    entries = _yolo_entries(root="ds")
    entries["ds/_annotations.coco.json"] = (
        '{"images": [{"id": 1}], "annotations": [{"id": 1, "image_id": 1, "category_id": 1}],'
        ' "categories": [{"id": 1, "name": "Aphid"}]}'
    )
    result = _run(entries)
    assert result["format"] == "yolo"
    assert "coco" in result["detected_candidates"]


def test_unrecognized_archive_raises():
    with pytest.raises(ZipIndexError):
        _run({"notes/readme.txt": "hello", "notes/other.txt": "world"})


# --- 計數正確性 -------------------------------------------------------------

def test_per_class_annotation_counts():
    entries = {
        "ds/data.yaml": YAML_8,
        "ds/train/images/i1.jpg": b"", "ds/train/labels/i1.txt": "0 .5 .5 .1 .1\n1 .5 .5 .1 .1\n",
        "ds/train/images/i2.jpg": b"", "ds/train/labels/i2.txt": "1 .5 .5 .1 .1\n",
        "ds/valid/images/v1.jpg": b"", "ds/valid/labels/v1.txt": "0 .5 .5 .1 .1\n",
    }
    result = _run(entries)
    assert result["total_images"] == 3
    assert result["total_annotations"] == 4
    by_id = {c["id"]: c for c in result["classes"]}
    assert by_id[0]["count"] == 2
    assert by_id[1]["count"] == 2
    assert by_id[0]["per_split"] == {"train": 1, "valid": 1}
    assert result["max_class_id_found"] == 1


def test_yaml_val_key_maps_to_valid_dir():
    """yaml 寫 val:，磁碟上是 valid/。split 名以目錄為準，且不得產生 error。"""
    entries = {
        "ds/data.yaml": YAML_8,
        "ds/valid/images/v1.jpg": b"", "ds/valid/labels/v1.txt": "0 .5 .5 .1 .1\n",
    }
    result = _run(entries)
    names = [s["name"] for s in result["splits"]]
    assert names == ["valid"]
    assert result["splits"][0]["annotations"] == 1
    assert not [i for i in result["issues"] if i["level"] == "error"]
    assert any(i["code"] == "I_YAML_KEY_DIR_MAPPING" for i in result["issues"])


def test_unresolvable_yaml_path_key_does_not_zero_counts():
    """
    真實 v5 的 data.yaml 帶 path: "f:\\115...\\Citrus_YOLO26_Detect"，指向他機路徑。
    這只能是資訊，計數必須照樣正確。
    """
    yaml_text = 'path: "f:\\\\115\\\\Citrus_YOLO26_Detect"\n' + YAML_8
    entries = {
        "ds/data.yaml": yaml_text,
        "ds/train/images/i1.jpg": b"", "ds/train/labels/i1.txt": "0 .5 .5 .1 .1\n",
    }
    result = _run(entries)
    assert result["total_images"] == 1
    assert result["total_annotations"] == 1
    assert not [i for i in result["issues"] if i["level"] == "error"]


def test_case_insensitive_image_extensions():
    entries = {
        "ds/data.yaml": YAML_8,
        "ds/train/images/a.JPG": b"", "ds/train/labels/a.txt": "0 .5 .5 .1 .1\n",
        "ds/train/images/b.PNG": b"", "ds/train/labels/b.txt": "0 .5 .5 .1 .1\n",
        "ds/train/images/c.JPEG": b"", "ds/train/labels/c.txt": "0 .5 .5 .1 .1\n",
    }
    assert _run(entries)["total_images"] == 3


def test_backslash_member_names_are_normalized():
    entries = {
        "ds\\data.yaml": YAML_8,
        "ds\\train\\images\\a.jpg": b"",
        "ds\\train\\labels\\a.txt": "0 .5 .5 .1 .1\n",
    }
    result = _run(entries)
    assert result["format"] == "yolo"
    assert result["total_images"] == 1


def test_macosx_members_ignored():
    entries = _yolo_entries(root="ds")
    entries["__MACOSX/ds/train/images/._a_0001.jpg"] = b"junk"
    entries["ds/train/images/.DS_Store"] = b"junk"
    assert _run(entries)["total_images"] == 1


def test_classes_txt_not_counted_as_label():
    entries = _yolo_entries(root="ds")
    entries["ds/train/labels/classes.txt"] = "Aphid\nCanker\n"
    result = _run(entries)
    assert result["total_label_files"] == 1


# --- 空標註語意（實測資料集有 450 個空標註檔）-------------------------------

def test_empty_label_file_is_background_not_error():
    entries = {
        "ds/data.yaml": YAML_8,
        "ds/train/images/h1.jpg": b"", "ds/train/labels/h1.txt": "",
        "ds/train/images/h2.jpg": b"", "ds/train/labels/h2.txt": "0 .5 .5 .1 .1\n",
    }
    result = _run(entries)
    assert result["background_images"] == 1
    assert result["total_annotations"] == 1
    assert not [i for i in result["issues"] if i["level"] == "error"]
    assert any(i["code"] == "I_BACKGROUND_IMAGES" for i in result["issues"])


def test_class_with_zero_instances_is_info_only():
    entries = {
        "ds/data.yaml": YAML_8,
        "ds/train/images/i1.jpg": b"", "ds/train/labels/i1.txt": "0 .5 .5 .1 .1\n",
    }
    result = _run(entries)
    codes = {i["code"]: i["level"] for i in result["issues"]}
    assert codes.get("I_CLASS_ZERO_INSTANCES") == "info"
    assert not [i for i in result["issues"] if i["level"] == "error"]


# --- 交叉驗證 ---------------------------------------------------------------

def test_out_of_range_class_id_is_error():
    entries = {
        "ds/data.yaml": YAML_8,          # nc: 2
        "ds/train/images/i1.jpg": b"", "ds/train/labels/i1.txt": "5 .5 .5 .1 .1\n",
    }
    result = _run(entries)
    assert result["max_class_id_found"] == 5
    assert any(i["code"] == "E_CLASS_ID_OUT_OF_RANGE" and i["level"] == "error"
               for i in result["issues"])


def test_nc_names_length_mismatch():
    yaml_text = "train: train/images\nnc: 5\nnames:\n- A\n- B\n"
    entries = {
        "ds/data.yaml": yaml_text,
        "ds/train/images/i1.jpg": b"", "ds/train/labels/i1.txt": "0 .5 .5 .1 .1\n",
    }
    result = _run(entries)
    assert any(i["code"] == "E_NC_NAMES_MISMATCH" for i in result["issues"])


def test_names_as_dict_is_accepted():
    yaml_text = "train: train/images\nnc: 2\nnames:\n  0: Aphid\n  1: Canker\n"
    entries = {
        "ds/data.yaml": yaml_text,
        "ds/train/images/i1.jpg": b"", "ds/train/labels/i1.txt": "0 .5 .5 .1 .1\n",
    }
    result = _run(entries)
    assert result["declared_names"] == ["Aphid", "Canker"]


def test_yaml_with_bom_is_parsed():
    """帶 BOM 的 yaml 若不用 utf-8-sig，train key 會變成 '\\ufefftrain' 而靜默失效。"""
    entries = {
        "ds/data.yaml": b"\xef\xbb\xbf" + YAML_8.encode("utf-8"),
        "ds/train/images/i1.jpg": b"", "ds/train/labels/i1.txt": "0 .5 .5 .1 .1\n",
    }
    result = _run(entries)
    assert result["declared_nc"] == 2
    assert result["declared_names"] == ["Aphid", "Canker"]


def test_unpaired_image_and_label_are_warnings():
    entries = {
        "ds/data.yaml": YAML_8,
        "ds/train/images/paired.jpg": b"", "ds/train/labels/paired.txt": "0 .5 .5 .1 .1\n",
        "ds/train/images/orphan_img.jpg": b"",
        "ds/train/labels/orphan_lbl.txt": "0 .5 .5 .1 .1\n",
    }
    result = _run(entries)
    split = result["splits"][0]
    assert split["images_without_label"] == 1
    assert split["labels_without_image"] == 1
    codes = {i["code"] for i in result["issues"]}
    assert "W_MISSING_LABEL_FILE" in codes and "W_ORPHAN_LABEL_FILE" in codes


def test_malformed_label_lines():
    entries = {
        "ds/data.yaml": YAML_8,
        "ds/train/images/i1.jpg": b"",
        "ds/train/labels/i1.txt": "abc .5 .5 .1 .1\n3 .5\n0 .5 .5 .1 .1\n",
    }
    result = _run(entries)
    bad = [i for i in result["issues"] if i["code"] == "E_MALFORMED_LABEL_LINE"]
    assert bad and bad[0]["level"] == "error"
    assert len(bad[0]["samples"]) == 2
    assert result["total_annotations"] == 1


# --- 檔名類別提示（實測 4,098 檔 100% 命中）--------------------------------

def test_class_hint_matches_when_present():
    entries = {
        "ds/data.yaml": YAML_8,
        "ds/train/images/synth_aug_cls1_00001.jpg": b"",
        "ds/train/labels/synth_aug_cls1_00001.txt": "1 .5 .5 .1 .1\n",
    }
    result = _run(entries)
    assert result["prefix_check"]["status"] == "ok"
    assert result["prefix_check"]["checked"] == 1
    assert result["prefix_check"]["matched"] == 1


def test_class_hint_allows_extra_classes():
    """一張影像可含多個類別；只要提示的類別有出現就算通過（用包含而非等於）。"""
    entries = {
        "ds/data.yaml": YAML_8,
        "ds/train/images/synth_aug_cls1_00001.jpg": b"",
        "ds/train/labels/synth_aug_cls1_00001.txt": "1 .5 .5 .1 .1\n0 .5 .5 .1 .1\n",
    }
    assert _run(entries)["prefix_check"]["status"] == "ok"


def test_class_hint_mismatch_is_warning():
    entries = {
        "ds/data.yaml": YAML_8,
        "ds/train/images/synth_aug_cls1_00001.jpg": b"",
        "ds/train/labels/synth_aug_cls1_00001.txt": "0 .5 .5 .1 .1\n",
    }
    result = _run(entries)
    assert result["prefix_check"]["status"] == "mismatch"
    assert result["prefix_check"]["mismatched"] == 1
    assert any(i["code"] == "W_PREFIX_CLASS_MISMATCH" for i in result["issues"])


def test_class_hint_skips_empty_files():
    entries = {
        "ds/data.yaml": YAML_8,
        "ds/train/images/synth_aug_cls1_00001.jpg": b"",
        "ds/train/labels/synth_aug_cls1_00001.txt": "",
    }
    result = _run(entries)
    assert result["prefix_check"]["checked"] == 0
    assert result["prefix_check"]["status"] == "not_applicable"


def test_class_hint_not_applicable_for_plain_names():
    entries = {
        "ds/data.yaml": YAML_8,
        "ds/train/images/train_raw_0001.jpg": b"",
        "ds/train/labels/train_raw_0001.txt": "0 .5 .5 .1 .1\n",
    }
    result = _run(entries)
    assert result["prefix_check"]["status"] == "not_applicable"
    assert not [i for i in result["issues"] if i["code"] == "W_PREFIX_CLASS_MISMATCH"]


# --- COCO / VOC -------------------------------------------------------------

def test_detects_coco_basic():
    entries = {
        "ds/annotations/instances_train.json": (
            '{"images": [{"id": 1}, {"id": 2}],'
            ' "annotations": [{"id": 1, "image_id": 1, "category_id": 1},'
            '                 {"id": 2, "image_id": 1, "category_id": 2},'
            '                 {"id": 3, "image_id": 2, "category_id": 1}],'
            ' "categories": [{"id": 1, "name": "Aphid"}, {"id": 2, "name": "Canker"}]}'
        ),
    }
    result = _run(entries)
    assert result["format"] == "coco"
    assert result["analysis_depth"] == "basic"
    assert result["verified"] is False
    assert result["unverified_note"]
    assert result["total_images"] == 2
    assert result["total_annotations"] == 3
    by_name = {c["name"]: c["count"] for c in result["classes"]}
    assert by_name == {"Aphid": 2, "Canker": 1}


def test_detects_voc_basic():
    xml = ("<annotation><filename>a.jpg</filename>"
           "<object><name>Aphid</name></object>"
           "<object><name>Canker</name></object></annotation>")
    entries = {
        "ds/Annotations/a.xml": xml,
        "ds/JPEGImages/a.jpg": b"",
    }
    result = _run(entries)
    assert result["format"] == "voc"
    assert result["verified"] is False
    assert result["total_annotations"] == 2
    assert result["total_images"] == 1


def test_voc_rejects_doctype():
    """expat 對 entity expansion 無防護；含 DOCTYPE 的 XML 必須在解析前被拒。"""
    evil = ('<?xml version="1.0"?>\n'
            '<!DOCTYPE foo [<!ENTITY a "aaaaaaaaaa">]>\n'
            '<annotation><object><name>&a;</name></object></annotation>')
    entries = {
        "ds/Annotations/evil.xml": evil,
        "ds/JPEGImages/a.jpg": b"",
    }
    result = _run(entries)
    assert any(i["code"] == "E_XML_DOCTYPE_REJECTED" and i["level"] == "error"
               for i in result["issues"])
    assert result["total_annotations"] == 0


# --- 安全與上限 -------------------------------------------------------------

def test_rejects_path_traversal_member():
    entries = _yolo_entries(root="ds")
    entries["../../evil.txt"] = "pwned"
    with pytest.raises(ZipIndexError):
        _run(entries)


def test_rejects_too_many_members(monkeypatch):
    monkeypatch.setattr(dataset_zip_mod, "MAX_DATASET_MEMBERS", 2)
    with pytest.raises(ZipIndexError, match="數量過多"):
        _run(_yolo_entries(root="ds", splits=("train", "valid", "test")))


def test_rejects_oversized_zip(monkeypatch):
    monkeypatch.setattr(dataset_zip_mod, "MAX_DATASET_ZIP_MB", 0)
    with _zip(_yolo_entries(root="ds")) as zf:
        with pytest.raises(ZipIndexError, match="過大"):
            analyze_dataset(
                ZipArchiveReader(zf, zip_size_bytes=10 * 1024 * 1024),
                "t.zip", zip_size_bytes=10 * 1024 * 1024,
            )


def test_rejects_oversized_uncompressed_total(monkeypatch):
    monkeypatch.setattr(dataset_zip_mod, "MAX_DATASET_UNCOMPRESSED_GB", 0)
    with pytest.raises(ZipIndexError, match="解壓後總大小過大"):
        _run(_yolo_entries(root="ds"))


def test_read_member_capped_rejects_oversize():
    """
    上限量的是實際解壓出的位元組，而不是中央目錄宣告的 file_size，
    因此偽造 file_size 的壓縮炸彈也會被擋下。
    """
    with _zip({"big.txt": "x" * 100}) as zf:
        with pytest.raises(ZipIndexError, match="過大"):
            dataset_zip_mod.read_member_capped(zf, "big.txt", cap=4)


def test_label_file_budget_truncates_instead_of_failing(monkeypatch):
    monkeypatch.setattr(analyzer_mod, "MAX_DATASET_LABEL_FILES", 1)
    entries = {
        "ds/data.yaml": YAML_8,
        "ds/train/images/i1.jpg": b"", "ds/train/labels/i1.txt": "0 .5 .5 .1 .1\n",
        "ds/train/images/i2.jpg": b"", "ds/train/labels/i2.txt": "1 .5 .5 .1 .1\n",
    }
    result = _run(entries)
    assert result["truncated"] is True
    assert any(i["code"] == "W_TRUNCATED" for i in result["issues"])


# --- 回應契約 ---------------------------------------------------------------

def test_all_keys_always_present():
    """
    router 使用 response_model_exclude_unset=True，條件式省略的欄位會從 JSON
    消失並在前端變成 undefined。分析器必須一律輸出所有 key。
    """
    expected = set(analyzer_mod._base_result("x").keys())
    for entries in (_yolo_entries(root="ds"),
                    {"ds/Annotations/a.xml": "<annotation><object><name>A</name></object></annotation>",
                     "ds/JPEGImages/a.jpg": b""}):
        assert set(_run(entries).keys()) == expected
