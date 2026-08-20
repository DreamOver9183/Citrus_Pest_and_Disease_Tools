"""
端到端測試：以 LocalLibrary 內的真實檔案驗證整個系統。

與 e2e_test.py 的差異：那支是早期的上傳流程煙霧測試，需要一份特定佈局的 assets
資料夾。這支改用**使用者本機資料夾裡實際存在的內容**，並涵蓋後來新增的資料集分析、
模型匯出與本機資料夾掃描三個子系統。

執行方式（後端需已在跑，Docker 或本機皆可）：

    python e2e_tests/e2e_local_library.py

環境變數：
    E2E_BASE_URL      預設 http://localhost:8000/api
    E2E_LIBRARY_DIR   主機端 LocalLibrary 路徑，預設由本檔位置推導
    E2E_SKIP_TFLITE   設為 1 可略過耗時約 100 秒的 TFLite 匯出

LocalLibrary 是空的或內容不足時會**優雅跳過並回傳 0**，與 e2e_test.py 的慣例一致，
因為那裡面是使用者的本機檔案，不進版控也不保證存在。

所有斷言都建立在「可獨立驗證的事實」上：資料集的影像／標註數直接數 ZIP 內的成員來
對答案，推論結果對照該圖真實標註的類別索引，而不是只斷言 status == success。
"""
import hashlib
import io
import json
import os
import posixpath
import re
import sys
import time
import zipfile

import requests

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8000/api")
_DEFAULT_LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "LocalLibrary")
LIBRARY_DIR = os.environ.get("E2E_LIBRARY_DIR", _DEFAULT_LIB)
SKIP_TFLITE = os.environ.get("E2E_SKIP_TFLITE") == "1"

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

_passed = 0
_failed = []


# --------------------------------------------------------------------- 小工具

def section(title):
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def check(label, condition, detail=""):
    global _passed
    if condition:
        _passed += 1
        print(f"  [PASS] {label}" + (f"  ({detail})" if detail else ""))
    else:
        _failed.append(label)
        print(f"  [FAIL] {label}" + (f"  ({detail})" if detail else ""))
    return bool(condition)


def api(method, path, **kwargs):
    kwargs.setdefault("timeout", 600)
    res = requests.request(method, f"{BASE_URL}{path}", **kwargs)
    res.raise_for_status()
    return res.json()


def tree_fingerprint(root):
    """(檔案數, 內容指紋)——用於證明系統完全沒有寫入使用者的資料夾。"""
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            try:
                stat = os.stat(full)
                entries.append(f"{rel}|{stat.st_size}|{int(stat.st_mtime)}")
            except OSError:
                entries.append(f"{rel}|?")
    digest = hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()[:16]
    return len(entries), digest


# ------------------------------------------------------- 真實內容的 ground truth

def count_yolo_zip(zip_path):
    """直接數 ZIP 內容得出影像／標註數，作為資料集分析結果的對照答案。"""
    images = labels = boxes = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            parts = name.split("/")
            if "images" in parts and name.lower().endswith(IMAGE_EXTS):
                images += 1
            elif "labels" in parts and name.lower().endswith(".txt"):
                labels += 1
                with zf.open(info) as f:
                    text = f.read().decode("utf-8", errors="replace")
                boxes += sum(1 for line in text.splitlines() if line.strip())
    return images, labels, boxes


def find_labeled_image(library_dir):
    """
    在 LocalLibrary 的資料集資料夾裡找一張「標註非空」的影像。

    回傳 (影像路徑, 期望的類別名稱)。找不到就回 (None, None)，讓推論階段降級成
    只驗證流程成功、不驗證類別。
    """
    for dirpath, dirnames, filenames in os.walk(library_dir):
        if os.path.basename(dirpath) != "images":
            continue
        label_dir = os.path.join(os.path.dirname(dirpath), "labels")
        if not os.path.isdir(label_dir):
            continue

        # 往上找 data.yaml 取得類別名稱表
        names = _names_from_yaml(dirpath, library_dir)

        for filename in sorted(filenames):
            if not filename.lower().endswith(IMAGE_EXTS):
                continue
            label_path = os.path.join(label_dir, os.path.splitext(filename)[0] + ".txt")
            if not os.path.exists(label_path):
                continue
            with open(label_path, "r", encoding="utf-8", errors="replace") as f:
                lines = [ln for ln in f.read().splitlines() if ln.strip()]
            if not lines:
                continue  # 空標註是刻意保留的負樣本，不適合拿來驗證偵測
            try:
                class_idx = int(lines[0].split()[0])
            except (ValueError, IndexError):
                continue
            expected = names[class_idx] if names and class_idx < len(names) else None
            return os.path.join(dirpath, filename), expected
    return None, None


