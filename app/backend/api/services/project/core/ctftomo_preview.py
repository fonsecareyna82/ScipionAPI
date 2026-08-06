"""Building summary/measurement rows for CTFTomoSeries preview, and
constructing the PostgreSQL CTFTomo reader when available.
"""
from typing import Any, Dict


def buildCtftomoSeriesSummary(ctfSeries) -> Dict[str, Any]:
    """Build a JSON-friendly summary for one CTFTomoSeries object."""
    tsId = ctfSeries.getTsId()
    label = ctfSeries.getObjLabel()
    tiltSeries = ctfSeries.getTiltSeries()
    dims = list(tiltSeries.getDim())
    pixelSize = tiltSeries.getSamplingRate()
    nViews = tiltSeries.getSize()

    item: Dict[str, Any] = {
        "tiltSeriesId": tsId,
        "label": str(label) if label is not None else "",
    }
    if nViews is not None:
        item["nViews"] = nViews
    if dims is not None:
        item["dims"] = dims
    if pixelSize is not None:
        item["pixelSize"] = pixelSize
    return item


def buildCtftomoMeasurementRow(ctfObj, tiltSeries=None) -> Dict[str, Any]:
    """Build a JSON-friendly row with CTF parameters for a single tilt image."""
    defocusU = ctfObj.getDefocusU()
    defocusV = ctfObj.getDefocusV()
    defocusAngle = ctfObj.getDefocusAngle()
    resolution = ctfObj.getResolution()
    phaseShift = ctfObj.getPhaseShift()
    acqOrder = ctfObj.getAcquisitionOrder()
    psdFile = ctfObj.getPsdFile()
    astigmatism = defocusU - defocusV
    tiltAngle = None
    enabled = ctfObj.isEnabled()
    dose = None

    if tiltSeries is not None:
        try:
            view = tiltSeries.getItem('_acqOrder', acqOrder)
        except Exception:
            view = None

        if view is not None:
            try:
                tiltAngle = view.getTiltAngle()
            except Exception:
                tiltAngle = None

            try:
                acq = view.getAcquisition()
                dose = acq.getAccumDose()
            except Exception:
                dose = None

    row: Dict[str, Any] = {}
    row["index"] = ctfObj.getObjId()
    row["viewIndex"] = ctfObj.getObjId()
    if tiltAngle is not None:
        row["tiltAngle"] = tiltAngle
    if dose is not None:
        row["dose"] = dose
    if defocusU is not None:
        row["defocusU"] = defocusU
    if defocusV is not None:
        row["defocusV"] = defocusV
    row['astigmatism'] = astigmatism
    if defocusAngle is not None:
        row["defocusAngle"] = defocusAngle
    if resolution is not None:
        row["resolution"] = resolution
    if phaseShift is not None:
        row["phaseShift"] = phaseShift
    if acqOrder is not None:
        row["order"] = acqOrder
    if psdFile:
        row['psdFile'] = psdFile

    row['excluded'] = not enabled

    return row


def buildPostgresqlCtftomoReader(mapper, projectId: int, protocolId, outputName: str):
    """protocolId here is expected to already be resolved for reader use
    (see ProjectService._resolvePostgresqlReaderProtocolId)."""
    from app.backend.viewers.postgresql_ctftomo_reader import PostgresqlCtftomoReader

    reader = PostgresqlCtftomoReader(
        db=mapper.db,
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
    )

    if reader.hasOutput():
        return reader

    return None
