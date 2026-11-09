"""Looking at a run's GPUs: what the driver's tool says, which processes are the run's, and what is kept."""
import os

from app.backend.runtime import gpu_sampler
from app.backend.runtime.gpu_sampler import (GpuSampler, GpuUse, measure, parseGpus, parseProcesses, physicalGpus,
                                             processTree)

MiB = 1024 * 1024

GPUS = "0, GPU-aaa, 90, 4000\n1, GPU-bbb, 70, 3000\n2, GPU-ccc, 0, 0\n"
PROCESSES = "GPU-aaa, 101, 3500\nGPU-bbb, 202, 2800\n"


def test_TheToolsLinesAreRead():
    gpus = parseGpus(GPUS + "\n[N/A]\n")
    assert [(gpu.index, gpu.uuid, gpu.busy, gpu.memoryBytes) for gpu in gpus][0] == ("0", "GPU-aaa", 90.0, 4000 * MiB)
    assert len(gpus) == 3
    processes = parseProcesses(PROCESSES + "No running processes found\n")
    assert [(p.uuid, p.pid, p.memoryBytes) for p in processes] == [("GPU-aaa", 101, 3500 * MiB),
                                                                   ("GPU-bbb", 202, 2800 * MiB)]


def test_ARunsGpuIdsPointIntoTheVisibleDevices():
    assert physicalGpus(["0", "1"], None) == ["0", "1"]
    assert physicalGpus(["0", "1"], "2,3") == ["2", "3"]
    assert physicalGpus(["0"], "GPU-ccc") == ["GPU-ccc"]
    assert physicalGpus(["5"], "2,3") == ["5"]


def test_AGpuIsBusyOnlyWhileTheRunsProcessesAreOnIt():
    gpus, processes = parseGpus(GPUS), parseProcesses(PROCESSES)
    visible = {101, 202}
    # The run (process 101) is on GPU 0; GPU 1 is busy with someone else's process; GPU 2 is idle
    busy, memory = measure(gpus, processes, ["0", "1", "2"], tree={1, 101}, visiblePids=visible)
    assert busy == 30.0 and memory == 3500 * MiB
    assert measure(gpus, processes, ["0"], tree={1, 101}, visiblePids=visible) == (90.0, 3500 * MiB)
    assert measure(gpus, processes, ["GPU-bbb"], tree={1, 101}, visiblePids=visible) == (0.0, 0)
    assert measure(gpus, processes, ["7"], tree={1}, visiblePids=visible) is None


def test_ProcessesThisMachineCannotSeeTakeTheGpusOwnFigures():
    gpus, processes = parseGpus(GPUS), parseProcesses(PROCESSES)
    assert measure(gpus, processes, ["1"], tree={1}, visiblePids=set()) == (70.0, 3000 * MiB)


def test_TheRunsProcessesAreTheRootAndWhatDescendsFromIt(tmp_path):
    for pid, parent in ((10, 1), (11, 10), (12, 11), (20, 1)):
        (tmp_path / str(pid)).mkdir()
        (tmp_path / str(pid) / "stat").write_text(f"{pid} (python x) S {parent} 0 0\n")
    assert processTree(10, proc=str(tmp_path)) == {10, 11, 12}


def test_TheLooksAddUp(monkeypatch):
    answers = {"--query-gpu": GPUS, "--query-compute-apps": PROCESSES}
    monkeypatch.setattr(gpu_sampler, "_run", lambda arguments: answers[arguments[1].split("=")[0]])
    monkeypatch.setattr(gpu_sampler, "processTree", lambda root: {root, 101})
    monkeypatch.setattr(gpu_sampler.os.path, "exists", lambda path: True)
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    sampler = GpuSampler(["0", "1"], root=1, interval=60, tool="/bin/tool")
    sampler.sampleOnce()
    sampler.sampleOnce()
    use = sampler.stop()
    assert (use.samples, use.busySum, use.memoryPeakBytes) == (2, 90.0, 3500 * MiB)


def test_AMachineWithoutTheToolIsNotLookedAt(monkeypatch):
    monkeypatch.setattr(gpu_sampler.shutil, "which", lambda name: None)
    assert GpuSampler.startFor(["0"]) is None
    assert GpuSampler.startFor([]) is None


def test_AToolThatFailsAddsNothing(monkeypatch):
    monkeypatch.setattr(gpu_sampler, "_run", lambda arguments: None)
    sampler = GpuSampler(["0"], root=1, interval=60, tool="/bin/tool")
    sampler.sampleOnce()
    assert sampler.snapshot() == GpuUse()
