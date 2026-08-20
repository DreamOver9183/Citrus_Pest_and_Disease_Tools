"""
匯出能力探測。

回答兩個不同的問題，而且刻意分開回答：

  1. 這台機器能不能做這種格式的匯出？（平台閘 + 相依閘）
  2. 這個 session 的權重能不能匯出？（架構閘）

分開的理由是訊息品質：使用者看到「TFLite 不可用」時，該知道是「此平台不支援，
請用 Docker」還是「套件沒裝」——這兩者的下一步動作完全不同。

探測一律用 importlib.util.find_spec()，**絕不 import**。真的 import litert 或
tensorflow 要數秒與數百 MB RSS，而這個函式每次前端掛載 SystemSpecs 都會被呼叫。
"""
import importlib.util
import platform
from typing import Any, Dict, List, Optional, Tuple

# 格式定義。required 缺任一即不可用；degraded 缺了仍可匯出，但要提示副作用。
_FORMAT_SPECS = {
    "onnx": {
        "label": "ONNX",
        "suffix": ".onnx",
        "description": "跨框架通用格式，可用於 ONNX Runtime、TensorRT、OpenVINO 等推論引擎",
        "required": ["onnx"],
        "degraded": {
            "onnxslim": "onnxslim 未安裝，將略過 ONNX 圖形簡化（不影響正確性，檔案略大）",
            "onnxruntime": "onnxruntime 未安裝，匯出的 .onnx 無法在本平台直接推論",
        },
        "os_gate": False,
    },
    "litert": {
        "label": "TFLite (LiteRT)",
        "suffix": ".tflite",
        "description": "Google LiteRT 行動端格式，由 PyTorch 直接轉換，產出單一 .tflite 檔",
        "required": ["litert_torch", "ai_edge_litert"],
        "degraded": {},
        "os_gate": True,
    },
}


def _find_spec(module_name: str) -> bool:
    """模組是否可被 import（不實際載入）。獨立成函式是為了讓測試能 monkeypatch。"""
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        # find_spec 對某些損壞的套件會拋 ImportError，視同不存在
        return False


def _platform_flags() -> Tuple[bool, bool, bool]:
    """
    回傳 (is_macos, is_linux, is_arm64)。

    刻意自己判斷而不 import ultralytics.utils —— 那會把整個 ultralytics 拉進來，
    而這個模組要能在極輕量的情境（例如純能力查詢）下被使用。判斷邏輯與
    ultralytics/utils/__init__.py 的 MACOS/LINUX/ARM64 一致。
    """
    system = platform.system()
    machine = platform.machine().lower()
    is_arm64 = machine in {"arm64", "aarch64"}
    return system == "Darwin", system == "Linux", is_arm64


def _os_gate_reason() -> Optional[str]:
    """
    LiteRT 的平台限制。

    複製 ultralytics/engine/exporter.py 的 export_litert 首行斷言：
        assert MACOS or (LINUX and not ARM64)
    複製而非「呼叫後捕捉」，是因為要在使用者按下按鈕**之前**就給出原因。
    """
    is_macos, is_linux, is_arm64 = _platform_flags()
    if is_macos or (is_linux and not is_arm64):
        return None
    current = f"{platform.system()} {platform.machine()}"
    return (
        f"TFLite (LiteRT) 匯出僅支援 Linux x86 與 macOS，目前環境為 {current}。"
        "請改用 Docker 容器執行匯出。"
    )


def _probe_format(fmt: str) -> Dict[str, Any]:
    spec = _FORMAT_SPECS[fmt]
    warnings: List[str] = []

    # 先報平台閘：平台不支援時，缺不缺套件已無意義
    if spec["os_gate"]:
        reason = _os_gate_reason()
        if reason:
            return {
                "format": fmt,
                "label": spec["label"],
                "suffix": spec["suffix"],
                "description": spec["description"],
                "available": False,
                "reason": reason,
                "reason_kind": "platform",
                "missing": [],
                "warnings": [],
            }

    missing = [m for m in spec["required"] if not _find_spec(m)]
    if missing:
        return {
            "format": fmt,
            "label": spec["label"],
            "suffix": spec["suffix"],
            "description": spec["description"],
            "available": False,
            "reason": f"缺少匯出相依套件：{'、'.join(missing)}。",
            "reason_kind": "dependency",
            "missing": missing,
            "warnings": [],
        }

    for module_name, message in spec["degraded"].items():
        if not _find_spec(module_name):
            warnings.append(message)

    return {
        "format": fmt,
        "label": spec["label"],
        "suffix": spec["suffix"],
        "description": spec["description"],
        "available": True,
        "reason": None,
        "reason_kind": None,
        "missing": [],
        "warnings": warnings,
    }


_CACHE: Optional[Dict[str, Any]] = None


def get_capabilities() -> Dict[str, Any]:
    """
    回傳所有格式的可用性。

    結果 memoize：關掉 YOLO_AUTOINSTALL 之後，執行期不會再有套件被裝上來，
    因此能力在行程生命週期內是固定的。
    """
    global _CACHE
    if _CACHE is None:
        formats = [_probe_format(f) for f in _FORMAT_SPECS]
        _CACHE = {
            "formats": formats,
            "any_available": any(f["available"] for f in formats),
        }
    return _CACHE


def refresh() -> None:
    """清掉快取（測試用）。"""
    global _CACHE
    _CACHE = None


def is_format_available(fmt: str) -> Tuple[bool, Optional[str]]:
    """單一格式的可用性與原因。未知格式視為不可用。"""
    if fmt not in _FORMAT_SPECS:
        return False, f"不支援的匯出格式：{fmt}"
    for info in get_capabilities()["formats"]:
        if info["format"] == fmt:
            return info["available"], info["reason"]
    return False, f"不支援的匯出格式：{fmt}"


def format_suffix(fmt: str) -> str:
    return _FORMAT_SPECS.get(fmt, {}).get("suffix", ".bin")


def session_export_gate(session: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    這個 session 的權重能不能匯出。

    **依 model_arch 判斷，絕不依副檔名**：zip_handler.index_single_weight 會把上傳的
    .pth 改名成 .pt（Ultralytics 只吃 .pt），所以磁碟上是 .pt 完全不代表它是 YOLO。
    """
    model_arch = (session.get("model_arch") or "yolo").lower()
    if model_arch != "yolo":
        return False, (
            f"僅支援 YOLO 架構的權重匯出，此模型為 {session.get('format_label') or model_arch}。"
        )

    weights_path = session.get("weights_path") or ""
    suffix = weights_path.rsplit(".", 1)[-1].lower() if "." in weights_path else ""
    if suffix != "pt":
        label = session.get("format_label") or suffix.upper() or "未知"
        return False, f"此 Session 已是 {label} 格式，無法再次匯出。"

    return True, None
