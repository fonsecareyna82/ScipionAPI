"""The record of one protocol run, for the computing each user uses: who launched it, where it ran, for how long
and with which GPUs.

The worker opens it when the protocol starts running (after waiting for its inputs and for a run slot), keeps it
alive from its heartbeat thread, and closes it with the status the protocol ended with. Keeping the record must
never stop a run: every failure here is logged and ignored.
"""
import logging
import os
import socket
from typing import Any, Dict, Optional

from app.backend.mapper.compute_usage_mapper import ComputeUsagePostgresqlMapper

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

    def __init__(self, db, runId: int):
        self.db = db
        self.runId = runId

    @classmethod
    def start(cls, db, projectId: int, projectPath: Optional[str], protocolId, protocol, userId: Optional[int],
              executionId: Optional[str], coordinatorRunId: Optional[str],
              streaming: bool) -> Optional["ProtocolRunRecord"]:
        try:
            values = dict(describeRun(protocol), projectId=int(projectId), projectPath=projectPath,
                          protocolId=str(protocolId), userId=userId, executionId=executionId,
                          coordinatorRunId=coordinatorRunId or None, host=socket.gethostname(),
                          streaming=bool(streaming))
            runId = ComputeUsagePostgresqlMapper(db).startRun(values)
            return cls(db, runId) if runId is not None else None
        except Exception:
            logger.warning("Could not record the start of the run. projectId=%s protocolId=%s",
                           projectId, protocolId, exc_info=True)
            return None

    def touch(self) -> None:
        try:
            ComputeUsagePostgresqlMapper(self.db).touchRun(self.runId)
        except Exception:
            logger.warning("Could not record that run %s is alive", self.runId, exc_info=True)

    def end(self, status: str) -> None:
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
