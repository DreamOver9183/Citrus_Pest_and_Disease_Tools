"""Application package init for backend.app

這裡設定 ultralytics 的環境變數，位置是刻意選的、不能搬。

`AUTOINSTALL` 與 `ONLINE` 在 ultralytics/utils/__init__.py 是**模組級常數**，
在 `import ultralytics` 當下就凍結。而 model_service.py 第 6 行是
`from ultralytics import YOLO`、第 10 行才是 `from app.core.config import ...`
——放進 config.py 已經太晚。

package 的 __init__ 保證先於任何 submodule 執行，所以只要有人 import
app.* 底下任何東西（包含裸跑 pytest）都會先經過這裡。

為何要關掉：
- YOLO_AUTOINSTALL=0 —— 預設是 True，`model.export()` 會在缺套件時於請求執行緒中
  直接跑 `pip install`。在離線環境會卡住、在唯讀容器會失敗，而且使用者只會看到
  匯出「卡住好幾分鐘」。相依套件一律由 requirements 明確安裝。
- YOLO_OFFLINE=1 —— 額外擋掉 `assert ONLINE` 與 attempt_download_asset 的對外連線。

用 setdefault 而非直接指派，讓維運仍可從 shell 覆寫。
"""
import os

os.environ.setdefault("YOLO_AUTOINSTALL", "0")
os.environ.setdefault("YOLO_OFFLINE", "1")
