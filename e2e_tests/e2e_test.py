"""End-to-end smoke test against a running backend instance.

Requires real model/dataset assets that are gitignored and machine-specific,
so this script is opt-in: set E2E_ASSETS_DIR to a directory that contains

    Model/YOLO26-large.zip
    SSD-MobilenetV3_Model_train/SSD-MobilenetV3-large_train/outputs/best_model.pth
    Datasets/Datasets_YOLO26.zip

If E2E_ASSETS_DIR is not set (or the files are missing), the script prints an
explanation and exits 0 rather than failing, so it is safe to reference from
CI without bundling multi-GB assets.
"""
import os
import time
import requests
import zipfile
import tempfile
import sys

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8000/api")
ASSETS_DIR = os.environ.get("E2E_ASSETS_DIR")

TEST_IMAGE_IN_ZIP = "Datasets_YOLO26/test/images/D_CK_0009.png"


def _resolve_asset_paths(assets_dir):
    return {
        "yolo_zip": os.path.join(assets_dir, "Model", "YOLO26-large.zip"),
        "ssd_pth": os.path.join(
            assets_dir,
            "SSD-MobilenetV3_Model_train",
            "SSD-MobilenetV3-large_train",
            "outputs",
            "best_model.pth",
        ),
        "dataset_zip": os.path.join(assets_dir, "Datasets", "Datasets_YOLO26.zip"),
    }


def wait_for_server():
    print("Waiting for server to start...")
    for _ in range(30):
        try:
            res = requests.get(f"{BASE_URL}/devices")
            if res.status_code == 200:
                print("Server is up!")
                return True
        except requests.ConnectionError:
            pass
        time.sleep(1)
    print("Server failed to start in time.")
    return False


def clear_sessions():
    res = requests.get(f"{BASE_URL}/sessions")
    if res.status_code == 200:
        sessions = res.json().get("sessions", {})
        for sid in sessions.keys():
            requests.post(f"{BASE_URL}/delete-session", data={"session_id": sid})
    print("Sessions cleared.")


def extract_test_image(dataset_zip, dest_dir):
    with zipfile.ZipFile(dataset_zip, "r") as z:
        z.extract(TEST_IMAGE_IN_ZIP, path=dest_dir)
    return os.path.join(dest_dir, TEST_IMAGE_IN_ZIP)


def test_yolo_flow(yolo_zip):
    print("\n--- Testing YOLO Flow ---")
    print(f"Uploading {yolo_zip}...")
    with open(yolo_zip, "rb") as f:
        res = requests.post(f"{BASE_URL}/upload-model", files={"file": f})
    assert res.status_code == 200, f"Upload failed: {res.text}"
    data = res.json()
    assert data["status"] == "success", f"Upload returned error: {data}"
    session_id = data["registered_sessions"][0]
    print(f"YOLO Model uploaded successfully. Session ID: {session_id}")
    return session_id


def test_ssd_flow(ssd_pth):
    print("\n--- Testing SSD Flow ---")
    print(f"Uploading {ssd_pth}...")
    with open(ssd_pth, "rb") as f:
        res = requests.post(f"{BASE_URL}/upload-model", files={"file": f})
    assert res.status_code == 200, f"Upload failed: {res.text}"
    data = res.json()
    assert data["status"] == "success", f"Upload returned error: {data}"
    session_id = data["registered_sessions"][0]
    print(f"SSD Model uploaded successfully. Session ID: {session_id}")
    return session_id


def run_inference(session_id, image_path):
    print(f"\n--- Running Inference for Session: {session_id} ---")
    with open(image_path, "rb") as f:
        res = requests.post(
            f"{BASE_URL}/inference",
            params={"session_id": session_id, "conf": 0.25},
            files={"file": f},
        )
    assert res.status_code == 200, f"Inference failed: {res.text}"
    data = res.json()
    assert data["status"] == "success", f"Inference error: {data}"

    counts = data.get("counts", 0)
    detections = data.get("detections", {})
    print(f"Inference successful! Counts: {counts}, Detections: {detections}")


def main():
    if not ASSETS_DIR:
        print(
            "E2E_ASSETS_DIR is not set. Skipping e2e test — this script needs real "
            "model/dataset assets (gitignored, machine-specific) to run.\n"
            "Set E2E_ASSETS_DIR to a directory containing Model/, Datasets/ and "
            "SSD-MobilenetV3_Model_train/ to run it locally."
        )
        sys.exit(0)

    paths = _resolve_asset_paths(ASSETS_DIR)
    missing = [p for p in paths.values() if not os.path.exists(p)]
    if missing:
        print("E2E_ASSETS_DIR is set but the following expected assets are missing:")
        for m in missing:
            print(f"  - {m}")
        print("Skipping e2e test.")
        sys.exit(0)

    if not wait_for_server():
        sys.exit(1)

    clear_sessions()

    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Extracting test image from {paths['dataset_zip']}...")
        img_path = extract_test_image(paths["dataset_zip"], temp_dir)
        print(f"Extracted to {img_path}")

        yolo_sid = test_yolo_flow(paths["yolo_zip"])
        run_inference(yolo_sid, img_path)

        ssd_sid = test_ssd_flow(paths["ssd_pth"])
        run_inference(ssd_sid, img_path)

    print("\nAll E2E tests completed successfully!")


if __name__ == "__main__":
    main()
