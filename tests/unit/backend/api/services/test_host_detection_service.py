import shutil
from pathlib import Path
import time

import pytest

from app.backend.api.services import host_detection_service as detection


def which(*present):
    return lambda command: f"/usr/bin/{command}" if command in present else None


SINFO = "\n".join([
    "gpu*|2-00:00:00|64|515000|gpu:a100:4(S:0-1)|up|3",
    "gpu*|2-00:00:00|32|256000|gpu:a100:2|up|1",
    "cpu|infinite|128|1024000|(null)|up|10",
    "short|30:00|8|4000|(null)|down|2",
])


def test_TheSchedulerIsToldByItsCommands():
    assert detection.detectScheduler(which("sbatch", "squeue", "sinfo")) == {"key": "slurm", "name": "SLURM"}
    assert detection.detectScheduler(which("qsub", "qconf"))["key"] == "sge"
    assert detection.detectScheduler(which("qsub", "pbsnodes"))["key"] == "pbs"
    assert detection.detectScheduler(which("bsub", "bjobs"))["key"] == "lsf"
    assert detection.detectScheduler(which()) is None


def test_SlurmPartitionsGatherTheirNodesWithTheDefaultFirst():
    partitions = detection.slurmPartitions(lambda command: SINFO)
    assert [partition["name"] for partition in partitions] == ["gpu", "cpu", "short"]
    gpu, cpu, short = partitions
    assert gpu == {"name": "gpu", "default": True, "hours": 48, "cpus": 64, "memoryMb": 515000, "gpus": 4,
                   "nodes": 4, "up": True, "asleep": False, "unknown": False}
    assert cpu["hours"] is None and cpu["gpus"] == 0
    assert short["hours"] == 1 and not short["up"]


# A cloud cluster with every machine off: they are not listed, the configuration still says what they have
CLOUD_SINFO = "gpu*|2-00:00:00|0|0|(null)|up|0|n/a\ncpu|infinite|16|64000|(null)|up|5|idle~\n"
CLOUD_PARTITIONS = "\n".join([
    "PartitionName=gpu AllowGroups=ALL Default=YES MaxTime=2-00:00:00 State=UP TotalCPUs=0",
    "PartitionName=cpu AllowGroups=ALL Default=NO MaxTime=UNLIMITED State=UP TotalCPUs=80",
    "PartitionName=admin Hidden=YES Default=NO MaxTime=UNLIMITED State=UP",
    "PartitionName=spot AllowGroups=ALL Default=NO MaxTime=04:00:00 State=UP TotalCPUs=0",
])
CLOUD_NODES = "\n".join([
    "NodeName=gpu-1 CPUTot=24 Gres=gpu:a100:2 RealMemory=220000 State=IDLE+CLOUD+POWERED_DOWN Partitions=gpu",
    "NodeName=gpu-2 CPUTot=24 Gres=gpu:a100:2 RealMemory=220000 State=IDLE+CLOUD+POWERED_DOWN Partitions=gpu",
    "NodeName=cpu-1 CPUTot=16 Gres=(null) RealMemory=64000 State=IDLE+CLOUD+POWERED_DOWN Partitions=cpu,spot",
])


def cloudRun(command):
    if command[0] == "sinfo":
        return CLOUD_SINFO
    return CLOUD_PARTITIONS if command[-1] == "partition" else CLOUD_NODES


def test_MachinesThatAreOffAreReadFromTheConfiguration():
    gpu, cpu, spot = detection.slurmPartitions(cloudRun)
    assert (gpu["name"], gpu["cpus"], gpu["memoryMb"], gpu["gpus"], gpu["nodes"]) == ("gpu", 24, 220000, 2, 2)
    assert gpu["asleep"] and gpu["default"] and not gpu["unknown"]
    assert cpu["asleep"] and cpu["cpus"] == 16
    # Only in the configuration (and the hidden one left out)
    assert spot["name"] == "spot" and spot["hours"] == 4 and spot["cpus"] == 16

    found = detection.detectHost("localhost", which("sbatch", "squeue", "sinfo"), cloudRun)
    assert "--gres=gpu:%_(GPU_COUNT)s" in found["settings"]["submitTemplate"]
    assert "start when a job comes" in found["message"] and "by hand" not in found["message"]


def test_WhatCannotBeKnownIsSaid():
    def nothingConfigured(command):
        if command[0] == "sinfo":
            return "gpu*|2-00:00:00|0|0|(null)|up|0|n/a\n"
        raise RuntimeError("scontrol: not allowed")
    gpu, = detection.slurmPartitions(nothingConfigured)
    assert gpu["unknown"]
    found = detection.detectHost("localhost", which("sbatch", "squeue", "sinfo"), nothingConfigured)
    assert "check memory and GPUs by hand" in found["message"]


