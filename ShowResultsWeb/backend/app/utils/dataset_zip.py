"""
資料集 ZIP 的安全讀取層。

與 zip_handler 的差異：這裡**完全不解壓縮**。資料集動輒數 GB，但分析所需的
資訊只有兩種來源——檔名清單（來自中央目錄）與少量文字檔（data.yaml、
labels/*.txt、COCO json、VOC xml）。因此本模組只提供：

  1. build_virtual_tree() — 從 infolist() 建出虛擬目錄樹，等同於對壓縮檔做 os.walk
  2. enforce_archive_limits() — 大小/數量上限，擋下壓縮炸彈
  3. read_member_capped() — 帶硬上限的單一成員讀取

路徑穿越防禦沿用 zip_handler.is_member_within，錯誤型別沿用 ZipIndexError，
兩者都維持單一真相來源。
"""
import json
import posixpath
import zipfile
from typing import Dict, List, Optional, Set, Tuple

from app.core.config import (
    MAX_DATASET_MEMBERS,
    MAX_DATASET_UNCOMPRESSED_GB,
    MAX_DATASET_ZIP_MB,
)
from app.utils.zip_handler import ZipIndexError, is_member_within

# 讀取單一成員時的硬上限
TEXT_MEMBER_CAP_BYTES = 4 * 1024 * 1024        # data.yaml / *.txt / *.xml
JSON_MEMBER_CAP_BYTES = 64 * 1024 * 1024       # COCO instances_*.json

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def _is_noise_member(name: str) -> bool:
    """macOS 壓縮工具產生的資源分叉與系統檔，計入統計會灌水，一律忽略。"""
    parts = name.split("/")
    if any(p == "__MACOSX" for p in parts):
        return True
    base = parts[-1]
    return base.startswith("._") or base == ".DS_Store"


def normalize_member_name(name: str) -> str:
    """
    正規化 ZIP 成員路徑。

    ZIP 規範要求用正斜線，但部分 Windows 壓縮工具會寫入反斜線，而 zipfile
    不會代為正規化。若不處理，純字串建樹會把 "ds\\train\\a.png" 當成單一扁平檔名。
    """
    return name.replace("\\", "/").lstrip("/")


def enforce_archive_limits(zip_ref: zipfile.ZipFile, zip_size_bytes: Optional[int] = None) -> None:
    """在做任何解析前擋下過大或成員過多的壓縮檔。"""
    if zip_size_bytes is not None and zip_size_bytes > MAX_DATASET_ZIP_MB * 1024 * 1024:
        raise ZipIndexError(
            f"ZIP 檔案過大（{zip_size_bytes / 1024 / 1024:.0f} MB），"
            f"系統上限為 {MAX_DATASET_ZIP_MB} MB"
        )

    infos = zip_ref.infolist()
    if len(infos) > MAX_DATASET_MEMBERS:
        raise ZipIndexError(
            f"ZIP 內檔案數量過多（{len(infos)}），系統上限為 {MAX_DATASET_MEMBERS}"
        )

    total_uncompressed = sum(info.file_size for info in infos)
    if total_uncompressed > MAX_DATASET_UNCOMPRESSED_GB * 1024 ** 3:
        raise ZipIndexError(
            f"ZIP 解壓後總大小過大（{total_uncompressed / 1024 ** 3:.1f} GB），"
            f"系統上限為 {MAX_DATASET_UNCOMPRESSED_GB} GB"
        )


