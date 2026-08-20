from PIL import Image
import os

def crop_metric_image(src_path, save_path, metric_type):
    """
    針對 YOLO results.png (2400x1200) 進行精確裁剪
    metric_type: 
      - 'train_box_loss', 'train_cls_loss', 'train_dfl_loss'
      - 'val_box_loss', 'val_cls_loss', 'val_dfl_loss'
      - 'precision', 'recall', 'mAP50', 'mAP50_95'
    """
    if not os.path.exists(src_path):
        return None
    
    img = Image.open(src_path)
    w, h = img.size
    
    # YOLO results.png 預設為 2 列 5 行
    grid_w, grid_h = w // 5, h // 2
    
    crops = {
        # 第一列 (Y: 0 ~ grid_h)
        "train_box_loss": (0, 0, grid_w, grid_h),
        "train_cls_loss": (grid_w, 0, grid_w*2, grid_h),
        "train_dfl_loss": (grid_w*2, 0, grid_w*3, grid_h),
        "precision": (grid_w*3, 0, grid_w*4, grid_h),
        "recall": (grid_w*4, 0, grid_w*5, grid_h),
        
        # 第二列 (Y: grid_h ~ h)
        "val_box_loss": (0, grid_h, grid_w, h),
        "val_cls_loss": (grid_w, grid_h, grid_w*2, h),
        "val_dfl_loss": (grid_w*2, grid_h, grid_w*3, h),
        "mAP50": (grid_w*3, grid_h, grid_w*4, h),
        "mAP50_95": (grid_w*4, grid_h, grid_w*5, h),
    }
    
    # 後備對應
    if metric_type == "mAP":
        metric_type = "mAP50"
    elif metric_type == "loss":
        metric_type = "train_box_loss"
        
    box = crops.get(metric_type, (0, 0, grid_w, grid_h))
    cropped = img.crop(box)
    cropped.save(save_path)
    return save_path