def test_TheProposalHasAQueuePerPartitionWithinItsLimits():
    settings = detection.slurmHostSettings("cluster", detection.slurmPartitions(lambda command: SINFO))
    assert settings["schedulerName"] == "SLURM"
    assert settings["submitCommand"] == "sbatch --parsable %_(JOB_SCRIPT)s"
    assert "--gres=gpu:%_(GPU_COUNT)s" in settings["submitTemplate"]
    queues = {queue["name"]: {param["variableName"]: param["value"] for param in queue["params"]}
              for queue in settings["queues"]}
    assert queues["gpu"] == {"JOB_MEMORY": "8192", "JOB_TIME": "24", "GPU_COUNT": "1", "QUEUE_FOR_JOBS": "N"}
    assert queues["cpu"]["GPU_COUNT"] == "0"
    assert queues["short"] == {"JOB_MEMORY": "4000", "JOB_TIME": "1", "GPU_COUNT": "0", "QUEUE_FOR_JOBS": "N"}


def test_WithoutGpusTheScriptAsksForNone():
    settings = detection.slurmHostSettings("localhost", detection.slurmPartitions(
        lambda command: "main*|infinite|16|64000|(null)|up|1"))
    assert "gres" not in settings["submitTemplate"]
    assert [param["variableName"] for param in settings["queues"][0]["params"]] == [
        "JOB_MEMORY", "JOB_TIME", "QUEUE_FOR_JOBS"]


def test_DetectingSaysWhatItFound():
    found = detection.detectHost("localhost", which("sbatch", "squeue", "sinfo"), lambda command: SINFO)
    assert found["supported"] and found["settings"]["hostAlias"] == "localhost"
    assert "3 queues" in found["message"]

    nothing = detection.detectHost("localhost", which(), lambda command: "")
    assert nothing["scheduler"] is None and nothing["settings"] is None

    lsf = detection.detectHost("localhost", which("bsub", "bjobs"), lambda command: "")
    assert lsf["scheduler"] == "LSF" and not lsf["supported"] and "by hand" in lsf["message"]

    def broken(command):
        raise RuntimeError("slurm_load_partitions: Unable to contact slurm controller")
    failing = detection.detectHost("localhost", which("sbatch", "squeue", "sinfo"), broken)
    assert "could not be read" in failing["message"] and "controller" in failing["message"]


def test_TheTestJobIsFilledInAsForAProtocol(tmp_path):
    settings = detection.slurmHostSettings("localhost", detection.slurmPartitions(lambda command: SINFO))
    job = detection.buildTestJob(settings, "gpu", tmp_path)
    assert job["submit"] == f"sbatch --parsable {tmp_path}/scipionweb_test_job.sh"
    assert "#SBATCH -p gpu" in job["scriptText"]
    assert "--mem=8192 --gres=gpu:1" in job["scriptText"]
    assert detection.TEST_COMMAND in job["scriptText"]

    settings["submitTemplate"] += "\n%_(ACCOUNT)s"
    with pytest.raises(ValueError, match=r"%_\(ACCOUNT\)s"):
        detection.buildTestJob(settings, "gpu", tmp_path)


def test_ATestJobRunsThroughTheConfiguredCommands(tmp_path):
    # A fake scheduler: "submitting" runs the script at once and prints a job id; checking answers nothing (gone)
    settings = {
        "submitTemplate": "#!/bin/bash\n%_(JOB_COMMAND)s > %_(JOB_SCRIPT)s.out",
        "submitCommand": "bash %_(JOB_SCRIPT)s && echo 4242",
        "checkCommand": "true %_(JOB_ID)s",
        "cancelCommand": "true",
        "jobDoneRegex": "",
        "queues": [{"name": "local", "params": []}],
    }
    started = detection.startTest(settings, "local", tmp_path)
    deadline = time.time() + 10
    while time.time() < deadline and detection.getTest(started["id"])["state"] not in ("finished", "failed"):
        time.sleep(0.1)
    result = detection.getTest(started["id"])
    assert result["state"] == "finished", result
    assert result["jobId"] == "4242"
    assert "ScipionWeb test job ran on" in result["output"]


def test_ATestJobThatCannotBeSentSaysWhy(tmp_path):
    settings = {"submitTemplate": "%_(JOB_COMMAND)s", "submitCommand": "echo 'no queue here' >&2; false",
                "checkCommand": "true", "queues": [{"name": "local", "params": []}]}
    started = detection.startTest(settings, "local", tmp_path)
    deadline = time.time() + 10
    while time.time() < deadline and detection.getTest(started["id"])["state"] not in ("finished", "failed"):
        time.sleep(0.1)
    result = detection.getTest(started["id"])
    assert result["state"] == "failed" and "no queue here" in result["output"]

    with pytest.raises(ValueError):
        detection.startTest(settings, "missing", tmp_path)


@pytest.mark.skipif(not shutil.which("sinfo"), reason="needs a Slurm on this machine")
def test_TheRealSlurmOfThisMachineIsRead():
    found = detection.detectHost("localhost")
    assert found["scheduler"] == "SLURM" and found["queues"], found


QSTAT_Q = """Queue: batch
    queue_type = Execution
    resources_max.walltime = 72:00:00
    resources_max.mem = 128gb
    resources_max.ncpus = 32
    enabled = True
    started = True

Queue: route
    queue_type = Route
    enabled = True

Queue: long
    queue_type = Execution
    resources_max.walltime = 336:00:00
    enabled = False
    started = True
"""