class VirtualTree:
    """
    ZIP 內容的唯讀目錄檢視。

    dirs[dirpath] = (子目錄名集合, 檔名集合)，dirpath 用 POSIX 形式，根目錄為 ""。
    這讓「某目錄下同時有 images/ 與 labels/」這類 marker 比對可以直接查表，
    與 zip_handler 用 os.walk 找 weights/args.yaml 是同一種手法。
    """

    def __init__(self) -> None:
        self.dirs: Dict[str, Tuple[Set[str], Set[str]]] = {}
        self.member_by_path: Dict[str, zipfile.ZipInfo] = {}
        self.total_uncompressed: int = 0

    def _ensure_dir(self, dirpath: str) -> Tuple[Set[str], Set[str]]:
        if dirpath not in self.dirs:
            self.dirs[dirpath] = (set(), set())
        return self.dirs[dirpath]

    def add_file(self, path: str, info: zipfile.ZipInfo) -> None:
        dirpath, filename = posixpath.split(path)
        _, files = self._ensure_dir(dirpath)
        files.add(filename)
        self.member_by_path[path] = info

        # 逐層向上補齊父目錄，讓中間層即使沒有直屬檔案也存在於樹中
        current = dirpath
        while current:
            parent, name = posixpath.split(current)
            child_dirs, _ = self._ensure_dir(parent)
            child_dirs.add(name)
            current = parent

    def files_in(self, dirpath: str) -> Set[str]:
        return self.dirs.get(dirpath, (set(), set()))[1]

    def subdirs_in(self, dirpath: str) -> Set[str]:
        return self.dirs.get(dirpath, (set(), set()))[0]

    def has_dir(self, dirpath: str) -> bool:
        return dirpath in self.dirs

    def join(self, dirpath: str, name: str) -> str:
        return posixpath.join(dirpath, name) if dirpath else name

    def list_images(self, dirpath: str) -> List[str]:
        return [
            f for f in self.files_in(dirpath)
            if posixpath.splitext(f)[1].lower() in IMAGE_EXTENSIONS
        ]

    def list_labels(self, dirpath: str) -> List[str]:
        return [
            f for f in self.files_in(dirpath)
            if f.lower().endswith(".txt") and f.lower() != "classes.txt"
        ]


def build_virtual_tree(zip_ref: zipfile.ZipFile) -> VirtualTree:
    """從中央目錄建出虛擬樹。不讀取也不解壓任何檔案內容。"""
    tree = VirtualTree()
    for info in zip_ref.infolist():
        if info.is_dir():
            continue
        name = normalize_member_name(info.filename)
        if not name or _is_noise_member(name):
            continue
        # 用固定的假 base 做穿越檢查：真正要擋的是 "../" 與絕對路徑
        if not is_member_within("/__dataset_root__", name):
            raise ZipIndexError(f"ZIP 檔包含不安全路徑: {info.filename}")
        tree.add_file(name, info)
        tree.total_uncompressed += info.file_size
    return tree


def read_member_capped(zip_ref: zipfile.ZipFile, path: str, cap: int = TEXT_MEMBER_CAP_BYTES) -> bytes:
    """
    讀取單一成員，超過 cap 即拒絕。

    這裡量的是**實際解壓出的位元組數**（多讀 1 byte 判斷是否超限），而不是信任
    中央目錄宣告的 file_size；偽造 file_size 的壓縮炸彈會在這裡被擋下。
    """
    try:
        with zip_ref.open(path) as handle:
            data = handle.read(cap + 1)
    except KeyError as exc:
        raise ZipIndexError(f"ZIP 內找不到檔案: {path}") from exc
    except zipfile.BadZipFile as exc:
        raise ZipIndexError(f"ZIP 內檔案損毀: {path}") from exc

    if len(data) > cap:
        raise ZipIndexError(
            f"ZIP 內單一檔案過大: {path}（上限 {cap // 1024 // 1024} MB）"
        )
    return data


def decode_text(data: bytes) -> str:
    """
    一律用 utf-8-sig 解碼。

    BOM 很重要：帶 BOM 的 data.yaml 會讓 yaml.safe_load 產生 "﻿train" 這個 key，
    使 train 靜默變成 None，最終呈現為「0 張圖片」這種難以追查的錯誤。
    """
    return data.decode("utf-8-sig", errors="replace")


def peek_json_object(zip_ref: zipfile.ZipFile, path: str) -> Optional[dict]:
    """嘗試把成員解析為 JSON 物件；失敗回 None（供 COCO 偵測使用）。"""
    try:
        data = read_member_capped(zip_ref, path, JSON_MEMBER_CAP_BYTES)
        parsed = json.loads(decode_text(data))
    except (ZipIndexError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


class TextBudget:
    """
    分析期間累計可讀取的文字量。

    超出預算不會讓整個分析失敗，而是停止讀取並標記 truncated——對超大資料集
    仍然給得出「大致正確」的統計，比直接報錯有用。
    """

    def __init__(self, limit_bytes: int):
        self.limit = limit_bytes
        self.used = 0
        self.exhausted = False

    def try_spend(self, nbytes: int) -> bool:
        if self.used + nbytes > self.limit:
            self.exhausted = True
            return False
        self.used += nbytes
        return True
