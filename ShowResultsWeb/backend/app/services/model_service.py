import gc
import os
import threading
import torch
import torch.nn as nn
from ultralytics import YOLO
from PIL import Image, ImageDraw, ImageFont
from torchvision.transforms import v2
from app.utils.device_probe import get_recommended_device, probe_all_devices
from app.core.config import TEMP_DIR

SSD_CLASS_NAMES = {
    1: "H_MC", 2: "H_PK", 3: "D_GS", 4: "D_MN", 5: "D_SM", 6: "D_CK",
    7: "P_AP", 8: "P_AP_LD", 9: "P_SI", 10: "P_TP", 11: "P_TP_LD", 12: "P_LM_LD"
}

def _build_ssd_large(num_classes=13):
    from torchvision.models.detection import ssdlite320_mobilenet_v3_large, SSDLite320_MobileNet_V3_Large_Weights
    from torchvision.models.detection.ssdlite import SSDLiteClassificationHead
    from functools import partial
    model = ssdlite320_mobilenet_v3_large(
        weights=SSDLite320_MobileNet_V3_Large_Weights.COCO_V1,
        num_classes=91, trainable_backbone_layers=0)
    ic = [list(list(conv_group.children())[0].children())[0].in_channels
          if not hasattr(list(conv_group.children())[0], 'in_channels')
          else list(conv_group.children())[0].in_channels
          for conv_group in model.head.classification_head.module_list]
    na = model.anchor_generator.num_anchors_per_location()
    nl = partial(nn.BatchNorm2d, eps=0.001, momentum=0.03)
    model.head.classification_head = SSDLiteClassificationHead(ic, na, num_classes, nl)
    return model

def _build_ssd_small(num_classes=13):
    import torchvision
    from torchvision.models.detection.ssdlite import _mobilenet_extractor, SSDLiteHead
    from torchvision.models.detection.ssd import SSD, DefaultBoxGenerator
    from torchvision.models.detection import _utils as det_utils
    from functools import partial
    norm_layer = partial(nn.BatchNorm2d, eps=0.001, momentum=0.03)
    backbone = torchvision.models.mobilenet_v3_small(
        weights=torchvision.models.MobileNet_V3_Small_Weights.DEFAULT, norm_layer=norm_layer)
    backbone = _mobilenet_extractor(backbone, 0, norm_layer)
    size = (320, 320)
    anchor_generator = DefaultBoxGenerator([[2, 3] for _ in range(6)], min_ratio=0.2, max_ratio=0.95)
    out_channels = det_utils.retrieve_out_channels(backbone, size)
    num_anchors = anchor_generator.num_anchors_per_location()
    model = SSD(backbone, anchor_generator, size, num_classes,
                head=SSDLiteHead(out_channels, num_anchors, num_classes, norm_layer),
                score_thresh=0.001, nms_thresh=0.55, detections_per_img=300,
                topk_candidates=300, image_mean=[0.5,0.5,0.5], image_std=[0.5,0.5,0.5])
    return model


class ModelManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ModelManager, cls).__new__(cls)
            cls._instance.current_model = None
            cls._instance.current_path = None
            cls._instance.current_device = "auto"
            cls._instance.model_arch = "yolo"
            cls._instance._lock = threading.Lock()
        return cls._instance

    def load_model(self, model_path: str, device: str = "auto", arch: str = "yolo"):
        with self._lock:
            target_device = device
            if target_device == "auto":
                target_device = get_recommended_device()

            # If path, device and arch haven't changed and model is loaded, return it
            if self.current_path == model_path and self.current_device == target_device and self.model_arch == arch and self.current_model is not None:
                return self.current_model

            # 執行記憶體回收
            if self.current_model is not None:
                del self.current_model
                self.current_model = None
            
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                
            if not model_path:
                return None

            print(f"[ModelManager] Loading model: {model_path} [arch: {arch}] on device: {target_device}")
            
            ultralytics_device = target_device
            if target_device.startswith("cuda:"):
                ultralytics_device = target_device.split(":")[1]

            try:
                if arch == "yolo":
                    model = YOLO(model_path)
                    model.to(ultralytics_device)
                elif arch == "ssdlite_mobilenet_v3_large":
                    model = _build_ssd_large(num_classes=13)
                    model.load_state_dict(torch.load(model_path, map_location=target_device, weights_only=True))
                    model.to(target_device)
                    model.eval()
                elif arch == "ssdlite_mobilenet_v3_small":
                    model = _build_ssd_small(num_classes=13)
                    model.load_state_dict(torch.load(model_path, map_location=target_device, weights_only=True))
                    model.to(target_device)
                    model.eval()
                else:
                    raise ValueError(f"Unknown architecture: {arch}")
            except Exception as e:
                print(f"[ModelManager] Failed to load model: {str(e)}")
                raise
                
            self.current_model = model
            self.current_path = model_path
            self.current_device = target_device
            self.model_arch = arch
            return self.current_model

    def predict(self, image_path, conf=0.25):
        with self._lock:
            if self.current_model is None:
                raise RuntimeError("No model is currently loaded.")
                
            if self.model_arch == "yolo":
                return self.current_model.predict(image_path, conf=conf, verbose=False)
            else:
                return self.predict_ssd(image_path, conf)

    def predict_ssd(self, image_path, conf=0.25):
        # Image Loading
        original_img = Image.open(image_path).convert("RGB")
        orig_w, orig_h = original_img.size
        
        # Preprocessing based on architecture
        if self.model_arch == "ssdlite_mobilenet_v3_large":
            transform = v2.Compose([
                v2.Resize((320, 320)),
                v2.ToImage(),
                v2.ToDtype(torch.float32, scale=True),
                v2.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
            ])
        else: # small
            transform = v2.Compose([
                v2.Resize((320, 320)),
                v2.ToImage(),
                v2.ToDtype(torch.float32, scale=True),
                v2.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5])
            ])
            
        tensor_img = transform(original_img).unsqueeze(0).to(self.current_device)
        
        # Inference
        with torch.no_grad():
            predictions = self.current_model(tensor_img)[0]
            
        boxes = predictions["boxes"].cpu().numpy()
        labels = predictions["labels"].cpu().numpy()
        scores = predictions["scores"].cpu().numpy()
        
        # Post-processing & Drawing
        draw = ImageDraw.Draw(original_img)
        
        results_json = []
        
        for box, label, score in zip(boxes, labels, scores):
            if score >= conf:
                # box is [xmin, ymin, xmax, ymax] in 320x320 scale
                xmin, ymin, xmax, ymax = box
                xmin = xmin * orig_w / 320.0
                xmax = xmax * orig_w / 320.0
                ymin = ymin * orig_h / 320.0
                ymax = ymax * orig_h / 320.0
                
                class_name = SSD_CLASS_NAMES.get(label, f"Unknown_{label}")
                
                # Draw box
                draw.rectangle([xmin, ymin, xmax, ymax], outline="red", width=3)
                # Draw label
                text = f"{class_name} {score:.2f}"
                draw.text((xmin, ymin - 15), text, fill="red")
                
                results_json.append({
                    "name": class_name,
                    "confidence": float(score),
                    "box": {"x1": float(xmin), "y1": float(ymin), "x2": float(xmax), "y2": float(ymax)}
                })
                
        # Save drawn image to TEMP_DIR
        base_name = os.path.basename(image_path)
        pred_path = os.path.join(TEMP_DIR, f"pred_ssd_{base_name}")
        original_img.save(pred_path)
        
        class _MockResults:
            def __init__(self, json_data, save_path):
                self.json_data = json_data
                self.save_path = save_path
                self.speed = {"inference": 0, "preprocess": 0, "postprocess": 0} # mock speed
                
            def tojson(self):
                import json
                return json.dumps(self.json_data)
        
        # Mock ultralytics result object structure to be compatible with inference.py
        mock_result = _MockResults(results_json, pred_path)
        # Mock the path property which is accessed as results[0].path
        setattr(mock_result, "path", pred_path)
        
        return [mock_result]

    def get_current_device_label(self):
        devices = probe_all_devices()
        for d in devices:
            if d["id"] == self.current_device:
                return d["label"]
        return self.current_device

model_manager = ModelManager()
