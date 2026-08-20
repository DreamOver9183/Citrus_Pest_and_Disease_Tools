"""
資料集「真實目錄」的唯讀讀取層——dataset_zip 的目錄對應版本。

dataset_zip 的模組註解說明了為何分析不需要解壓縮：所需資訊只有檔名清單與少量
文字檔。真實目錄天生就滿足這個前提（檔案本來就在磁碟上），所以這裡做的事更單純：
用 os.scandir() 走出一棵與 build_virtual_tree() 結構完全相同的 VirtualTree，
再提供帶上限的單檔讀取。

如此一來 dataset_detector 與 dataset_analyzer 的解析邏輯完全不必知道來源是壓縮檔
還是目錄——它們只透過 reader 介面取得位元組。

本模組**只讀不寫**：絕不建立、修改或刪除 root_path 底下的任何檔案。
"""
import os
from typing import NamedTuple, Optional

from app.core.config import (
    MAX_DATASET_MEMBERS,
    MAX_DATASET_UNCOMPRESSED_GB,
)
from app.utils.dataset_zip import (
    TEXT_MEMBER_CAP_BYTES,
    VirtualTree,
    is_noise_member,
)
from app.utils.zip_handler import ZipIndexError


class _DirEntryStat(NamedTuple):
    """
    VirtualTree.member_by_path 的值。

    **必須是有 .file_size 的真實物件，不能用 None 佔位。** dataset_analyzer 在
    _analyze_yolo 與 _analyze_voc 內會做：

        info = tree.member_by_path.get(member_path)
        if info is not None and not budget.try_spend(info.file_size):
            result["truncated"] = True

    若這裡塞 None，那個 `is not None` 前置條件會讓整個 TextBudget 截斷保護悄悄
    失效——不會報錯，只是永遠不截斷。zipfile.ZipInfo 剛好也有 .file_size，
    兩種來源因此共用同一組消費端程式碼。
    """
    file_size: int


def build_virtual_tree_from_dir(root_path: str) -> VirtualTree:
    """
    遞迴走訪 root_path，建出與 build_virtual_tree() 結構相同的 VirtualTree。

    用 os.scandir() 而非 os.walk()：DirEntry.stat() 在多數平台上會沿用走訪時已取得
    的中繼資料，資料集動輒上萬張影像時可省下大量 stat() 系統呼叫。

    上限檢查在走訪過程中就地進行——目錄沒有 ZIP 中央目錄那種「可以事先廉價總覽」
    的結構，所以改為邊走邊累計，超限立即中止，不必先走完整棵樹才發現太大。

    follow_symlinks=False 只用於「是否遞迴進入」的判斷，避免符號連結造成無窮遞迴
    或走出 root_path 之外。
    """
    tree = VirtualTree()
    root_path = os.path.abspath(root_path)
    file_count = 0

    def _walk(abs_dir: str, rel_dir: str) -> None:
        nonlocal file_count
        try:
            entries = list(os.scandir(abs_dir))
        except OSError:
            # 權限不足或路徑消失：略過該子樹，不讓整次掃描失敗
            return

        for entry in entries:
            rel_path = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
            if is_noise_member(rel_path):
                continue

            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue

            if is_dir:
                _walk(entry.path, rel_path)
                continue

            try:
                size = entry.stat().st_size
            except OSError:
                continue

            file_count += 1
            if file_count > MAX_DATASET_MEMBERS:
                raise ZipIndexError(
                    f"資料夾內檔案數量過多（超過 {MAX_DATASET_MEMBERS}），請縮小掃描範圍"
                )

            tree.total_uncompressed += size
            if tree.total_uncompressed > MAX_DATASET_UNCOMPRESSED_GB * 1024 ** 3:
                raise ZipIndexError(
                    f"資料夾總大小過大（超過 {MAX_DATASET_UNCOMPRESSED_GB} GB），請縮小掃描範圍"
                )

            tree.add_file(rel_path, _DirEntryStat(file_size=size))

    _walk(root_path, "")
    return tree


class DirArchiveReader:
    """
    真實目錄來源的 reader adapter，與 ZipArchiveReader 介面對稱。

    錯誤一律轉成 ZipIndexError：這個型別名稱對目錄來源而言語意不太貼切，但改名
    會牽動所有既有 ZIP 呼叫點與測試，效益不值得；此處統一沿用，讓上層的錯誤處理
    維持單一路徑。
    """

    def __init__(self, root_path: str):
        self.root_path = os.path.abspath(root_path)

    def build_tree(self) -> VirtualTree:
        if not os.path.isdir(self.root_path):
            raise ZipIndexError(f"找不到資料夾: {self.root_path}")
        return build_virtual_tree_from_dir(self.root_path)

    def read(self, path: str, cap: int = TEXT_MEMBER_CAP_BYTES) -> bytes:
        full_path = os.path.join(self.root_path, path.replace("/", os.sep))
        try:
            with open(full_path, "rb") as handle:
                data = handle.read(cap + 1)
        except FileNotFoundError as exc:
            raise ZipIndexError(f"資料夾內找不到檔案: {path}") from exc
        except OSError as exc:
            raise ZipIndexError(f"讀取檔案失敗: {path}（{exc}）") from exc

        if len(data) > cap:
            raise ZipIndexError(
                f"單一檔案過大: {path}（上限 {cap // 1024 // 1024} MB）"
            )
        return data
