"""What a session's first movie says about its acquisition, read from the metadata the microscope wrote with it.

The reading is Dmitry A. Semchonok's (ITQB NOVA, ORCID 0000-0003-1622-9443; ``app/backend/vendor/cryo_import_metadata``):
EPU XML (Falcon, Gatan K2/K3, Ceta) and SerialEM MDOC, every value marked DIRECT, DERIVED, MANUAL (not in the
metadata) or UNVERIFIED, and the dose on the sample worked out from fields whose units EPU does not label. On top
of it, what the facility knows:

* the detector is the one of the microscope the metadata names (``detectorFor``), and its reader is chosen by that
  camera name: EPU 2.x writes no detector commercial name, and its Falcon XML carries Ceta keys too;
* the frames come from the movie's ``_Fractions.xml`` when the XML does not give them;
* the pixel is the detector's calibrated one for the magnification (``calibratedPixelSize``), and the doses per A^2
  are re-expressed for it; the nominal pixel is kept.
"""
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.backend.api.services.facility_service import calibratedPixelSize, detectorFor
from app.backend.vendor import cryo_import_metadata as reader

# What a movie's metadata file is called next to it: EPU names movies <image>_Fractions.<ext> or <image>_EER.eer
MOVIE_NAME_SUFFIXES = ("_Fractions", "_EER")
METADATA_SUFFIXES = (".xml", ".mdoc")


def metadataFileOf(moviePath: Path) -> Optional[Path]:
    """The XML (EPU) or MDOC (SerialEM) written with a movie, when it is there."""
    stem = moviePath.name.split(".", 1)[0]
    stems = [stem]
    for suffix in MOVIE_NAME_SUFFIXES:
        if stem.endswith(suffix):
            stems.insert(0, stem[: -len(suffix)])
    for candidate in stems:
        for extension in METADATA_SUFFIXES:
            path = moviePath.with_name(candidate + extension)
            if path.is_file():
                return path
    mdoc = moviePath.with_name(moviePath.name + ".mdoc")
    return mdoc if mdoc.is_file() else None


def _cameraName(root: ET.Element) -> Optional[str]:
    for camera in reader.children(root, "camera"):
        name = reader.first_text(camera, "Name")
        if name:
            return name
    return None


def _parse(path: Path, cameraName: Optional[str]) -> "reader.Report":
    if path.suffix.lower() != ".mdoc" and cameraName and "falcon" in cameraName.lower():
        root = ET.parse(path).getroot()
        if not reader.children(root, "Fraction"):
            return reader.parse_falcon(path, root)
    return reader.parse_file(path)


def _fractionsCount(xmlPath: Path) -> Optional[int]:
    fractions = xmlPath.with_name(xmlPath.stem + "_Fractions.xml")
    if not fractions.is_file():
        return None
    try:
        count = reader.number(reader.first_text(ET.parse(fractions).getroot(), "RecordedNumberOfFractions"))
    except ET.ParseError:
        return None
    return int(round(count)) if count else None


def _value(report: "reader.Report", key: str) -> Any:
    value = report.values.get(key)
    return value.value if value is not None else None


def _status(report: "reader.Report", key: str) -> Optional[str]:
    value = report.values.get(key)
    return value.status if value is not None and value.value is not None else None


def readAcquisition(metadataPath: Path, detectors: Iterable[Dict[str, Any]],
                    detectorId: Optional[int] = None) -> Dict[str, Any]:
    """What a movie's metadata says, with the microscope's detectors.

    detectorId is the detector the staff gave the dataset, if any: its calibration is used whatever the
    metadata names. Raises ValueError for metadata that cannot be read.
    """
    metadataPath = Path(metadataPath)
    detectors = list(detectors or ())
    cameraName = None
    if metadataPath.suffix.lower() == ".xml":
        try:
            cameraName = _cameraName(ET.parse(metadataPath).getroot())
        except ET.ParseError as error:
            raise ValueError("cannot parse XML: %s" % error)
    report = _parse(metadataPath, cameraName)
    detector = next((item for item in detectors if detectorId is not None and int(item["id"]) == int(detectorId)), None)
    detector = detector or detectorFor(detectors, cameraName or str(report.detector.value or ""))

    warnings: List[str] = list(report.warnings)
    frames = _value(report, "frames")
    framesStatus = _status(report, "frames")
    if frames is None and metadataPath.suffix.lower() == ".xml":
        frames = _fractionsCount(metadataPath)
        framesStatus = "DIRECT" if frames else None

    magnification = _value(report, "magnification")
    nominal = _value(report, "pixel")
    calibrated = calibratedPixelSize(detector.get("pixelSizes") or [], magnification, nominal) if detector else None
    if calibrated is not None and nominal:
        exposure = _value(report, "exposure")
        if report.format.startswith("EPU XML (Gatan"):
            report = reader.parse_epu_gatan(metadataPath, ET.parse(metadataPath).getroot(),
                                            reader.custom_data(ET.parse(metadataPath).getroot()),
                                            str(report.detector.value), calibrated)
        else:
            reader.apply_calibrated_pixel(report, nominal, calibrated, exposure)
        warnings = list(report.warnings)

    totalDose = _value(report, "total_dose")
    dosePerFrame = _value(report, "dose_per_frame")
    if dosePerFrame is None and totalDose and frames:
        dosePerFrame = totalDose / frames
    return {
        "metadataFile": metadataPath.name,
        "format": report.format,
        "cameraName": cameraName or report.detector.value,
        "detectorId": int(detector["id"]) if detector else None,
        "detectorName": detector["name"] if detector else None,
        "instrument": report.extras.get("instrument"),
        "acquiredAt": report.extras.get("acquisition_time"),
        "voltageKv": _value(report, "voltage"),
        "magnification": magnification,
        "nominalPixelSize": nominal,
        "pixelSize": calibrated if calibrated is not None else nominal,
        "pixelCalibrated": calibrated is not None,
        "frames": frames,
        "exposureSeconds": _value(report, "exposure"),
        "totalDose": totalDose,
        "dosePerFrame": dosePerFrame,
        "cameraDose": _value(report, "camera_dose"),
        "gain": _value(report, "gain"),
        # How each value was found (DIRECT, DERIVED, UNVERIFIED); a value missing from the metadata has none
        "statuses": {"frames": framesStatus, "totalDose": _status(report, "total_dose"),
                     "pixelSize": "CALIBRATED" if calibrated is not None else _status(report, "pixel")},
        "warnings": warnings,
    }