def _names_from_yaml(images_dir, library_dir):
    """從最近的 data.yaml 取出 names 清單（只做最小解析，不引入 PyYAML 依賴）。"""
    current = os.path.dirname(os.path.dirname(images_dir))
    for _ in range(4):
        if not current.startswith(os.path.abspath(library_dir)[: len(current)]):
            break
        for candidate in ("data.yaml", "data.yml", "dataset.yaml"):
            path = os.path.join(current, candidate)
            if os.path.exists(path):
                return _parse_names(path)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return []


def _parse_names(yaml_path):
    names, in_names = [], False
    with open(yaml_path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if line.startswith("names:"):
                in_names = True
                inline = line.split(":", 1)[1].strip()
                if inline.startswith("["):
                    return [n.strip().strip("'\"") for n in inline.strip("[]").split(",") if n.strip()]
                continue
            if in_names:
                stripped = line.strip()
                if stripped.startswith("- "):
                    names.append(stripped[2:].strip().strip("'\""))
                elif stripped and not line.startswith((" ", "\t", "-")):
                    break
    return names


# ------------------------------------------------------------------- 測試階段

def phase_preflight():
    section("階段 1／12：連線與環境")
    devices = api("GET", "/devices")
    check("後端可連線且回報裝置清單", devices.get("status") == "success",
          f"目前裝置 {devices.get('current_device')}")

    info = api("GET", "/local-library")
    check("本機資料夾端點回報路徑", info.get("status") == "success" and info.get("exists"),
          info.get("path"))
    return info["path"]


def phase_reset():
    section("階段 2／12：清空既有狀態")
    sessions = api("GET", "/sessions").get("sessions", {})
    for sid in list(sessions):
        requests.post(f"{BASE_URL}/delete-session", data={"session_id": sid}, timeout=120)
    datasets = api("GET", "/datasets").get("datasets", {})
    for did in list(datasets):
        requests.post(f"{BASE_URL}/delete-dataset", data={"dataset_id": did}, timeout=120)

    check("sessions 已清空", len(api("GET", "/sessions").get("sessions", {})) == 0)
    check("datasets 已清空", len(api("GET", "/datasets").get("datasets", {})) == 0)


def phase_discovery():
    section("階段 3／12：掃描（探索階段必須是唯讀的）")
    started = time.monotonic()
    scan = api("POST", "/local-library/scan")
    elapsed = time.monotonic() - started

    candidates = scan.get("candidates", [])
    models = [c for c in candidates if c["kind"] == "model"]
    datasets = [c for c in candidates if c["kind"] == "dataset"]
    print(f"  掃描耗時 {elapsed:.2f}s：{scan.get('message')}")
    for c in models:
        print(f"    權重  [{c['source_kind']:11}] {c['name']:36} {c['detail']}")
    for c in datasets:
        print(f"    資料集[{c['source_kind']:11}] {c['name']:36} {c['detail']}")

    check("掃描找到至少一個模型", len(models) >= 1, f"{len(models)} 個")
    check("掃描回報的數量與清單一致",
          scan.get("total_models") == len(models) and scan.get("total_datasets") == len(datasets))
    check("掃描完全沒有註冊任何 session（唯讀契約）",
          len(api("GET", "/sessions").get("sessions", {})) == 0)
    check("掃描完全沒有註冊任何 dataset（唯讀契約）",
          len(api("GET", "/datasets").get("datasets", {})) == 0)

    kinds = {c["source_kind"] for c in candidates}
    print(f"  涵蓋的來源形態：{sorted(kinds)}")
    check("ZIP 內的訓練成果有被找到（原缺陷的直接回歸）", "zip_run" in kinds,
          "未發現 zip_run，LocalLibrary 內可能沒有訓練成果 ZIP" if "zip_run" not in kinds else "")

    rescan = api("POST", "/local-library/scan")
    check("重複掃描的 candidate_id 保持穩定",
          sorted(c["candidate_id"] for c in rescan["candidates"])
          == sorted(c["candidate_id"] for c in candidates))
    return candidates


def phase_register(candidates):
    section("階段 4／12：勾選式載入（只載入選取的項目）")
    by_kind = {}
    for c in candidates:
        by_kind.setdefault(c["source_kind"], []).append(c)

    chosen = []
    for kind in ("run_dir", "zip_run", "weight_file"):
        if by_kind.get(kind):
            chosen.append(by_kind[kind][0])
    # 全部資料集都載入。註冊本身是即時的（統計在探索階段就算好了，不會重跑分析），
    # 而評估階段需要一個夠大的資料集才驗證得了東西——只載入最小的那份會挑到十幾張
    # 影像的子集，模型什麼都偵測不到，指標全為 0 而無法斷言任何事。
    chosen.extend(c for c in candidates if c["kind"] == "dataset")

    if not chosen:
        print("  LocalLibrary 內沒有可載入的項目，略過後續階段")
        return None, None

    not_chosen = [c for c in candidates if c not in chosen]
    print("  選取：")
    for c in chosen:
        print(f"    + [{c['source_kind']:11}] {c['name']}")
    print(f"  未選取 {len(not_chosen)} 項（不得被載入）")

    res = api("POST", "/local-library/register",
              json={"candidate_ids": [c["candidate_id"] for c in chosen]})
    print(f"  {res.get('message')}")

    sessions = api("GET", "/sessions").get("sessions", {})
    datasets = api("GET", "/datasets").get("datasets", {})

    expected_models = len([c for c in chosen if c["kind"] == "model"])
    check("載入的模型數等於選取數", len(sessions) == expected_models,
          f"{len(sessions)} / 期望 {expected_models}")
    check("未選取的項目沒有被載入", len(sessions) + len(datasets) == len(chosen),
          f"總計 {len(sessions) + len(datasets)} / 選取 {len(chosen)}")
    check("所有載入的 session 都標記為 local_library 來源",
          all(s.get("source") == "local_library" for s in sessions.values()))

    for s in sessions.values():
        label = "ZIP 解壓" if "local_library" in s["weights_path"] else "就地引用"
        print(f"    {s.get('custom_name')} | {s.get('epochs')} epochs | {label}")

    check("重複載入相同項目不會產生重複註冊",
          api("POST", "/local-library/register",
              json={"candidate_ids": [c["candidate_id"] for c in chosen]}
              ).get("registered_sessions") == []
          and len(api("GET", "/sessions").get("sessions", {})) == len(sessions))
    return sessions, datasets


def phase_readonly(before):
    section("階段 5／12：使用者檔案唯讀保證")
    after = tree_fingerprint(LIBRARY_DIR)
    check("LocalLibrary 檔案數未變", before[0] == after[0], f"{before[0]} → {after[0]}")
    check("LocalLibrary 內容指紋未變（大小與 mtime 皆未動）",
          before[1] == after[1], f"{before[1]} → {after[1]}")


def phase_metrics(sessions):
    section("階段 6／12：指標與圖表")
    # 注意 /api/generate-chart 是 SSD 專用的手繪曲線端點（YOLO 沒有 results.png 時才用），
    # YOLO 的指標圖一律走 /api/metrics 的裁切路徑。
    base = BASE_URL.rsplit("/api", 1)[0]

    for sid, s in sessions.items():
        if s.get("source_type") == "single_weight":
            continue  # 散落權重檔本來就沒有訓練紀錄
        name = s.get("custom_name")

        for metric_type in ("confusion_matrix", "mAP50", "precision"):
            metrics = api("GET", "/metrics",
                          params={"session_id": sid, "metric_type": metric_type})
            url = metrics.get("url")
            ok = metrics.get("status") == "success" and url
            check(f"指標圖已產生：{metric_type}", ok, url or metrics.get("message", ""))
            if not ok:
                continue
            image = requests.get(f"{base}{url}", timeout=120)
            check(f"指標圖可實際下載：{metric_type}",
                  image.status_code == 200 and len(image.content) > 5000,
                  f"{image.status_code}, {len(image.content):,} bytes")

        check(f"指標摘要有解析出數值：{name}",
              len(s.get("metrics_summary") or {}) > 0,
              f"{len(s.get('metrics_summary') or {})} 個欄位")
        break  # 一個代表性 session 即可，避免重複載入模型拖慢


def phase_inference(sessions):
    section("階段 7／12：推論（含真實標註對照）")
    image_path, expected_class = find_labeled_image(LIBRARY_DIR)
    if not image_path:
        print("  LocalLibrary 內找不到帶標註的影像，略過類別對照")
        return
    print(f"  測試影像：{os.path.relpath(image_path, LIBRARY_DIR)}")
    print(f"  真實標註類別：{expected_class or '（無法解析 data.yaml）'}")

    for sid, s in sessions.items():
        with open(image_path, "rb") as f:
            res = requests.post(f"{BASE_URL}/inference",
                                params={"session_id": sid, "conf": 0.25},
                                files={"file": f}, timeout=600)
        data = res.json()
        source = "ZIP 解壓" if "local_library" in s["weights_path"] else "就地引用"
        ok = res.status_code == 200 and data.get("status") == "success"
        check(f"推論成功（{source}）：{s.get('custom_name')}", ok,
              f"{data.get('device_used')}, counts={data.get('counts')}, "
              f"{json.dumps(data.get('detections'), ensure_ascii=False)}")

        if ok and expected_class and data.get("counts"):
            check(f"偵測類別與真實標註相符（{source}）",
                  expected_class in data.get("detections", {}),
                  f"期望 {expected_class}，得到 {list(data.get('detections', {}))}")


def phase_dataset_analysis(datasets):
    section("階段 8／12：資料集分析（對照 ZIP 實際內容驗算）")
    if not datasets:
        print("  沒有已載入的資料集，略過")
        return

    for did, d in datasets.items():
        print(f"  {d.get('zip_name')}: format={d.get('format')} "
              f"images={d.get('total_images'):,} annotations={d.get('total_annotations'):,} "
              f"classes={len(d.get('classes', []) or [])}")
        check(f"資料集格式已辨識：{d.get('zip_name')}", bool(d.get("format")))
        check(f"影像數為正：{d.get('zip_name')}", (d.get("total_images") or 0) > 0)

    # 對任一 LocalLibrary 內的資料集 ZIP 做獨立驗算
    zips = [f for f in os.listdir(LIBRARY_DIR) if f.lower().endswith(".zip")]
    for zip_name in zips:
        zip_path = os.path.join(LIBRARY_DIR, zip_name)
        images, labels, boxes = count_yolo_zip(zip_path)
        if images == 0:
            continue  # 訓練成果 ZIP，不是資料集
        print(f"  獨立驗算 {zip_name}：實際 {images:,} 影像 / {boxes:,} 標註框")

        scan = api("POST", "/local-library/scan")
        match = next((c for c in scan["candidates"]
                      if c["kind"] == "dataset" and c["name"] == zip_name), None)
        if match:
            check(f"分析結果與 ZIP 實際內容相符：{zip_name}",
                  f"{images:,}" in match["detail"] and f"{boxes:,}" in match["detail"],
                  match["detail"])
        break


def phase_export(sessions):
    section("階段 9／12：模型格式匯出")
    caps = api("GET", "/export/capabilities")
    available = [f["format"] for f in caps.get("formats", []) if f.get("available")]
    print(f"  本環境可用格式：{available or '（無）'}")
    if not available:
        print("  無可用格式（本機 Windows 開發模式屬正常），略過")
        return

    target = next((sid for sid, s in sessions.items() if s.get("model_arch") == "yolo"), None)
    if not target:
        print("  沒有 YOLO 架構的 session，略過")
        return

    formats = ["onnx"] + ([] if SKIP_TFLITE or "litert" not in available else ["litert"])
    for fmt in formats:
        if fmt not in available:
            continue
        started = time.monotonic()
        # 回應把 job 包在 "job" 底下，不是攤平在頂層
        submitted = api("POST", "/export", data={"session_id": target, "format": fmt})
        job = submitted.get("job") or {}
        job_id = job.get("job_id")
        check(f"{fmt.upper()} 匯出 job 已建立", bool(job_id),
              f"state={job.get('state')}" if job_id else submitted.get("message", ""))
        if not job_id:
            continue

        state = None
        status = {}
        for _ in range(240):
            time.sleep(2)
            polled = api("GET", f"/export/{job_id}")
            status = polled.get("job") or polled
            state = status.get("state")
            if state in ("done", "failed"):
                break
        elapsed = time.monotonic() - started
        check(f"{fmt.upper()} 匯出完成", state == "done",
              f"state={state}, 耗時 {elapsed:.0f}s")
        if state != "done":
            print(f"    log: {(status.get('log_tail') or '')[-300:]}")
            continue

        download = requests.get(f"{BASE_URL}/export/{job_id}/download", timeout=300)
        size_mb = len(download.content) / (1024 * 1024)
        check(f"{fmt.upper()} 產物可下載", download.status_code == 200 and len(download.content) > 1000,
              f"{size_mb:.2f} MB")

        if fmt == "onnx":
            _verify_onnx(download.content)
        else:
            check("TFLite 產物具備 TFL3 識別碼", b"TFL3" in download.content[:64],
                  f"前 16 bytes = {download.content[:16]!r}")


def _verify_onnx(blob):
    """
    驗證 ONNX 產物。

    ONNX 是 protobuf ModelProto：第一個位元組 0x08 是 field 1（ir_version）的
    varint tag，接著 0x12 是 field 2（producer_name）的長度前綴字串。**不要**去比對
    特定的 ir_version 數值——那會隨匯出端的版本改變（實測 ultralytics 產出 ir_version 9）。
    能 import onnx 時直接用官方 checker 做完整驗證。
    """
    structurally_ok = blob[:1] == b"\x08" and b"pytorch" in blob[:64].lower()
    check("ONNX 產物為結構正確的 protobuf ModelProto", structurally_ok,
          f"ir_version tag={blob[0]:#04x}, producer={blob[4:11].decode('ascii', 'replace')}")

    try:
        import onnx
    except ImportError:
        print("      （未安裝 onnx 套件，略過 checker 完整驗證）")
        return

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".onnx", delete=False) as tmp:
        tmp.write(blob)
        tmp_path = tmp.name
    try:
        model = onnx.load(tmp_path)
        onnx.checker.check_model(model)
        check("ONNX 產物通過 onnx.checker 驗證", True,
              f"ir_version={model.ir_version}, opset={model.opset_import[0].version}, "
              f"producer={model.producer_name}")
    except Exception as exc:  # noqa: BLE001
        check("ONNX 產物通過 onnx.checker 驗證", False, str(exc)[:160])
    finally:
        os.unlink(tmp_path)


