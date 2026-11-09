"""What a machine reports of itself: GPUs with their processes and where those come from, memory and disks."""
from app.backend.runtime import node_resources
from app.backend.runtime.node_resources import ancestorsOf, diskOf, gpuSnapshot, memoryOf, parseGpuDetails

GPUS = ("0, GPU-aaa, NVIDIA A100, 87, 30000, 40960, 61\n"
        "1, GPU-bbb, NVIDIA A100, 0, 0, 40960, [N/A]\n")


def _proc(tmp_path, parents):
    for pid, parent in parents.items():
        (tmp_path / str(pid)).mkdir()
        (tmp_path / str(pid) / "stat").write_text(f"{pid} (relion refine) S {parent} 0 0\n")
    return str(tmp_path)


def test_TheGpusDetailsAreRead():
    first, second = parseGpuDetails(GPUS)
    assert (first["index"], first["name"], first["busy"], first["temperature"]) == ("0", "NVIDIA A100", 87.0, 61.0)
    assert first["memoryUsedBytes"] == 30000 * 1024 * 1024
    assert second["temperature"] is None


def test_AProcessComesWithTheProcessesItDescendsFrom(tmp_path):
    proc = _proc(tmp_path, {30: 20, 20: 10, 10: 1, 1: 0})
    assert ancestorsOf(30, proc) == [20, 10, 1]
    assert ancestorsOf(99, proc) == []


def test_EachGpuListsItsProcesses(tmp_path, monkeypatch):
    proc = _proc(tmp_path, {30: 20, 20: 10})
    answers = {"--query-gpu": GPUS, "--query-compute-apps": "GPU-aaa, 30, 29000\n"}
    monkeypatch.setattr(node_resources, "_run", lambda arguments: answers[arguments[1].split("=")[0]])
    snapshot = gpuSnapshot(tool="/bin/tool", proc=proc)
    first, second = snapshot["gpus"]
    assert first["processes"] == [{"pid": 30, "memoryBytes": 29000 * 1024 * 1024, "ancestors": [20, 10]}]
    assert second["processes"] == []


def test_AMachineWithoutGpusOrWhoseToolFailsSaysSo(monkeypatch):
    monkeypatch.setattr(node_resources.shutil, "which", lambda name: None)
    assert gpuSnapshot() == {"gpus": [], "gpuError": None}
    monkeypatch.setattr(node_resources, "_run", lambda arguments: None)
    assert gpuSnapshot(tool="/bin/tool")["gpuError"]


def test_MemoryAndDisks(tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       32000 kB\nMemFree:  1000 kB\nMemAvailable:   16000 kB\n")
    assert memoryOf(str(meminfo)) == {"memoryTotalBytes": 32000 * 1024, "memoryAvailableBytes": 16000 * 1024}
    disk = diskOf("projects", str(tmp_path))
    assert disk["label"] == "projects" and disk["totalBytes"] >= disk["freeBytes"] > 0
    assert diskOf("scratch", None) is None and diskOf("scratch", str(tmp_path / "missing")) is None
