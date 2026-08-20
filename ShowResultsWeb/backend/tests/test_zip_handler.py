import os
import zipfile

import pytest

from app.utils.zip_handler import ZipIndexError, extract_and_index, index_single_weight


def _make_zip(zip_path, entries):
    """entries: dict of {arcname: bytes}"""
    with zipfile.ZipFile(zip_path, "w") as zf:
        for arcname, data in entries.items():
            zf.writestr(arcname, data)


def test_extract_and_index_finds_valid_run(tmp_path):
    zip_path = tmp_path / "run.zip"
    _make_zip(
        zip_path,
        {
            "train/args.yaml": "epochs: 50\noptimizer: AdamW\nmodel: yolo26n.pt\n",
            "train/weights/best.pt": b"fake-weights",
            "train/results.csv": "epoch,metrics/mAP50(B)\n0,0.1\n1,0.9\n",
            "train/results.png": b"fake-png",
            "train/confusion_matrix.png": b"fake-png",
        },
    )

    extract_to = tmp_path / "extracted"
    found_runs = extract_and_index(str(zip_path), str(extract_to))

    assert len(found_runs) == 1
    run = found_runs[0]
    assert run["epochs"] == 50
    assert run["optimizer"] == "AdamW"
    assert run["model_cfg"] == "yolo26n.pt"
    assert run["weights_path"].endswith("best.pt")
    assert os.path.exists(run["weights_path"])
    assert run["metrics_summary"].get("mAP50") == "0.9"
    assert run["results_png"] is not None
    assert run["confusion_matrix"] is not None


def test_extract_and_index_ignores_folders_without_weights(tmp_path):
    zip_path = tmp_path / "run.zip"
    _make_zip(
        zip_path,
        {
            "notes/readme.txt": "just some notes, no weights here",
        },
    )

    extract_to = tmp_path / "extracted"
    found_runs = extract_and_index(str(zip_path), str(extract_to))

    assert found_runs == []


def test_extract_and_index_rejects_bad_zip(tmp_path):
    bad_zip = tmp_path / "not_a_zip.zip"
    bad_zip.write_bytes(b"this is definitely not a zip file")

    with pytest.raises(ZipIndexError):
        extract_and_index(str(bad_zip), str(tmp_path / "extracted"))


def test_extract_and_index_blocks_path_traversal(tmp_path):
    zip_path = tmp_path / "evil.zip"
    # zipfile.writestr allows arbitrary arcnames including traversal sequences.
    _make_zip(zip_path, {"../../evil.txt": b"pwned"})

    with pytest.raises(ZipIndexError):
        extract_and_index(str(zip_path), str(tmp_path / "extracted"))


def test_index_single_weight_renames_pth_to_pt(tmp_path):
    src_file = tmp_path / "uploaded_model.pth"
    src_file.write_bytes(b"fake-weights")

    dest_dir = tmp_path / "dest"
    info = index_single_weight(str(src_file), str(dest_dir))

    assert info["weights_path"].endswith("uploaded_model.pt")
    assert os.path.exists(info["weights_path"])
    assert info["weights_size_mb"] >= 0
