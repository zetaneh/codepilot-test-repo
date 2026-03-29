import pytest
import subprocess
import json

def test_health_check_json_output_validity():
    result = subprocess.run(
        ["python", "health_check.py"],
        capture_output=True,
        text=True,
        check=True
    )
    output = json.loads(result.stdout)

    # 1. Verify JSON structure
    assert "status" in output
    assert "uptime_seconds" in output
    assert "memory" in output
    assert "disk" in output

    # 2. Verify data types and basic correctness
    assert output["status"] == "ok"
    assert isinstance(output["uptime_seconds"], (int, float))
    assert output["uptime_seconds"] > 0

    # Memory metrics
    memory = output["memory"]
    assert isinstance(memory, dict)
    assert "total" in memory
    assert "available" in memory
    assert "percent" in memory
    assert "used" in memory
    assert "free" in memory

    assert isinstance(memory["total"], int)
    assert isinstance(memory["available"], int)
    assert isinstance(memory["percent"], (int, float))
    assert isinstance(memory["used"], int)
    assert isinstance(memory["free"], int)

    assert 0 <= memory["percent"] <= 100
    assert memory["total"] >= memory["used"]
    assert memory["total"] >= memory["available"]

    # Disk metrics
    disk = output["disk"]
    assert isinstance(disk, dict)
    assert "total" in disk
    assert "used" in disk
    assert "free" in disk
    assert "percent" in disk

    assert isinstance(disk["total"], int)
    assert isinstance(disk["used"], int)
    assert isinstance(disk["free"], int)
    assert isinstance(disk["percent"], (int, float))

    assert 0 <= disk["percent"] <= 100
    assert disk["total"] >= disk["used"]
