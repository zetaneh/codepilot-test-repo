import json
import psutil
import time

def get_health_metrics():
    # Uptime
    boot_time_timestamp = psutil.boot_time()
    uptime_seconds = time.time() - boot_time_timestamp

    # Memory
    memory = psutil.virtual_memory()

    # Disk
    disk = psutil.disk_usage('/')

    metrics = {
        "status": "ok",
        "uptime_seconds": uptime_seconds,
        "memory": {
            "total": memory.total,
            "available": memory.available,
            "percent": memory.percent,
            "used": memory.used,
            "free": memory.free
        },
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": disk.percent
        }
    }
    return metrics

if __name__ == "__main__":
    metrics = get_health_metrics()
    print(json.dumps(metrics, indent=2))
