from PIL import Image

from app.utils.image_cropper import crop_metric_image

# results.png grid is 5 columns x 2 rows.
GRID_W, GRID_H = 100, 60
IMG_W, IMG_H = GRID_W * 5, GRID_H * 2

CELL_COLORS = {
    (0, 0): (255, 0, 0),      # train_box_loss
    (1, 0): (0, 255, 0),      # train_cls_loss
    (2, 0): (0, 0, 255),      # train_dfl_loss
    (3, 0): (255, 255, 0),    # precision
    (4, 0): (255, 0, 255),    # recall
    (0, 1): (0, 255, 255),    # val_box_loss
    (1, 1): (128, 0, 0),      # val_cls_loss
    (2, 1): (0, 128, 0),      # val_dfl_loss
    (3, 1): (0, 0, 128),      # mAP50
    (4, 1): (128, 128, 0),    # mAP50_95
}


def _make_grid_image(path):
    img = Image.new("RGB", (IMG_W, IMG_H))
    for (col, row), color in CELL_COLORS.items():
        for x in range(col * GRID_W, (col + 1) * GRID_W):
            for y in range(row * GRID_H, (row + 1) * GRID_H):
                img.putpixel((x, y), color)
    img.save(path)


def test_crop_returns_none_for_missing_source(tmp_path):
    result = crop_metric_image(str(tmp_path / "missing.png"), str(tmp_path / "out.png"), "mAP50")
    assert result is None


def test_crop_extracts_expected_cell(tmp_path):
    src = tmp_path / "results.png"
    _make_grid_image(src)

    out = tmp_path / "mAP50.png"
    crop_metric_image(str(src), str(out), "mAP50")

    cropped = Image.open(out)
    assert cropped.size == (GRID_W, GRID_H)
    # mAP50 is column 3, row 1 -> (0, 0, 128)
    assert cropped.getpixel((5, 5)) == (0, 0, 128)


def test_crop_recall_is_top_row_last_column(tmp_path):
    src = tmp_path / "results.png"
    _make_grid_image(src)

    out = tmp_path / "recall.png"
    crop_metric_image(str(src), str(out), "recall")

    cropped = Image.open(out)
    assert cropped.getpixel((5, 5)) == (255, 0, 255)


def test_crop_unknown_metric_falls_back_to_first_cell(tmp_path):
    src = tmp_path / "results.png"
    _make_grid_image(src)

    out = tmp_path / "unknown.png"
    crop_metric_image(str(src), str(out), "totally_unknown_metric")

    cropped = Image.open(out)
    assert cropped.getpixel((5, 5)) == (255, 0, 0)