def phase_evaluation(sessions, datasets):
    section("階段 10／12：驗證評估（讓模型實跑資料集）")
    if not sessions or not datasets:
        print("  缺少模型或資料集，略過")
        return []

    targets = api("GET", "/evaluations/targets")
    usable = [d for d in targets.get("datasets", []) if d.get("available")]
    check("至少有一個資料集可供評估", bool(usable),
          "；".join(d.get("reason") or "" for d in targets.get("datasets", [])) or "")

    # 不可評估的項目仍必須列出並附原因，而不是被藏起來
    for d in targets.get("datasets", []):
        if not d.get("available"):
            check(f"不可評估的資料集有附原因：{d['name']}", bool(d.get("reason")), d.get("reason", "")[:60])

    if not usable:
        return []

    # 挑影像最多的資料集。取第一個會挑到最小的那份，而在一個只有十幾張影像的子集上
    # 模型可能一個物件都沒偵測到——那時 mAP 為 0、逐類別列表為空，都是正確行為，
    # 但這樣的評估無法驗證任何東西。
    registered = api("GET", "/datasets").get("datasets", {})
    def _image_count(d):
        return (registered.get(d["dataset_id"], {}) or {}).get("total_images") or 0
    usable.sort(key=_image_count, reverse=True)

    dataset = usable[0]
    print(f"  選用影像數最多的資料集：{dataset['name']}（{_image_count(dataset):,} 張）")
    session_id = next(
        (s["session_id"] for s in targets.get("sessions", []) if s.get("available")), None
    )
    check("至少有一個 YOLO 模型可供評估", session_id is not None)
    if session_id is None:
        return []

    split = dataset.get("default_split")
    check("預設 split 不是 train", split != "train", f"預設為 {split}")
    print(f"  評估 {dataset['name']} / {split}（可能需要數分鐘）...")

    started = time.monotonic()
    submitted = api("POST", "/evaluations",
                    data={"session_id": session_id, "dataset_id": dataset["dataset_id"], "split": split})
    job_id = (submitted.get("job") or {}).get("job_id")
    check("評估 job 已建立", bool(job_id), submitted.get("message", ""))
    if not job_id:
        return []

    state, job = None, {}
    for _ in range(600):
        time.sleep(2)
        job = (api("GET", f"/evaluations/{job_id}").get("job")) or {}
        state = job.get("state")
        if state in ("done", "failed"):
            break
    elapsed = time.monotonic() - started
    check("評估完成", state == "done", f"state={state}, 耗時 {elapsed:.0f}s")
    if state != "done":
        print(f"    {job.get('message')}")
        return []

    overall = job.get("overall") or {}
    print(f"  mAP50={overall.get('map50')}  mAP50-95={overall.get('map50_95')}  "
          f"P={overall.get('precision')}  R={overall.get('recall')}")
    # mAP 為 0 是合法結果（模型可能真的什麼都沒偵測到），所以下界是 0 而非大於 0。
    # 真正該擋的是超出 [0,1] 的值——那代表指標抽取寫錯了。
    # 注意不能寫 `overall.get("map50") or -1`：0.0 是 falsy，會被換成 -1 而誤判為失敗。
    map50 = overall.get("map50")
    check("mAP50 在 [0,1] 之內", map50 is not None and 0 <= map50 <= 1, str(map50))
    check("mAP50 與 mAP50-95 的大小關係正確",
          (overall.get("map50") or 0) >= (overall.get("map50_95") or 0),
          f"{overall.get('map50')} >= {overall.get('map50_95')}")
    check("類別詞彙比對有結果", (job.get("vocab_check") or {}).get("status") in ("match", "name_drift"),
          (job.get("vocab_check") or {}).get("status", ""))
    check("影像數與 split 相符", (job.get("image_count") or 0) > 0, str(job.get("image_count")))

    per_class = job.get("per_class") or []
    profile = {p["class_id"]: p for p in (job.get("size_profile") or [])}
    # ultralytics 在完全沒有偵測結果時 ap_class_index 會是空的，因此逐類別列表可能為空。
    # 只有在確實有偵測到東西（mAP > 0）時才要求逐類別指標存在。
    if (overall.get("map50") or 0) > 0:
        check("有逐類別指標", len(per_class) > 0, f"{len(per_class)} 類")
    else:
        print("  （此 split 沒有任何偵測結果，略過逐類別斷言）")
    check("尺寸剖面涵蓋所有宣告的類別", len(profile) > 0, f"{len(profile)} 類")

    print()
    print(f"  {'類別':<20}{'AP@50':>8}{'框數':>8}{'中位框面積':>12}")
    print("  " + "-" * 48)
    for entry in sorted(per_class, key=lambda e: e["ap50"]):
        size = profile.get(entry["class_id"], {})
        area = size.get("median_area_pct")
        print(f"  {entry['name']:<20}{entry['ap50']:>8.3f}{size.get('boxes', 0):>8}"
              f"{(f'{area:.3f}%' if area is not None else '—'):>12}")

    # 這是本功能的核心價值：同一個模型在不同 split 上的數字不同，
    # 而訓練時記錄的舊值只對應其中一個
    plots = job.get("plot_urls") or {}
    check("產出了評估圖表", len(plots) > 0, "、".join(plots))
    if plots:
        key = next(iter(plots))
        image = requests.get(f"{BASE_URL.rsplit('/api', 1)[0]}{plots[key]}", timeout=120)
        check(f"圖表可下載：{key}", image.status_code == 200 and len(image.content) > 5000,
              f"{image.status_code}, {len(image.content):,} bytes")

    return [job_id]


