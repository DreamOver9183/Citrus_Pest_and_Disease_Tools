import torch
import psutil

def probe_all_devices():
    devices = []
    
    # 1. CPU
    mem = psutil.virtual_memory()
    devices.append({
        "id": "cpu",
        "label": "CPU",
        "type": "cpu",
        "available": True,
        "details": {
            "ram_total_gb": round(mem.total / (1024 ** 3), 1),
            "ram_used_gb": round(mem.used / (1024 ** 3), 1)
        }
    })
    
    # 2. CUDA
    if torch.cuda.is_available():
        num_devices = torch.cuda.device_count()
        for i in range(num_devices):
            props = torch.cuda.get_device_properties(i)
            mem_reserved = torch.cuda.memory_reserved(i)
            mem_allocated = torch.cuda.memory_allocated(i)
            devices.append({
                "id": f"cuda:{i}",
                "label": f"{props.name} (cuda:{i})",
                "type": "cuda",
                "available": True,
                "details": {
                    "vram_total_gb": round(props.total_memory / (1024 ** 3), 1),
                    "vram_reserved_gb": round(mem_reserved / (1024 ** 3), 1),
                    "vram_allocated_gb": round(mem_allocated / (1024 ** 3), 1),
                    "compute_capability": f"{props.major}.{props.minor}"
                }
            })
    
    # 3. MPS
    mps_available = False
    try:
        mps_available = torch.backends.mps.is_available()
    except Exception:
        pass
        
    if mps_available:
        devices.append({
            "id": "mps",
            "label": "Apple Silicon (MPS) [Experimental]",
            "type": "mps",
            "available": True,
            "details": {}
        })
        
    return devices

def get_recommended_device():
    if torch.cuda.is_available():
        return "cuda:0"
    
    mps_available = False
    try:
        mps_available = torch.backends.mps.is_available()
    except Exception:
        pass
        
    if mps_available:
        return "mps"
        
    return "cpu"
