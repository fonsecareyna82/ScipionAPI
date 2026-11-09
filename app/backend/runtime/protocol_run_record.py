"""The record of one protocol run, for the computing each user uses: who launched it, where it ran, for how long,
with which GPUs and how much it really used them.

The worker opens it when the protocol starts running (after waiting for its inputs and for a run slot), keeps it
alive from its heartbeat thread, and closes it with the status the protocol ended with. A run with GPUs started
on this machine (not sent to a queue) has them looked at while it goes on (gpu_sampler); what was found is saved
with each heartbeat and at the end. Keeping the record must
never stop a run: every failure here is logged and ignored.
"""
import logging
import os
import socket
from typing import Any, Dict, Optional

from app.backend.mapper.compute_usage_mapper import ComputeUsagePostgresqlMapper
from app.backend.runtime.gpu_sampler import GpuSampler

logger = logging.getLogger(__name__)

# The environment variables a queue sets to its job's id inside the job
QUEUE_JOB_ID_VARIABLES = ("SLURM_JOB_ID", "PBS_JOBID", "LSB_JOBID", "JOB_ID")


def _value(protocol, attribute: str) -> Optional[int]:
    try:
        value = getattr(protocol, attribute).get()
        return int(value) if value is not None else None
    except Exception:
        return None


def describeRun(protocol) -> Dict[str, Any]:
    """What a protocol runs with: its GPUs, threads, MPI processes and queue."""
    gpuIds = []
    try:
        if protocol.usesGpu():
            gpuIds = [str(gpu) for gpu in protocol.getGpuList()]
    except Exception:
        gpuIds = []

    queueName = None
    try:
        if protocol.useQueue():
            queueName = str(protocol.getQueueParams()[0] or "") or None
    except Exception:
        queueName = None

    queueJobId = next((os.environ[name] for name in QUEUE_JOB_ID_VARIABLES if os.environ.get(name)), None)

    try:
        label = protocol.getObjLabel() or None
    except Exception:
        label = None

    return {
        "protocolClassName": type(protocol).__name__,
        "protocolLabel": label,
        "gpus": len(gpuIds),
        "gpuIds": ",".join(gpuIds) or None,
        "threads": _value(protocol, "numberOfThreads"),
        "mpi": _value(protocol, "numberOfMpi"),
        "queueName": queueName,
        "queueJobId": queueJobId,
    }


class ProtocolRunRecord:
    """One run of a protocol in protocol_runs."""

    def __init__(self, db, runId: int, sampler: Optional[GpuSampler] = None):
        self.db = db
        self.runId = runId
        self.sampler = sampler
        self._savedSamples = 0

    @classmethod
    def start(cls, db, projectId: int, projectPath: Optional[str], protocolId, protocol, userId: Optional[int],
              executionId: Optional[str], coordinatorRunId: Optional[str],
              streaming: bool) -> Optional["ProtocolRunRecord"]:
        try:
            values = dict(describeRun(protocol), projectId=int(projectId), projectPath=projectPath,
                          protocolId=str(protocolId), userId=userId, executionId=executionId,
                          coordinatorRunId=coordinatorRunId or None, host=socket.gethostname(),
                          streaming=bool(streaming), pid=os.getpid())
            runId = ComputeUsagePostgresqlMapper(db).startRun(values)
            if runId is None:
                return None
            return cls(db, runId, sampler=cls._startSampler(values))
        except Exception:
            logger.warning("Could not record the start of the run. projectId=%s protocolId=%s",
                           projectId, protocolId, exc_info=True)
            return None

    @staticmethod
    def _startSampler(values: Dict[str, Any]) -> Optional[GpuSampler]:
        """Looks at the run's GPUs, when it has some and runs here (a queue runs it on another machine)."""
        if not values.get("gpuIds") or values.get("queueName"):
            return None
        try:
            return GpuSampler.startFor(str(values["gpuIds"]).split(","))
        except Exception:
            logger.warning("Could not start looking at the GPUs of the run", exc_info=True)
            return None

    def _saveGpuUse(self, final: bool = False) -> None:
        if self.sampler is None:
            return
        try:
            use = self.sampler.stop() if final else self.sampler.snapshot()
            if use.samples == self._savedSamples:
                return
            ComputeUsagePostgresqlMapper(self.db).saveGpuUse(self.runId, use.samples, use.busySum,
                                                            use.memoryPeakBytes)
            self._savedSamples = use.samples
        except Exception:
            logger.warning("Could not record the GPU use of run %s", self.runId, exc_info=True)

    def touch(self) -> None:
        try:
            ComputeUsagePostgresqlMapper(self.db).touchRun(self.runId)
        except Exception:
            logger.warning("Could not record that run %s is alive", self.runId, exc_info=True)
        self._saveGpuUse()

    def end(self, status: str) -> None:
        self._saveGpuUse(final=True)
        try:
            ComputeUsagePostgresqlMapper(self.db).endRun(self.runId, status)
        except Exception:
            logger.warning("Could not record the end of run %s", self.runId, exc_info=True)
            return
        # A failure (or a long run that finished) is told to whom it concerns; never stops the worker
        try:
            from app.backend.api.services import notify_events

            notify_events.runEnded(self.db, self.runId, status)
        except Exception:
            logger.warning("Could not tell of the end of run %s", self.runId, exc_info=True)


def endStatus(protocolStatus: Any, raised: bool) -> str:
    """The status a run ended with: the protocol's, or failed when the run raised without saying so."""
    status = str(protocolStatus or "").strip().lower()
    if raised and status not in ("failed", "aborted"):
        return "failed"
    # A protocol that returns while still marked running was stopped from outside
    return status if status and status not in ("running", "launched", "scheduled") else "aborted"