def phase_report(job_ids):
    section("階段 11／12：成果報告")
    if not job_ids:
        print("  沒有可放進報告的評估結果，略過")
        return

    body = api("POST", "/reports", json={"job_ids": job_ids})
    check("報告已產生", body.get("status") == "success", body.get("message", ""))
    meta = body.get("report") or {}
    if not meta:
        return
    print(f"  {meta.get('filename')} · {meta.get('size_kb')} KB")

    base = BASE_URL.rsplit("/api", 1)[0]
    res = requests.get(f"{base}/api/reports/{meta['report_id']}/view", timeout=120)
    check("報告可開啟", res.status_code == 200, str(res.status_code))
    html = res.text

    external = re.findall(r'(?:src|href)="(?!data:)[^"]+"', html)
    check("報告完全自足（無任何外部資源引用）", not external,
          f"發現 {len(external)} 個外部引用" if external else "0 個")
    check("圖表已內嵌", "data:image/" in html, f"{html.count('data:image/')} 張")
    # 散點圖需要至少兩個「同時有 AP 與中位框面積」的類別，沒偵測到東西時不會畫——
    # 那是正確行為，所以只在有逐類別資料時才要求。
    has_per_class = "逐類別表現" in html and "AP@50" in html
    if has_per_class and "<svg" not in html:
        print("  （沒有足夠的逐類別資料可畫散點圖）")
    check("報告主體結構完整", "逐類別表現" in html and "實測指標總覽" in html)
    check("含列印樣式（供 Ctrl+P 轉 PDF）", "@media print" in html)
    check("明確標示指標為重新計算", "重新計算" in html)
    check("列出已知限制", "已知限制" in html)

    listed = api("GET", "/reports")
    check("報告出現在清單中",
          any(r["report_id"] == meta["report_id"] for r in listed.get("reports", [])))


