"""
能力探測測試。

刻意不 import onnx / litert / tensorflow —— 探測本身就只用 find_spec，測試也一樣。
"""
import pytest

from app.services import export_capabilities as caps


@pytest.fixture(autouse=True)
def clear_cache():
    caps.refresh()
    yield
    caps.refresh()


def _patch(monkeypatch, *, system, machine, present):
    monkeypatch.setattr(caps.platform, "system", lambda: system)
    monkeypatch.setattr(caps.platform, "machine", lambda: machine)
    monkeypatch.setattr(caps, "_find_spec", lambda m: m in present)


def _by_format(result):
    return {f["format"]: f for f in result["formats"]}


ALL_MODULES = {"onnx", "onnxruntime", "onnxslim", "litert_torch", "ai_edge_litert"}


def test_windows_blocks_litert_by_platform_not_dependency(monkeypatch):
    """Windows 上即使套件齊全，litert 仍應以「平台」為由被擋。"""
    _patch(monkeypatch, system="Windows", machine="AMD64", present=ALL_MODULES)
    fmts = _by_format(caps.get_capabilities())

    assert fmts["onnx"]["available"] is True
    assert fmts["litert"]["available"] is False
    assert fmts["litert"]["reason_kind"] == "platform"
    assert "Windows" in fmts["litert"]["reason"]
    assert fmts["litert"]["missing"] == []


def test_linux_missing_deps_reports_dependency_reason(monkeypatch):
    _patch(monkeypatch, system="Linux", machine="x86_64", present={"onnx", "onnxruntime", "onnxslim"})
    fmts = _by_format(caps.get_capabilities())

    assert fmts["onnx"]["available"] is True
    assert fmts["litert"]["available"] is False
    assert fmts["litert"]["reason_kind"] == "dependency"
    assert set(fmts["litert"]["missing"]) == {"litert_torch", "ai_edge_litert"}


def test_platform_and_dependency_reasons_are_distinct(monkeypatch):
    """兩道閘的意義就在於給出不同的下一步建議。"""
    _patch(monkeypatch, system="Windows", machine="AMD64", present=ALL_MODULES)
    platform_reason = _by_format(caps.get_capabilities())["litert"]["reason"]

    caps.refresh()
    _patch(monkeypatch, system="Linux", machine="x86_64", present={"onnx"})
    dependency_reason = _by_format(caps.get_capabilities())["litert"]["reason"]

    assert platform_reason != dependency_reason
    assert "Docker" in platform_reason
    assert "套件" in dependency_reason


def test_linux_with_all_deps_enables_both(monkeypatch):
    _patch(monkeypatch, system="Linux", machine="x86_64", present=ALL_MODULES)
    fmts = _by_format(caps.get_capabilities())
    assert fmts["onnx"]["available"] is True
    assert fmts["litert"]["available"] is True
    assert caps.get_capabilities()["any_available"] is True


def test_arm64_linux_blocks_litert(monkeypatch):
    """litert 沒有 aarch64 輪子，exporter 的斷言也擋掉 ARM64 Linux。"""
    _patch(monkeypatch, system="Linux", machine="aarch64", present=ALL_MODULES)
    fmts = _by_format(caps.get_capabilities())
    assert fmts["litert"]["available"] is False
    assert fmts["litert"]["reason_kind"] == "platform"


def test_macos_allows_litert(monkeypatch):
    _patch(monkeypatch, system="Darwin", machine="arm64", present=ALL_MODULES)
    assert _by_format(caps.get_capabilities())["litert"]["available"] is True


def test_missing_onnx_makes_onnx_unavailable(monkeypatch):
    _patch(monkeypatch, system="Linux", machine="x86_64", present={"onnxruntime"})
    fmts = _by_format(caps.get_capabilities())
    assert fmts["onnx"]["available"] is False
    assert fmts["onnx"]["reason_kind"] == "dependency"
    assert fmts["onnx"]["missing"] == ["onnx"]


def test_optional_onnx_deps_produce_warnings_not_failure(monkeypatch):
    """onnxslim / onnxruntime 缺席只降級，不該讓 ONNX 變成不可用。"""
    _patch(monkeypatch, system="Windows", machine="AMD64", present={"onnx"})
    onnx = _by_format(caps.get_capabilities())["onnx"]
    assert onnx["available"] is True
    assert len(onnx["warnings"]) == 2
    assert any("onnxslim" in w for w in onnx["warnings"])
    assert any("onnxruntime" in w for w in onnx["warnings"])


def test_unknown_format_is_unavailable():
    available, reason = caps.is_format_available("coreml")
    assert available is False
    assert "coreml" in reason


# --- 逐 session 閘 ----------------------------------------------------------

@pytest.mark.parametrize("session,expected_ok,expect_in_reason", [
    ({"model_arch": "yolo", "weights_path": "/x/best.pt", "format_label": "PyTorch"}, True, None),
    # SSDLite 在磁碟上是 .pt（zip_handler 會改名），必須靠 model_arch 擋下來
    ({"model_arch": "ssdlite_mobilenet_v3_large", "weights_path": "/x/m.pt",
      "format_label": "SSDLite-MobileNetV3 (PyTorch)"}, False, "YOLO"),
    ({"model_arch": "ssdlite_mobilenet_v3_small", "weights_path": "/x/m.pt",
      "format_label": "SSDLite-MobileNetV3 (PyTorch)"}, False, "YOLO"),
    # 已匯出的格式不能再匯出
    ({"model_arch": "yolo", "weights_path": "/x/m.onnx", "format_label": "ONNX"}, False, "ONNX"),
    ({"model_arch": "yolo", "weights_path": "/x/m.tflite", "format_label": "TFLite"}, False, "TFLite"),
    # model_arch 未指定時預設為 yolo
    ({"weights_path": "/x/best.pt"}, True, None),
])
def test_session_export_gate(session, expected_ok, expect_in_reason):
    ok, reason = caps.session_export_gate(session)
    assert ok is expected_ok
    if expect_in_reason:
        assert expect_in_reason in reason
    else:
        assert reason is None


def test_ssdlite_gate_is_by_arch_not_extension():
    """
    這一條是整組測試的鎖：SSDLite 的權重檔在磁碟上副檔名是 .pt
    （zip_handler.index_single_weight 會把 .pth 改名），所以任何依副檔名判斷的
    實作都會漏掉它。
    """
    session = {"model_arch": "ssdlite_mobilenet_v3_large", "weights_path": "/runs/weights/model.pt"}
    ok, reason = caps.session_export_gate(session)
    assert ok is False
    assert "YOLO" in reason