def pbsRun(command):
    return "Server: head\n    default_queue = batch\n" if command[:2] == ["qstat", "-B"] else QSTAT_Q


def test_PbsExecutionQueuesAreReadWithTheirLimits():
    queues = detection.pbsQueues(pbsRun)
    assert [queue["name"] for queue in queues] == ["batch", "long"]
    batch, long = queues
    assert batch["default"] and batch["hours"] == 72 and batch["memoryMb"] == 131072 and batch["cpus"] == 32
    assert long["hours"] == 336 and not long["up"]

    found = detection.detectHost("localhost", which("qsub", "pbsnodes"), pbsRun)
    settings = found["settings"]
    assert found["supported"] and settings["schedulerName"] == "PBS/TORQUE"
    assert settings["cancelCommand"] == "qdel %_(JOB_ID)s" and settings["jobDoneRegex"] == "job_state = [CF]"
    job = detection.buildTestJob(settings, "batch", Path("/tmp/x"))
    assert "#PBS -q batch" in job["scriptText"] and "#PBS -l mem=8192mb" in job["scriptText"]


def sgeRun(command):
    if command == ["qconf", "-sql"]:
        return "all.q\ngpu.q\n"
    if command == ["qconf", "-spl"]:
        return "make\nmpi\nsmp\n"
    name = command[-1]
    return {"all.q": "qname all.q\nhostlist @allhosts n1 n2\nslots 1,[n1=16],[n2=16]\nh_rt INFINITY\nh_vmem INFINITY\n",
            "gpu.q": "qname gpu.q\nhostlist g1\nslots 8\nh_rt 48:00:00\nh_vmem 16G\n"}[name]


def test_SgeQueuesAndItsThreadsEnvironment():
    queues = detection.sgeQueues(sgeRun)
    assert [(queue["name"], queue["hours"], queue["memoryMb"], queue["cpus"], queue["nodes"]) for queue in queues] == [
        ("all.q", None, 0, 16, 2), ("gpu.q", 48, 16384, 8, 1)]
    assert detection.sgeThreadsEnvironment(sgeRun) == "smp"

    settings = detection.detectHost("localhost", which("qsub", "qconf"), sgeRun)["settings"]
    assert settings["schedulerName"] == "SGE"
    job = detection.buildTestJob(settings, "gpu.q", Path("/tmp/x"))
    assert "#$ -pe smp 1" in job["scriptText"] and "#$ -l h_vmem=8192M" in job["scriptText"]
    assert "#$ -l h_rt=24:00:00" in job["scriptText"]


def test_TheInstallerSetsUpOnlyAnUnsetHostsConf(tmp_path):
    path = tmp_path / "hosts.conf"
    path.write_text('[localhost]\nNAME = PBS/TORQUE\nQUEUES = { "default": {} }\n')
    assert detection.configuredQueues(path) is None

    done = detection.autoConfigureHostsConf(path, which("sbatch", "squeue", "sinfo"), lambda command: SINFO)
    assert done["written"] and "gpu, cpu, short" in done["message"]
    assert (tmp_path / "hosts.conf.before-detect").exists()
    assert detection.configuredQueues(path) == ["gpu", "cpu", "short"]

    # What Scipion reads back is the same script, with its #SBATCH lines
    from configparser import RawConfigParser
    parser = RawConfigParser(comment_prefixes=";")
    parser.optionxform = str
    parser.read(path)
    assert "#SBATCH -p %_(JOB_QUEUE)s" in parser.get("localhost", "SUBMIT_TEMPLATE")
    assert parser.get("localhost", "SUBMIT_COMMAND") == "sbatch --parsable %_(JOB_SCRIPT)s"

    again = detection.autoConfigureHostsConf(path, which("sbatch", "squeue", "sinfo"), lambda command: SINFO)
    assert not again["written"] and again["reason"] == "configured"

    nothing = detection.autoConfigureHostsConf(tmp_path / "other.conf", which(), lambda command: "")
    assert not nothing["written"] and nothing["reason"] == "nothing"


def test_TheDoctorComparesHostsConfWithTheScheduler(tmp_path):
    path = tmp_path / "hosts.conf"
    slurm = which("sbatch", "squeue", "sinfo")
    path.write_text('[localhost]\nQUEUES = { "default": {} }\n')
    assert detection.checkHostsConf(path, which())["status"] == "ok"
    assert "not set up" in detection.checkHostsConf(path, slurm, lambda command: SINFO)["detail"]

    detection.writeHostsConf(path, detection.slurmHostSettings("localhost", detection.slurmPartitions(
        lambda command: SINFO)))
    assert detection.checkHostsConf(path, slurm, lambda command: SINFO)["status"] == "ok"
    fewer = detection.checkHostsConf(path, slurm, lambda command: "gpu*|1:00:00|1|1|(null)|up|1")
    assert fewer["status"] == "warn" and "cpu, short" in fewer["detail"]
    assert detection.checkHostsConf(path, which())["status"] == "warn"