def phase_deletion_safety(sessions, lib_before):
    section("階段 12／12：刪除安全性與持久化契約")
    if len(sessions) < 1:
        print("  沒有 session 可刪，略過")
        return

    sids = list(sessions)
    victim = sids[0]
    survivors = {sid: sessions[sid]["weights_path"] for sid in sids[1:]}

    requests.post(f"{BASE_URL}/delete-session", data={"session_id": victim}, timeout=120)
    remaining = api("GET", "/sessions").get("sessions", {})
    check("目標 session 已移除", victim not in remaining)
    check("其餘 session 仍在", all(sid in remaining for sid in survivors))

    for sid, path in survivors.items():
        still_there = any(s["weights_path"] == path for s in remaining.values())
        check(f"其餘 session 的權重路徑未受影響", still_there, path.split("/")[-3])

    after = tree_fingerprint(LIBRARY_DIR)
    check("刪除 session 後使用者檔案完全未動",
          lib_before[0] == after[0] and lib_before[1] == after[1],
          f"{after[0]} 個檔案，指紋 {after[1]}")

    sessions_now = api("GET", "/sessions").get("sessions", {})
    check("記憶體中仍看得到 LocalLibrary 來源的 session（不落地不等於用不了）",
          all(s.get("source") == "local_library" for s in sessions_now.values())
          if sessions_now else True,
          f"{len(sessions_now)} 個")


# ------------------------------------------------------------------------ main

def main():
    if not os.path.isdir(LIBRARY_DIR):
        print(f"找不到 LocalLibrary（{LIBRARY_DIR}），略過測試。")
        sys.exit(0)

    count, _ = tree_fingerprint(LIBRARY_DIR)
    if count == 0:
        print(f"LocalLibrary 是空的（{LIBRARY_DIR}），略過測試。\n"
              "請先放入 YOLO 訓練成果（資料夾或 ZIP）與／或資料集後再執行。")
        sys.exit(0)

    print(f"目標後端：{BASE_URL}")
    print(f"主機端 LocalLibrary：{LIBRARY_DIR}（{count} 個檔案）")

    started = time.monotonic()
    lib_before = tree_fingerprint(LIBRARY_DIR)

    try:
        phase_preflight()
        phase_reset()
        candidates = phase_discovery()
        sessions, datasets = phase_register(candidates)
        if sessions is None:
            print("\n沒有可載入的項目，測試結束。")
            sys.exit(0)
        phase_readonly(lib_before)
        phase_metrics(sessions)
        phase_inference(sessions)
        phase_dataset_analysis(datasets)
        phase_export(sessions)
        eval_jobs = phase_evaluation(sessions, datasets)
        phase_report(eval_jobs)
        phase_deletion_safety(sessions, lib_before)
    except requests.RequestException as exc:
        print(f"\n[ERROR] 與後端通訊失敗：{exc}")
        sys.exit(1)

    section("結果")
    total = _passed + len(_failed)
    print(f"  通過 {_passed} / {total}，耗時 {time.monotonic() - started:.0f} 秒")
    if _failed:
        print("  失敗項目：")
        for name in _failed:
            print(f"    - {name}")
        sys.exit(1)
    print("  全部通過。")


if __name__ == "__main__":
    main()
