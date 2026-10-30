#!/usr/bin/env python3
# Copyright (c) 2026 Dmitry A. Semchonok, ITQB NOVA (Universidade NOVA de Lisboa). All rights reserved.
# Author: Dmitry A. Semchonok
#         Cryo-EM Integrative Structural Biology Laboratory, ITQB NOVA, Oeiras, Portugal
#         dmitry.semchonok@itqb.unl.pt | ORCID: https://orcid.org/0000-0003-1622-9443
# v2.4 (11 Oct 2026): Gatan K2/K3 EPU XML reader and --pixel-size option added (prepared with AI assistance).
# v2.5 (21 Oct 2026): Falcon dose units verified by cross-checks; dose on sample used for import;
#                     camera dose, transmission, stage tilt and XML suffix hint added (prepared with AI assistance).
# v2.6 (21 Oct 2026): answer-first summary in cryoSPARC form order, dose per frame, all four XML cut fields
#                     with a worked example, one-line checks, per-grid-square table; --details for the long
#                     v2.5 summaries (prepared with AI assistance).
# v2.7 (21 Oct 2026): --pixel-size also applies to Falcon movies; doses per A^2 are re-expressed for the
#                     calibrated pixel (prepared with AI assistance).
# v2.8 (22 Oct 2026): beam-shift (AFIS) groups and cryoSPARC Exposure Group Utilities values; --table folder
#                     checked before the scan (prepared with AI assistance).
#                     29 Oct 2026: author details and sharing terms updated in this header; code unchanged.
# Sharing and permission:
#   - The Scipion team at CNB-CSIC (Madrid) may use, adapt and integrate this code into Scipion, including
#     Scipion Web, and distribute it as part of Scipion under Scipion's licence, provided that the author is
#     credited (name, ITQB NOVA and ORCID) in the code and in the documentation of any derived feature.
#   - Shared with the SBCloud CryoEM Tournament 2026 organizers for review of compliance with the tournament rules.
#   - Any other use, copying, modification or redistribution requires the author's written permission.
"""Report cryo-EM import metadata from EPU XML, Ceta fractions XML, or SerialEM MDOC.

Examples:
  python cryo_import_metadata.py movie.xml
  python cryo_import_metadata.py movie.mdoc
  python cryo_import_metadata.py /path/to/acquisition --sample 20
  python cryo_import_metadata.py /path/to/DATA_01 --scope epu-grid-data --summary-only
  python cryo_import_metadata.py /path/to/K3_data --scope all --summary-only --pixel-size 0.84
  python cryo_import_metadata.py /path/to/Krios_session --summary-only --pixel-size 0.7300

v2.4: adds EPU XML for Gatan K2/K3 (BioQuantum) movies.  Detector type is now
taken from the detector commercial name first, because K3 EPU XML also carries
"Ceta*" keys (CetaFramesSummed) that made v2.3 treat it as a Ceta image.

v2.5: fixes the Falcon dose.  v2.4 read Detectors[...].TotalDose as e-/A^2, but
on EPU with an energy-filtered Falcon (Krios, Detectors[EF-Falcon]) it equals
DoseOnCamera: the dose that reached the camera, in e-/pixel.  The import dose is
now the dose on the sample (CustomData DoseOnSample / 1e20, e-/A^2), validated
against the generic DoseRate * ExposureTime / pixel^2.  The unit of every other
dose field is inferred from how it relates to Dose and DoseOnSample, never
assumed.  Per movie, the camera dose and the camera/sample ratio (transmission
through ice and energy filter) are reported; blank or blocked exposures show up
as camera-dose outliers.  Also new: stage tilt, applied defocus, beam shift and
energy slit for Falcon; GridSquare_*/Data folders are recognised without an
Images-Disc* parent; the recommendation block picks the movie group(s) when
atlas, grid-square and foil-hole images are scanned too; and the cryoSPARC
"suffix to cut for XML correspondence" is derived from the movie file names.

v2.6: a directory run prints one answer-first summary: the cryoSPARC Import
Movies values in the order of the job form (including dose per frame for
RELION/Scipion and all four XML cut fields with a worked file-pair example),
one-line checks, and one line per grid square.  A value is printed as is when
every movie agrees; when movies differ, the median is shown together with the
range and the largest deviation, so the cost of using one value is visible.
--details adds the long v2.5 per-grid-square and dataset-wide summaries.

v2.7: --pixel-size (facility-calibrated movie pixel) now applies to Falcon
movies too.  EPU converts its measured dose (counts per pixel) to e-/A^2 with
its own nominal pixel, so with a calibrated pixel every dose per A^2 is
re-expressed: dose x (EPU pixel / calibrated pixel)^2.  The unit cross-checks
still use EPU's pixel, because that is the one EPU used.  Single images
(atlas, grid square, foil hole) keep EPU's pixel size.

v2.8: the beam shifts of the movies are grouped (single linkage over many length
scales, no extra packages) to suggest the 'Number of clusters' for cryoSPARC
Exposure Group Utilities: the group count that stays stable over the widest
range of scales, normally one group per AFIS hole position.  Shots per hole
come from the EPU Data template IDs in the file names.  Each movie's group is
written to the table (beam_shift_group; 0 = stray movie).

The program deliberately does not guess microscope values that are absent from
the acquisition metadata.  Every reported value is labelled DIRECT, DERIVED,
or MANUAL.  Dose conversion from a SerialEM K3 MDOC is only done under the
documented e-/physical-pixel/s convention.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import statistics
import sys
import textwrap
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


VERSION = "2.8"
DOSE_KEYS = {"dose_per_frame", "total_dose", "camera_dose"}
EXTRA_FIELDS = [
    "acquisition_time", "instrument", "image_pixel_A", "binning", "movie_size_px",
    "epu_nominal_movie_pixel_A", "dose_rate_e_per_movie_px_s", "epu_total_dose_e_per_A2",
    "total_dose_with_calibrated_pixel", "applied_defocus_um", "beam_shift_x", "beam_shift_y",
    "energy_slit_eV",
    # v2.5 (appended so that the column numbers of v2.4 tables stay the same)
    "stage_tilt_deg", "dose_rate_on_sample_e_per_px_s", "dose_on_camera_e_per_A2",
    "dose_on_camera_e_per_px", "camera_to_sample_ratio", "minus_ln_transmission",
    "detector_total_dose_unit",
]
STRICT_REL_TOLERANCE = 0.005
UNIT_REL_TOLERANCE = 0.02  # agreement needed to accept a unit interpretation
M2_TO_A2 = 1e20            # EPU area-normalised doses are e-/m^2; 1 m^2 = 1e20 A^2
MOVIE_SUFFIXES = (".eer", ".tif", ".tiff", ".mrcs")


@dataclass
class Value:
    value: Any = None
    status: str = "MANUAL"
    source: str = "not present in supplied metadata"
    unit: str = ""

    def display(self) -> str:
        if self.value is None:
            return "NOT FOUND"
        if isinstance(self.value, float):
            return f"{self.value:.6g}"
        return str(self.value)


@dataclass
class Report:
    path: Path
    format: str
    detector: Value
    values: dict[str, Value] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)


def direct(value: Any, source: str, unit: str = "") -> Value:
    return Value(value, "DIRECT", source, unit)


def derived(value: Any, source: str, unit: str = "") -> Value:
    return Value(value, "DERIVED", source, unit)


def manual(source: str = "not present in supplied metadata", unit: str = "") -> Value:
    return Value(None, "MANUAL", source, unit)


def percentile(values: list[float], probability: float) -> float:
    """Linearly interpolated percentile, equivalent to a common type-7 quantile."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def robust_outlier_indexes(values: list[float]) -> set[int]:
    """Flag strong outliers using modified z-score, with an IQR fallback."""
    if len(values) < 5:
        return set()
    median = statistics.median(values)
    deviations = [abs(item - median) for item in values]
    mad = statistics.median(deviations)
    if mad > 0:
        return {index for index, item in enumerate(values) if 0.67448975 * abs(item - median) / mad > 3.5}
    q1, q3 = percentile(values, 0.25), percentile(values, 0.75)
    iqr = q3 - q1
    if iqr <= 0:
        return set()
    low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return {index for index, item in enumerate(values) if item < low or item > high}


def number(text: Optional[str]) -> Optional[float]:
    if text is None:
        return None
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", str(text))
    try:
        return float(match.group(0)) if match else None
    except ValueError:
        return None


def tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def children(element: ET.Element, name: str) -> list[ET.Element]:
    return [item for item in element.iter() if tag(item).lower() == name.lower()]


def first_text(root: ET.Element, name: str) -> Optional[str]:
    values = children(root, name)
    return (values[0].text or "").strip() if values else None


def custom_data(root: ET.Element) -> dict[str, str]:
    """Read EPU's KeyValueOfstringanyType entries without relying on namespaces."""
    result: dict[str, str] = {}
    for entry in root.iter():
        if not tag(entry).startswith("KeyValueOf"):
            continue
        key = value = None
        for item in entry.iter():
            if tag(item) == "Key":
                key = (item.text or "").strip()
            elif tag(item) == "Value":
                value = (item.text or "").strip()
        if key:
            result[key] = value or ""
    return result


def detector_custom_value(data: dict[str, str], suffix: str, preferred: Optional[str] = None) -> Optional[str]:
    """Find a detector-specific EPU CustomData value across camera-name variants."""
    if preferred and data.get(preferred):
        return data[preferred]
    suffix_lower = suffix.lower()
    matches = [
        value
        for key, value in data.items()
        if key.lower().startswith("detectors[") and key.lower().endswith(suffix_lower) and value
    ]
    return matches[0] if matches else None


def parse_ceta(path: Path, root: ET.Element) -> Report:
    detector = first_text(root, "CommercialName") or first_text(root, "CameraName") or "Ceta"
    report = Report(path, "Ceta fractions XML", direct(detector, "CommercialName / CameraName"))
    sensor_nodes = children(root, "SensorPixelSize")
    pixel_m = number(first_text(root, "SensorPixelSize"))
    if pixel_m is None and sensor_nodes:
        # Ceta writes SensorPixelSize as a nested x/y value, not leaf text.
        pixel_candidates = [number((item.text or "").strip()) for item in sensor_nodes[0].iter()]
        pixel_m = next((item for item in pixel_candidates if item and 1e-12 < item < 1e-6), None)
    frames = number(first_text(root, "RecordedNumberOfFractions"))
    fractions = children(root, "Fraction")
    doses = [number(first_text(item, "TotalDose")) for item in fractions]
    doses = [item for item in doses if item is not None]
    exposures = [number(first_text(item, "ExposureTime")) for item in fractions]
    exposures = [item for item in exposures if item is not None]
    rates = [number(first_text(item, "DoseRate")) for item in fractions]
    rates = [item for item in rates if item is not None]

    report.values["pixel"] = direct(pixel_m * 1e10, "SensorPixelSize (m to A)", "A/px") if pixel_m else manual()
    report.values["voltage"] = manual("Ceta fractions XML does not contain microscope voltage", "kV")
    report.values["cs"] = manual("Ceta fractions XML does not contain Cs", "mm")
    report.values["magnification"] = manual("Ceta fractions XML does not contain magnification")
    report.values["frames"] = direct(int(round(frames)), "RecordedNumberOfFractions") if frames else manual()
    report.values["gain"] = manual("Ceta fractions XML does not contain a gain reference")
    report.values["exposure"] = derived(sum(exposures), "sum of Fraction/ExposureTime", "s") if exposures else manual()
    report.values["total_dose"] = derived(sum(doses), "sum of Fraction/TotalDose", "e-/A^2") if doses else manual()
    report.values["dose_per_frame"] = derived(statistics.mean(doses), "mean of Fraction/TotalDose", "e-/A^2/frame") if doses else manual()
    report.values["dose_rate"] = derived(statistics.mean(rates), "mean of Fraction/DoseRate", "e-/A^2/s") if rates else manual()
    if frames and len(fractions) != round(frames):
        report.warnings.append(f"RecordedNumberOfFractions is {frames:g}, but {len(fractions)} Fraction elements were found.")
    if doses and exposures and rates:
        mismatches = sum(not math.isclose(d, e * r, rel_tol=0.02) for d, e, r in zip(doses, exposures, rates))
        report.checks.append("[OK] Fraction TotalDose agrees with ExposureTime * DoseRate." if not mismatches else f"[WARNING] {mismatches} fraction dose values disagree with exposure * rate.")
    if report.values["total_dose"].value and report.values["total_dose"].value > 100:
        report.warnings.append("Total dose exceeds 100 e-/A^2; verify this is the intended summed movie dose before import.")
    return report


def parse_falcon(path: Path, root: ET.Element, calibrated_pixel: Optional[float] = None) -> Report:
    data = custom_data(root)
    detector = detector_custom_value(data, "].CommercialName", "Detectors[BM-Falcon].CommercialName") or data.get("DetectorCommercialName") or "Falcon"
    report = Report(path, "EPU XML (Falcon)", direct(detector, "CustomData detector commercial name"))
    pixel_nodes = children(root, "pixelSize")
    scale_values = [number((x.text or "").strip()) for node in pixel_nodes for x in children(node, "numericValue")]
    scale_values = [x for x in scale_values if x and 1e-12 < x < 1e-6]
    if not scale_values:
        # Compatibility fallback for EPU versions that omit the pixelSize wrapper.
        scale_values = [number((x.text or "").strip()) for x in children(root, "numericValue")]
        scale_values = [x for x in scale_values if x and 1e-12 < x < 1e-6]
    voltage_v = number(first_text(root, "AccelerationVoltage"))
    frames = number(first_text(root, "NumberOffractions"))
    total = number(detector_custom_value(data, "].TotalDose", "Detectors[BM-Falcon].TotalDose"))
    rate = number(detector_custom_value(data, "].DoseRate", "Detectors[BM-Falcon].DoseRate"))
    exposure = number(detector_custom_value(data, "].ExposureTime", "Detectors[BM-Falcon].ExposureTime"))
    gain = detector_custom_value(data, "].GainReference", "Detectors[BM-Falcon].GainReference")
    magnification = number(first_text(root, "NominalMagnification"))
    # Name the detector after the key the dose came from (fallback: commercial-name key).
    detector_key = next(
        (key.split("]")[0] + "]" for suffix in ("].totaldose", "].commercialname")
         for key in data if key.lower().startswith("detectors[") and key.lower().endswith(suffix)),
        "detector",
    )
    exposure_source = f"{detector_key}.ExposureTime"
    if exposure is None:
        exposure = number(first_text(root, "ExposureTime"))
        exposure_source = "ExposureTime"
    if exposure is not None and exposure <= 0:
        report.warnings.append(f"ExposureTime {exposure:g} s is not positive; it was not used.")
        exposure = None
    pixel_a = scale_values[0] * 1e10 if scale_values else None
    report.values["pixel"] = direct(pixel_a, "SpatialScale numericValue (m to A)", "A/px") if pixel_a else manual()
    report.values["voltage"] = direct(voltage_v / 1000, "AccelerationVoltage (V to kV)", "kV") if voltage_v else manual()
    report.values["cs"] = manual("EPU XML does not contain Cs", "mm")
    report.values["magnification"] = direct(int(round(magnification)), "NominalMagnification") if magnification else manual()
    report.values["frames"] = direct(int(round(frames)), "CameraSpecificInput/FractionationSettings/NumberOffractions") if frames else manual()
    report.values["gain"] = direct(gain, f"{detector_key}.GainReference") if gain else manual()
    report.values["exposure"] = direct(exposure, exposure_source, "s") if exposure else manual()
    resolve_falcon_dose(report, data, detector_key, pixel_a, exposure, total, rate)
    if calibrated_pixel and frames:
        apply_calibrated_pixel(report, pixel_a, calibrated_pixel, exposure)
    total = report.values["total_dose"]
    report.values["dose_per_frame"] = (
        Value(total.value / frames, "UNVERIFIED" if total.status == "UNVERIFIED" else "DERIVED",
              "total dose / NumberOffractions" + (" (total dose unverified)" if total.status == "UNVERIFIED" else ""),
              "e-/A^2/frame")
        if total.value and total.value > 0 and frames else manual()
    )
    epu_common_extras(report, root, data)
    return report


def close(a: Optional[float], b: Optional[float], tol: float = UNIT_REL_TOLERANCE) -> bool:
    if a is None or b is None:
        return False
    if a == b:
        return True
    return b != 0 and math.isclose(a, b, rel_tol=tol)


def area_dose(raw: Optional[float], name: str, report: Report) -> Optional[float]:
    """EPU Dose / DoseOnSample are area-normalised (e-/m^2, around 1e21); return e-/A^2.

    Zero is kept (a blank exposure).  Negative values and values that are not on
    the e-/m^2 scale are rejected with a warning.
    """
    if raw is None:
        return None
    if raw == 0:
        return 0.0
    if raw < 1e10:
        report.warnings.append(f"{name} = {raw:.6g} is not a positive e-/m^2 value; it was not used.")
        return None
    return raw / M2_TO_A2


def dose_unit(value: Optional[float], per_a2: Optional[float], p2: Optional[float]) -> Optional[str]:
    """Name the unit in which `value` equals the area dose `per_a2` (e-/A^2), if any."""
    if value is None or per_a2 is None or p2 is None:
        return None
    if close(value, per_a2 * p2):
        return "e-/px"
    if close(value, per_a2):
        return "e-/A^2"
    return None


def resolve_falcon_dose(report: Report, data: dict[str, str], detector_key: str, pixel_a: Optional[float],
                        exposure: Optional[float], det_total: Optional[float], det_rate: Optional[float]) -> None:
    """Work out the dose on the sample and at the camera from EPU Falcon XML (v2.5).

    EPU writes several dose fields whose units are not labelled:
      DoseOnSample      e-/m^2 on the specimen (the beam), constant for a session
      DoseRate          generic rate on the specimen, e-/px/s (as EPU's Measure Dose shows)
      Dose              e-/m^2 that reached the camera, after specimen and energy filter
      DoseOnCamera      the same camera dose in e-/px
      Detectors[..].TotalDose / DoseRate   camera dose (e-/px) and rate (e-/px/s) on
                        EF-Falcon Krios data; e-/A^2 on the sample on some other set-ups
    A unit is accepted only when it reproduces another field within 2 %.  The import
    dose (cryoSPARC "Total exposure dose") is the dose on the sample.  Without
    DoseOnSample the value is marked UNVERIFIED unless two independent fields agree.
    """
    p2 = pixel_a * pixel_a if pixel_a else None
    sample_a2 = area_dose(number(data.get("DoseOnSample")), "DoseOnSample", report)
    if sample_a2 == 0:
        report.warnings.append("DoseOnSample is zero; it was not used.")
        sample_a2 = None
    camera_a2 = area_dose(number(data.get("Dose")), "Dose", report)
    generic_rate = number(data.get("DoseRate"))
    dose_on_camera = number(data.get("DoseOnCamera"))
    if p2 is not None and abs(p2 - 1) < 2 * UNIT_REL_TOLERANCE:
        report.warnings.append("Pixel size is close to 1 A, so e-/px and e-/A^2 cannot be told apart by these checks.")
    if det_total is not None and det_total < 0:
        report.warnings.append(f"{detector_key}.TotalDose {det_total:.6g} is negative; it was not used.")
        det_total = None
    if generic_rate is not None and generic_rate <= 0:
        report.warnings.append(f"DoseRate {generic_rate:.6g} is not positive; it was not used.")
        generic_rate = None
    rate_dose = generic_rate * exposure if generic_rate is not None and exposure else None
    missing = [name for name, item in (("DoseRate", generic_rate), ("ExposureTime", exposure), ("pixel size", p2)) if item is None]

    # 1. Dose on the sample from DoseOnSample, validated by the generic DoseRate.
    if sample_a2 is not None:
        rate_unit = None
        if not missing:
            rate_unit = {"e-/px": "e-/px/s", "e-/A^2": "e-/A^2/s"}.get(dose_unit(rate_dose, sample_a2, p2) or "")
        if rate_unit:
            divisor = " / pixel^2" if rate_unit == "e-/px/s" else ""
            report.values["total_dose"] = derived(
                sample_a2, f"DoseOnSample / 1e20, validated by DoseRate * ExposureTime{divisor}", "e-/A^2")
            report.checks.append(
                f"[OK] Dose on sample {sample_a2:.4g} e-/A^2 (DoseOnSample) agrees with DoseRate {generic_rate:.4g} "
                f"{rate_unit} * {exposure:g} s{divisor} within 2 %.")
        elif missing:
            reason = ", ".join(missing) + " missing"
            report.values["total_dose"] = derived(sample_a2, f"DoseOnSample / 1e20 (no cross-check: {reason})", "e-/A^2")
            report.warnings.append(f"Dose on sample taken from DoseOnSample without a DoseRate cross-check ({reason}).")
        else:
            report.values["total_dose"] = manual("DoseOnSample and DoseRate disagree; inspect the XML before import", "e-/A^2")
            report.warnings.append(
                f"Dose mismatch: DoseOnSample implies {sample_a2:.6g} e-/A^2, but DoseRate * ExposureTime / pixel^2 "
                f"implies {rate_dose / p2:.6g} e-/A^2 ({rate_dose:.6g} if DoseRate is per A^2).")

    # 2. Dose at the camera and the unit of the detector-specific fields.
    det_unit, det_reference = "unverified", None
    if det_total is not None:
        for reference_name, reference in (("at camera", camera_a2), ("on sample", sample_a2)):
            unit = dose_unit(det_total, reference, p2)
            if unit:
                det_unit, det_reference = f"{unit} {reference_name}", reference_name
                break
    if camera_a2 is not None:
        report.values["camera_dose"] = derived(camera_a2, "Dose / 1e20 (e-/m^2 to e-/A^2): dose that reached the camera", "e-/A^2")
        report.extras["dose_on_camera_e_per_A2"] = camera_a2
        if p2:
            report.extras["dose_on_camera_e_per_px"] = camera_a2 * p2
            if dose_on_camera is not None:
                unit = dose_unit(dose_on_camera, camera_a2, p2)
                report.checks.append(
                    f"[INFO] DoseOnCamera {dose_on_camera:.4g} is in e-/px (Dose / 1e20 * pixel^2)." if unit == "e-/px"
                    else f"[INFO] DoseOnCamera {dose_on_camera:.4g} is in e-/A^2." if unit
                    else f"[WARNING] DoseOnCamera {dose_on_camera:.4g} matches Dose in neither e-/px nor e-/A^2.")
    if det_total is not None:
        if det_reference:
            report.checks.append(f"[INFO] {detector_key}.TotalDose {det_total:.4g} is {det_unit}.")
        if det_rate is not None and exposure:
            report.checks.append(
                f"[OK] {detector_key}.TotalDose agrees with its DoseRate * ExposureTime." if close(det_total, det_rate * exposure)
                else f"[WARNING] {detector_key}.TotalDose differs from its DoseRate * ExposureTime.")

    # 3. No DoseOnSample: use the generic DoseRate if possible, but say how sure we are.
    if "total_dose" not in report.values:
        candidate = rate_dose / p2 if rate_dose is not None and p2 else None   # assumes DoseRate is e-/px/s on the sample
        if candidate is not None:
            unit = dose_unit(det_total, candidate, p2)
            if unit == "e-/A^2":
                # TotalDose (e-/A^2) and DoseRate (e-/px/s) give the same dose in different units.
                report.values["total_dose"] = derived(
                    candidate, f"DoseRate * ExposureTime / pixel^2, equal to {detector_key}.TotalDose", "e-/A^2")
                det_unit = "e-/A^2 on sample (no DoseOnSample)"
                report.warnings.append("No DoseOnSample: dose on sample from DoseRate (e-/px/s) and TotalDose (e-/A^2), which agree.")
            else:
                report.values["total_dose"] = Value(
                    candidate, "UNVERIFIED", "DoseRate * ExposureTime / pixel^2, DoseRate assumed e-/px/s on the sample", "e-/A^2")
                report.warnings.append(
                    f"No DoseOnSample: dose on sample {candidate:.4g} e-/A^2 assumes DoseRate is e-/px/s on the sample "
                    "(true for EPU Falcon data checked so far). Confirm with the dose rate measured over vacuum.")
            if camera_a2 is not None and candidate < camera_a2 * (1 - UNIT_REL_TOLERANCE):
                report.warnings.append(f"The dose on sample ({candidate:.4g}) is below the camera dose ({camera_a2:.4g} e-/A^2); "
                                       "the DoseRate unit assumption is probably wrong.")
        elif camera_a2 is not None:
            report.values["total_dose"] = manual(
                f"only the dose at the camera is recorded ({camera_a2:.4g} e-/A^2, a lower bound); "
                "use the dose rate measured over vacuum", "e-/A^2")
            report.warnings.append("No DoseOnSample or DoseRate: the dose on the sample is higher than the camera dose; "
                                   "supply it from the vacuum dose-rate measurement.")
        elif det_total:
            report.values["total_dose"] = Value(det_total, "UNVERIFIED", f"{detector_key}.TotalDose, unit assumed e-/A^2", "e-/A^2")
            alternative = (f" If it is e-/px at the camera (as on EPU Krios EF-Falcon data), the camera dose is "
                           f"{det_total / p2:.4g} e-/A^2 and the dose on sample is higher still." if p2 else "")
            report.warnings.append(
                f"{detector_key}.TotalDose unit cannot be checked (no Dose, DoseOnSample or DoseRate in this XML)."
                f"{alternative} Confirm against the dose rate measured over vacuum.")
        else:
            report.values["total_dose"] = manual(unit="e-/A^2")
    if det_total is not None:
        report.extras["detector_total_dose_unit"] = det_unit

    total = report.values["total_dose"]
    if total.value is not None and det_total is not None and not close(det_total, total.value):
        report.checks.append(
            f"[NOTE] {detector_key}.TotalDose ({det_total:.4g}) is not the import dose; v2.4 and earlier reported it as e-/A^2.")
    report.values["dose_rate"] = (
        Value(total.value / exposure, total.status, "total dose / ExposureTime", "e-/A^2/s")
        if total.value is not None and exposure else manual(unit="e-/A^2/s")
    )
    if total.status == "DERIVED" and total.value is not None and p2 and exposure:
        report.extras["dose_rate_on_sample_e_per_px_s"] = total.value * p2 / exposure

    # 4. Transmission through specimen (and energy filter, if any).
    if camera_a2 is not None and sample_a2:
        ratio = camera_a2 / sample_a2
        report.extras["camera_to_sample_ratio"] = ratio
        report.extras["minus_ln_transmission"] = -math.log(ratio) if ratio > 0 else None
        if ratio > 1 + 2.5 * UNIT_REL_TOLERANCE:
            report.warnings.append(f"Camera dose is {100 * (ratio - 1):.0f} % above the dose on sample; check the dose calibration.")


def apply_calibrated_pixel(report: Report, nominal: Optional[float], calibrated: float,
                           exposure: Optional[float]) -> None:
    """v2.7: use a facility-calibrated pixel for a Falcon movie and re-express doses per A^2.

    EPU derives its e-/A^2 values from counts per pixel with its nominal pixel, so the
    dose per A^2 for the calibrated pixel is EPU's value * (nominal / calibrated)^2.
    Per-pixel values (e-/px, e-/px/s) and the camera/sample ratio do not change.
    """
    report.values["pixel"] = Value(calibrated, "MANUAL", "--pixel-size (facility-calibrated value supplied by user)", "A/px")
    if not nominal:
        report.warnings.append("No EPU pixel size in the XML, so the doses could not be re-expressed for --pixel-size.")
        return
    scale = (nominal / calibrated) ** 2
    diff = (nominal - calibrated) / calibrated * 100
    report.extras["epu_nominal_movie_pixel_A"] = nominal
    report.checks.append(f"[INFO] EPU nominal pixel {nominal:.6g} A is {diff:+.2f} % from the calibrated {calibrated:g} A; "
                         f"doses per A^2 multiplied by {scale:.4f}.")
    if abs(diff) > 5:
        report.warnings.append(f"--pixel-size {calibrated:g} A differs from EPU's {nominal:.6g} A by {diff:+.1f} %; "
                               "check the value and that it is for this magnification.")
    total = report.values.get("total_dose")
    if total is not None and total.value is not None:
        report.extras["epu_total_dose_e_per_A2"] = total.value
        report.extras["total_dose_with_calibrated_pixel"] = total.value * scale
        report.values["total_dose"] = Value(total.value * scale, total.status,
                                            total.source + "; re-expressed for the calibrated pixel", "e-/A^2")
        if exposure:
            report.values["dose_rate"] = Value(total.value * scale / exposure, total.status,
                                               "total dose (calibrated pixel) / ExposureTime", "e-/A^2/s")
    camera = report.values.get("camera_dose")
    if camera is not None and camera.value is not None:
        report.values["camera_dose"] = Value(camera.value * scale, camera.status,
                                             camera.source + "; re-expressed for the calibrated pixel", "e-/A^2")
        report.extras["dose_on_camera_e_per_A2"] = camera.value * scale


def stage_tilt_deg(root: ET.Element) -> Optional[float]:
    """Stage alpha tilt from stage/Position/A (EPU stores radians)."""
    positions = [pos for stage in children(root, "stage") for pos in children(stage, "Position")] or children(root, "Position")
    for position in positions:
        for item in position:
            if tag(item) == "A":
                value = number(item.text)
                if value is None:
                    continue
                # |alpha| above ~1.25 rad (72 deg) is beyond the stage range, so the value is already in degrees.
                return value if abs(value) > 1.25 else math.degrees(value)
    return None


def epu_common_extras(report: Report, root: ET.Element, data: dict[str, str]) -> None:
    """Per-exposure EPU values shared by the Falcon and K2/K3 readers."""
    applied_defocus = number(data.get("AppliedDefocus"))
    report.extras["applied_defocus_um"] = applied_defocus * 1e6 if applied_defocus is not None else None
    beam_shift_nodes = children(root, "BeamShift")
    if beam_shift_nodes:
        report.extras["beam_shift_x"] = number(first_text(beam_shift_nodes[0], "_x"))
        report.extras["beam_shift_y"] = number(first_text(beam_shift_nodes[0], "_y"))
    report.extras["acquisition_time"] = first_text(root, "acquisitionDateTime")
    report.extras["energy_slit_eV"] = number(first_text(root, "EnergySelectionSlitWidth"))
    report.extras["instrument"] = first_text(root, "InstrumentModel")
    report.extras["stage_tilt_deg"] = stage_tilt_deg(root)


def parse_mdoc(path: Path) -> Report:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in raw and not raw.lstrip().startswith("["):
            key, value = raw.split("=", 1)
            values.setdefault(key.strip(), value.strip())
    title = path.read_text(encoding="utf-8", errors="replace").splitlines()[0] if path.stat().st_size else ""
    detector_name = "K3" if re.search(r"\bK3\b", title, re.I) else "Unknown (SerialEM camera)"
    report = Report(path, "SerialEM MDOC", direct(detector_name, "MDOC header"))
    px, voltage, mag = number(values.get("PixelSpacing")), number(values.get("Voltage")), number(values.get("Magnification"))
    frames, exposure, rate = number(values.get("NumSubFrames")), number(values.get("ExposureTime")), number(values.get("DoseRate"))
    exposure_dose = number(values.get("ExposureDose"))
    report.values["pixel"] = direct(px, "PixelSpacing", "A/px") if px else manual()
    report.values["voltage"] = direct(voltage, "Voltage", "kV") if voltage else manual()
    report.values["cs"] = manual("SerialEM MDOC does not contain Cs", "mm")
    report.values["magnification"] = direct(int(round(mag)), "Magnification") if mag else manual()
    report.values["frames"] = direct(int(round(frames)), "NumSubFrames") if frames else manual()
    report.values["gain"] = direct(values["GainReference"], "GainReference") if values.get("GainReference") else manual()
    report.values["exposure"] = direct(exposure, "ExposureTime", "s") if exposure else manual()
    report.values["dose_rate"] = direct(rate, "DoseRate (assumed e-/physical-pixel/s)", "e-/pixel/s") if rate else manual()
    if exposure_dose and exposure_dose > 0:
        report.values["total_dose"] = direct(exposure_dose, "ExposureDose", "e-/A^2")
    elif px and exposure and rate:
        total = rate * exposure / (px * px)
        report.values["total_dose"] = derived(total, "DoseRate * ExposureTime / PixelSpacing^2; assumes e-/physical-pixel/s", "e-/A^2")
        report.warnings.append("K3 dose is derived using the standard SerialEM e-/physical-pixel/s convention; confirm camera calibration if this convention differs.")
    else:
        report.values["total_dose"] = manual()
    total = report.values["total_dose"].value
    report.values["dose_per_frame"] = derived(total / frames, "total dose / NumSubFrames", "e-/A^2/frame") if total and frames else manual()
    if exposure_dose == 0:
        report.warnings.append("ExposureDose is zero and was not used as the total dose.")
    return report


def parse_ceta_epu_image(path: Path, root: ET.Element) -> Report:
    """Parse a single integrated Ceta/Ceta-F image written by EPU.

    These MicroscopeImage XML files differ from Ceta fractions XML.  They carry
    the calibrated image pixel size under SpatialScale/pixelSize and microscope
    settings under microscopeData.  For dose, EPU stores DoseRate in CustomData
    in camera-pixel units and DoseOnSample as a very large area-normalized value.

    We only report a total sample dose when the independent metadata paths agree:
      1. DoseRate * ExposureTime / pixel_size_A^2
      2. DoseOnSample / 1e20

    Agreement within 2% validates the unit interpretation and guards against
    silently using an unrelated dose-like field.  Movie-only fraction and gain
    fields remain MANUAL because this XML describes one integrated image.
    """
    data = custom_data(root)
    detector = (
        detector_custom_value(data, "].CommercialName", "Detectors[BM-Ceta].CommercialName")
        or data.get("DetectorCommercialName")
        or first_text(root, "CameraName")
        or "Ceta"
    )
    report = Report(path, "EPU XML (Ceta single image)", direct(detector, "CustomData detector commercial name"))

    pixel_nodes = children(root, "pixelSize")
    scale_values = [
        number((item.text or "").strip())
        for node in pixel_nodes
        for item in children(node, "numericValue")
    ]
    scale_values = [item for item in scale_values if item and 1e-12 < item < 1e-6]

    pixel_a = scale_values[0] * 1e10 if scale_values else None
    voltage_v = number(first_text(root, "AccelerationVoltage"))
    magnification = number(first_text(root, "NominalMagnification"))
    exposure = number(first_text(root, "ExposureTime"))
    camera_dose_rate = number(data.get("DoseRate"))
    dose_on_sample_raw = number(data.get("DoseOnSample"))

    report.values["pixel"] = direct(pixel_a, "SpatialScale/pixelSize numericValue (m to A)", "A/px") if pixel_a else manual()
    report.values["voltage"] = direct(voltage_v / 1000, "AccelerationVoltage (V to kV)", "kV") if voltage_v else manual()
    report.values["cs"] = manual("EPU XML does not contain Cs", "mm")
    report.values["magnification"] = direct(int(round(magnification)), "NominalMagnification") if magnification else manual()
    report.values["frames"] = manual("single integrated Ceta image; no movie fraction count")
    report.values["gain"] = manual("single-image EPU XML does not provide an importable movie gain reference")
    report.values["exposure"] = direct(exposure, "camera ExposureTime", "s") if exposure else manual()
    report.values["dose_per_frame"] = manual("single integrated image; no movie fractions")

    # EPU's Ceta single-image DoseRate behaves as e-/camera-pixel/s in the
    # supplied metadata. Convert it to e-/A^2/s only when the calibrated pixel
    # size is available.
    dose_rate_a2 = None
    if camera_dose_rate is not None and pixel_a:
        dose_rate_a2 = camera_dose_rate / (pixel_a * pixel_a)
        report.values["dose_rate"] = derived(
            dose_rate_a2,
            "CustomData DoseRate / pixel_size^2; validated against DoseOnSample when available",
            "e-/A^2/s",
        )
    else:
        report.values["dose_rate"] = manual(
            "requires CustomData DoseRate and calibrated pixel size",
            "e-/A^2/s",
        )

    total_from_rate = dose_rate_a2 * exposure if dose_rate_a2 is not None and exposure else None

    # In these EPU MicroscopeImage XML files DoseOnSample is stored on an m^-2
    # area basis.  1 m^2 = 1e20 A^2, so divide by 1e20 to obtain e-/A^2.
    dose_on_sample_a2 = dose_on_sample_raw / 1e20 if dose_on_sample_raw is not None else None

    if dose_on_sample_a2 is not None and total_from_rate is not None:
        if math.isclose(dose_on_sample_a2, total_from_rate, rel_tol=0.02):
            report.values["total_dose"] = derived(
                dose_on_sample_a2,
                "CustomData DoseOnSample / 1e20 (m^-2 to A^-2), validated by DoseRate * ExposureTime / pixel_size^2",
                "e-/A^2",
            )
            report.checks.append(
                "[OK] DoseOnSample agrees with DoseRate * ExposureTime / pixel_size^2 within 2%."
            )
        else:
            report.values["total_dose"] = manual(
                "DoseOnSample disagrees with DoseRate * ExposureTime / pixel_size^2; inspect metadata before use",
                "e-/A^2",
            )
            report.warnings.append(
                f"Dose mismatch: DoseOnSample implies {dose_on_sample_a2:.6g} e-/A^2, "
                f"while DoseRate * ExposureTime / pixel_size^2 implies {total_from_rate:.6g} e-/A^2."
            )
    elif total_from_rate is not None:
        report.values["total_dose"] = derived(
            total_from_rate,
            "CustomData DoseRate * ExposureTime / pixel_size^2; DoseOnSample unavailable for cross-check",
            "e-/A^2",
        )
        report.warnings.append(
            "Total dose was derived from DoseRate, exposure time, and pixel size because DoseOnSample was unavailable for an independent cross-check."
        )
    else:
        report.values["total_dose"] = manual(
            "requires DoseOnSample plus DoseRate/exposure/pixel size for validation, or enough fields for a derived estimate",
            "e-/A^2",
        )

    report.warnings.append(
        "Single integrated Ceta image: fraction-count and movie gain-reference fields are intentionally not inferred."
    )
    return report


def parse_epu_gatan(path: Path, root: ET.Element, data: dict[str, str], detector: str,
                    calibrated_pixel: Optional[float] = None) -> Report:
    """Parse an EPU MicroscopeImage XML written for a Gatan K2/K3 movie.

    The XML describes EPU's integrated (often binned) image, not the movie:
      * pixelSize is for that image; movie pixel = pixelSize / Binning, and the
        movie size is ReadoutArea * Binning (checked against your movies).
      * EPU's pixelSize is the microscope's nominal magnification calibration,
        which can differ by a few % from a facility-calibrated value.
      * CustomData Dose is e-/m^2 (divide by 1e20 for e-/A^2).
      * CustomData DoseRate is validated by recomputing Dose from it under two
        unit hypotheses (per super-resolution pixel or per movie pixel).
    With --pixel-size, the dose is also re-expressed with the calibrated pixel.
    """
    report = Report(path, "EPU XML (Gatan K2/K3 movie)", direct(detector, "CustomData detector commercial name"))
    scale_values = [
        number((item.text or "").strip())
        for node in children(root, "pixelSize")
        for item in children(node, "numericValue")
    ]
    scale_values = [item for item in scale_values if item and 1e-12 < item < 1e-6]
    image_px = scale_values[0] * 1e10 if scale_values else None
    binning_nodes = children(root, "Binning")
    binning = number(first_text(binning_nodes[0], "x")) if binning_nodes else None
    binning = binning or 1.0
    readout_nodes = children(root, "ReadoutArea")
    readout_w = number(first_text(readout_nodes[0], "width")) if readout_nodes else None
    readout_h = number(first_text(readout_nodes[0], "height")) if readout_nodes else None
    sr_factor = number(data.get("SuperResolutionFactor")) or 1.0
    voltage_v = number(first_text(root, "AccelerationVoltage"))
    magnification = number(first_text(root, "NominalMagnification"))
    frames = number(first_text(root, "NumberOffractions"))
    exposure = number(first_text(root, "ExposureTime"))
    dose_raw = number(data.get("Dose")) or number(data.get("DoseOnSample"))
    dose_rate_raw = number(data.get("DoseRate"))

    movie_px = image_px / binning if image_px else None
    report.extras["image_pixel_A"] = image_px
    report.extras["binning"] = binning
    if readout_w and readout_h:
        report.extras["movie_size_px"] = f"{int(round(readout_w * binning))}x{int(round(readout_h * binning))}"
    report.extras["epu_nominal_movie_pixel_A"] = movie_px

    if calibrated_pixel:
        report.values["pixel"] = Value(calibrated_pixel, "MANUAL", "--pixel-size (calibrated value supplied by user)", "A/px")
        if movie_px:
            diff = (movie_px - calibrated_pixel) / calibrated_pixel * 100
            report.checks.append(f"[INFO] EPU nominal movie pixel {movie_px:.4f} A ({diff:+.1f} % vs calibrated {calibrated_pixel:g} A).")
    else:
        report.values["pixel"] = derived(movie_px, f"EPU nominal pixelSize / Binning ({image_px:.4f} A / {binning:g})", "A/px") if movie_px else manual()
        if movie_px:
            report.warnings.append("Pixel size is EPU's nominal calibration; prefer the facility-calibrated value (--pixel-size) if known.")
    report.values["voltage"] = direct(voltage_v / 1000, "AccelerationVoltage (V to kV)", "kV") if voltage_v else manual()
    report.values["cs"] = manual("EPU XML does not contain Cs", "mm")
    report.values["magnification"] = direct(int(round(magnification)), "NominalMagnification") if magnification else manual()
    report.values["frames"] = direct(int(round(frames)), "FractionationSettings/NumberOffractions") if frames else manual()
    report.values["gain"] = manual("EPU XML for K2/K3 does not name the gain reference")
    report.values["exposure"] = direct(exposure, "camera ExposureTime", "s") if exposure else manual()

    epu_total = dose_raw / 1e20 if dose_raw else None
    report.extras["epu_total_dose_e_per_A2"] = epu_total
    sample_raw, camera_raw = number(data.get("DoseOnSample")), number(data.get("Dose"))
    if sample_raw and camera_raw and not close(sample_raw, camera_raw):
        report.warnings.append(
            f"Dose ({camera_raw / 1e20:.4g} e-/A^2) and DoseOnSample ({sample_raw / 1e20:.4g} e-/A^2) differ; Dose is used here. "
            "On EPU Falcon data Dose is the dose at the camera and DoseOnSample the dose on the specimen (v2.5); "
            "check which one applies to this K2/K3 set-up.")
    rate_movie_px = None
    if dose_rate_raw and exposure and movie_px:
        hypotheses = [
            ("per super-resolution pixel", dose_rate_raw * sr_factor * sr_factor),
            ("per movie pixel", dose_rate_raw),
        ]
        for label, rate in hypotheses:
            recomputed = rate * exposure / (movie_px * movie_px)
            if epu_total and math.isclose(recomputed, epu_total, rel_tol=0.02):
                rate_movie_px = rate
                report.checks.append(f"[OK] DoseRate is {label}: DoseRate*ExposureTime/pixel^2 = {recomputed:.4g} vs Dose {epu_total:.4g} e-/A^2 (within 2 %).")
                break
        if rate_movie_px is None:
            report.warnings.append("DoseRate could not be reconciled with Dose under either unit hypothesis; dose rate not reported.")
    report.extras["dose_rate_e_per_movie_px_s"] = rate_movie_px
    report.values["dose_rate"] = derived(rate_movie_px, "CustomData DoseRate, converted to movie pixels", "e-/px/s") if rate_movie_px else manual()

    if calibrated_pixel and rate_movie_px and exposure:
        total = rate_movie_px * exposure / (calibrated_pixel * calibrated_pixel)
        report.values["total_dose"] = derived(total, "dose rate (e-/px/s) * exposure / calibrated pixel^2", "e-/A^2")
        report.extras["total_dose_with_calibrated_pixel"] = total
    elif epu_total:
        report.values["total_dose"] = direct(epu_total, "CustomData Dose / 1e20 (EPU, with its nominal pixel)", "e-/A^2")
    else:
        report.values["total_dose"] = manual()
    total = report.values["total_dose"].value
    report.values["dose_per_frame"] = derived(total / frames, "total dose / NumberOffractions", "e-/A^2/frame") if total and frames else manual()

    epu_common_extras(report, root, data)
    return report


def parse_file(path: Path, calibrated_pixel: Optional[float] = None) -> Report:
    if path.suffix.lower() == ".mdoc":
        return parse_mdoc(path)
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"cannot parse XML: {exc}") from exc
    names = " ".join(filter(None, [first_text(root, "CommercialName"), first_text(root, "CameraName")]))

    # Ceta fraction XML has Fraction elements and uses the dedicated fractions parser.
    if children(root, "Fraction"):
        return parse_ceta(path, root)

    data = custom_data(root)
    custom_text = (" ".join(data.keys()) + " " + " ".join(data.values())).lower()

    # v2.4: decide by the detector's commercial name first.  K3 EPU XML also has
    # "CetaFramesSummed"/"CetaNoiseReductionEnabled" keys, so key text alone is unsafe.
    commercial = data.get("DetectorCommercialName") or detector_custom_value(data, "].CommercialName") or ""
    commercial_lower = commercial.lower()
    if "falcon" in commercial_lower:
        return parse_falcon(path, root, calibrated_pixel)
    if "ceta" in commercial_lower:
        return parse_ceta_epu_image(path, root)
    if re.search(r"\bk[23]\b|gatan|bioquantum", commercial_lower):
        return parse_epu_gatan(path, root, data, commercial, calibrated_pixel)

    # EPU single-image Ceta/Ceta-F XML identifies the detector in CustomData.
    if "ceta" in names.lower() or "ceta" in custom_text:
        return parse_ceta_epu_image(path, root)

    if "falcon" in custom_text:
        return parse_falcon(path, root, calibrated_pixel)

    raise ValueError(
        "unrecognized XML: supported formats are Ceta fractions XML, "
        "Ceta EPU single-image XML, Falcon EPU XML, Gatan K2/K3 EPU XML and SerialEM MDOC"
    )


def print_value(label: str, value: Value) -> None:
    unit = f" {value.unit}" if value.value is not None and value.unit else ""
    print(f"  {label:<27} {value.display() + unit:<24} [{value.status}]  {value.source}")


def print_report(report: Report) -> None:
    v = report.values
    print(f"\n{'=' * 92}\nFILE: {report.path}\nFORMAT: {report.format}\nDETECTOR: {report.detector.display()} [{report.detector.status}]  {report.detector.source}")
    print("\nSCIPION - Import Movies")
    for label, key in [("Pixel size", "pixel"), ("Microscope voltage", "voltage"), ("Spherical aberration", "cs"), ("Magnification", "magnification"), ("Dose per frame", "dose_per_frame"), ("Number of fractions", "frames")]:
        print_value(label, v[key])
    print_value("Initial dose", direct(0.0, "default unless a pre-exposure is known", "e-/A^2"))
    print("\nCRYOSPARC - Import Movies")
    for label, key in [("Pixel size", "pixel"), ("Accelerating voltage", "voltage"), ("Spherical aberration", "cs"), ("Total exposure dose", "total_dose"), ("Gain reference", "gain")]:
        print_value(label, v[key])
    print("\nOTHER / VALIDATION")
    print_value("Exposure time", v["exposure"])
    print_value("Dose rate on sample" if "camera_dose" in v else "Dose rate", v["dose_rate"])
    if "camera_dose" in v:
        print_value("Dose at camera", v["camera_dose"])
    for key, item in report.extras.items():
        if item is not None:
            shown = f"{item:.6g}" if isinstance(item, float) else str(item)
            print(f"  {key:<27} {shown}")
    for check in report.checks:
        print(f"  {check}")
    for warning in report.warnings:
        print(f"  [WARNING] {warning}")
    manual_names = [name for name in ("pixel", "voltage", "cs", "magnification", "frames", "total_dose") if v[name].value is None]
    if manual_names:
        print("  [WARNING] Supply manually: " + ", ".join(manual_names) + ".")


def report_value(report: Report, key: str) -> Any:
    if key == "detector":
        return report.detector.value
    item = report.values.get(key)
    return item.value if item is not None else None


def normalized_signature_value(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 8)
    return value


def acquisition_signature(report: Report) -> tuple[Any, ...]:
    """Settings that should define a homogeneous movie-import group."""
    return tuple(
        normalized_signature_value(report_value(report, key))
        for key in ("detector", "pixel", "voltage", "magnification", "frames", "exposure", "gain")
    )


def signature_groups(reports: list[Report]) -> dict[tuple[Any, ...], list[Report]]:
    grouped: dict[tuple[Any, ...], list[Report]] = {}
    for report in reports:
        grouped.setdefault(acquisition_signature(report), []).append(report)
    return grouped


def numeric_summary(reports: list[Report], key: str) -> tuple[list[float], list[Report], set[int]]:
    pairs = [(float(report_value(report, key)), report) for report in reports if report_value(report, key) is not None]
    values = [item[0] for item in pairs]
    value_reports = [item[1] for item in pairs]
    outliers = robust_outlier_indexes(values) if key in DOSE_KEYS else set()
    return values, value_reports, outliers


def print_dose_summary(reports: list[Report], key: str, label: str, outlier_limit: int, informational: bool = False) -> None:
    values, value_reports, outliers = numeric_summary(reports, key)
    if not values:
        print(f"  [MANUAL] {label}: not present in supplied metadata")
        return
    median = statistics.median(values)
    q1, q3 = percentile(values, 0.25), percentile(values, 0.75)
    p05, p95 = percentile(values, 0.05), percentile(values, 0.95)
    mad = statistics.median(abs(item - median) for item in values)
    central_width = (p95 - p05) / max(abs(median), 1e-12)
    outlier_fraction = len(outliers) / len(values)
    if informational:
        # v2.5: spread is expected (e.g. camera dose follows ice thickness); report, don't judge.
        state = "[INFO]"
    elif not outliers and central_width <= 0.05:
        state = "[OK]"
    elif outlier_fraction <= 0.02 and central_width <= 0.05:
        state = "[OK WITH OUTLIERS]"
    else:
        state = "[WARNING]"
    print(
        f"  {state} {label}: n={len(values)}; median={median:.6g}; "
        f"Q1-Q3={q1:.6g}-{q3:.6g}; P05-P95={p05:.6g}-{p95:.6g}; "
        f"MAD={mad:.6g}; range={min(values):.6g}-{max(values):.6g}; "
        f"outliers={len(outliers)} (relative to this summary group)"
    )
    for index in sorted(outliers, key=lambda item: values[item])[:outlier_limit]:
        print(f"    [OUTLIER] {values[index]:.6g}  {value_reports[index].path}")
    if len(outliers) > outlier_limit:
        print(f"    ... {len(outliers) - outlier_limit} more; use --table to export all per-movie values.")
    if outliers:
        print("    Statistical flags are for inspection, not automatic movie exclusion.")


def print_recommended_import(reports: list[Report]) -> None:
    groups = signature_groups(reports)
    print("\nRECOMMENDED REPRESENTATIVE IMPORT PARAMETERS")
    if len(groups) == 1:
        print_import_block(reports)
        return
    # v2.5: files without a fraction count are single images (atlas, grid square,
    # foil hole), not movies; recommend for the movie group(s) only.
    movie_groups = sorted((members for signature, members in groups.items() if signature[4] is not None), key=len, reverse=True)
    images = sum(len(members) for signature, members in groups.items() if signature[4] is None)
    if not movie_groups:
        print(f"  [WARNING] {len(groups)} acquisition signatures and no movie group (no fraction count); supply import values manually.")
        return
    if images:
        print(f"  [INFO] {images} single-image file(s) without movie fractions (atlas / grid-square / foil-hole images) left out.")
    if len(movie_groups) > 1:
        print(f"  [WARNING] {len(movie_groups)} different movie acquisition signatures; import each group separately.")
    for index, members in enumerate(movie_groups, 1):
        if len(movie_groups) > 1:
            print(f"\n  MOVIE GROUP {index} (n={len(members)})")
        print_import_block(members)


def print_import_block(reports: list[Report]) -> None:
    def median_value(key: str) -> Optional[float]:
        values = [float(report_value(report, key)) for report in reports if report_value(report, key) is not None]
        return statistics.median(values) if values else None

    detector_values = sorted({str(report.detector.value) for report in reports if report.detector.value is not None})
    gain_values = sorted({str(report.values["gain"].value) for report in reports if report.values["gain"].value is not None})
    detector = detector_values[0] if len(detector_values) == 1 else "MIXED"
    gain = gain_values[0] if len(gain_values) == 1 else ("NOT FOUND" if not gain_values else "MIXED")
    print(f"  Detector                    {detector}")
    print(f"  Pixel size                  {format_optional(median_value('pixel'))} A/px")
    print(f"  Voltage                     {format_optional(median_value('voltage'))} kV")
    print("  Spherical aberration (Cs)   MANUAL - not present in supplied metadata")
    print(f"  Magnification               {format_optional(median_value('magnification'))}")
    print(f"  Fractions                   {format_optional(median_value('frames'))}")
    print(f"  Exposure time               {format_optional(median_value('exposure'))} s")
    print(f"  Scipion dose/fraction       {format_optional(median_value('dose_per_frame'))} e-/A^2/frame")
    total_dose = median_value("total_dose")
    totals = [report.values["total_dose"] for report in reports if "total_dose" in report.values]
    statuses = {item.status for item in totals}
    on_sample = bool(totals) and all(item.source.startswith("DoseOnSample") and item.status == "DERIVED" for item in totals)
    if "UNVERIFIED" in statuses:
        print("  [WARNING] Dose/fraction and total dose rest on an unverified dose unit; see the per-file warnings.")
    print(f"  CryoSPARC total dose        {format_optional(total_dose)} e-/A^2" + ("  (dose on sample)" if on_sample else ""))
    if "UNVERIFIED" in statuses:
        print("  [WARNING] Total dose could not be verified from the XML; confirm it with the vacuum dose-rate measurement.")
    if "MANUAL" in statuses and total_dose is None:
        print("  [WARNING] No dose on sample in the metadata; supply it from the vacuum dose-rate measurement.")
    camera = median_value("camera_dose")
    if camera is not None:
        print(f"  Dose at camera (median)     {camera:.6g} e-/A^2  (after the specimen and any energy filter; not for import)")
    rate_px = [float(r.extras["dose_rate_on_sample_e_per_px_s"]) for r in reports if r.extras.get("dose_rate_on_sample_e_per_px_s") is not None]
    if rate_px:
        print(f"  Dose rate on sample         {statistics.median(rate_px):.6g} e-/px/s  (compare with EPU Measure Dose)")
    tilts = [round(float(r.extras["stage_tilt_deg"]), 1) for r in reports if r.extras.get("stage_tilt_deg") is not None]
    if tilts:
        counts = {value: tilts.count(value) for value in sorted(set(tilts))}
        print("  Stage tilt (deg)            " + ", ".join(f"{value:g} (n={n})" for value, n in counts.items()))
    print(f"  Gain reference              {gain}")
    hint = None
    movies = any(report.path.suffix.lower() == ".xml" and report_value(report, "frames") is not None for report in reports)
    if movies:
        hint = xml_suffix_hint(reports)
        if hint:
            print(f"  CryoSPARC XML cuts          input suffix {len(hint.movie_suffix)} ('{hint.movie_suffix}'), "
                  f"XML suffix {len(hint.xml_suffix)} ('{hint.xml_suffix}'), both prefixes 0 "
                  f"({hint.found}/{hint.checked} sampled XML files)")
        else:
            print("  CryoSPARC XML suffix cut    NOT FOUND - no movie file beside the sampled XML files; "
                  "count the characters the movie name has after the XML name")
    if "eer" in gain.lower() or (hint and hint.movie_suffix.lower().endswith(".eer")):
        print("  [EER NOTE] Dose/fraction assumes the metadata fraction count. Recalculate it if EER rendering/grouping changes the number of output frames.")
        frames = median_value("frames")
        if total_dose:
            options = sorted({40, int(frames)} if frames else {40})
            print("  [EER NOTE] cryoSPARC 'EER Number of Fractions': " + "; ".join(
                f"{n} -> {total_dose / n:.3g} e-/A^2 per fraction" for n in options))


@dataclass
class SuffixHint:
    movie_suffix: str   # what follows the XML stem in the movie name, e.g. '_EER.eer'
    xml_suffix: str     # what follows the stem in the XML name, i.e. '.xml'
    found: int
    checked: int
    example_xml: str
    example_movie: str


def xml_suffix_hint(reports: list[Report], limit: int = 200) -> Optional[SuffixHint]:
    """Find the movie file beside sampled EPU XMLs and work out the cryoSPARC cut lengths."""
    listings: dict[Path, list[str]] = {}
    counts: dict[str, int] = {}
    examples: dict[str, tuple[str, str]] = {}
    checked = 0
    step = max(1, len(reports) // limit)
    for report in reports[::step][:limit]:
        if report.path.suffix.lower() != ".xml":
            continue
        folder, stem = report.path.parent, report.path.stem
        if folder not in listings:
            try:
                listings[folder] = [
                    entry.name for entry in folder.iterdir()
                    if entry.suffix.lower() in MOVIE_SUFFIXES or (entry.suffix.lower() == ".mrc" and "fraction" in entry.name.lower())
                ]
            except OSError:
                listings[folder] = []
        checked += 1
        for name in listings[folder]:
            if name.startswith(stem) and len(name) > len(stem):
                suffix = name[len(stem):]
                counts[suffix] = counts.get(suffix, 0) + 1
                examples.setdefault(suffix, (report.path.name, name))
    if not counts:
        return None
    suffix, found = max(counts.items(), key=lambda item: item[1])
    xml_name, movie_name = examples[suffix]
    return SuffixHint(suffix, xml_name[len(Path(xml_name).stem):], found, checked, xml_name, movie_name)


def format_optional(value: Optional[float]) -> str:
    return "NOT FOUND" if value is None else f"{value:.6g}"


def directory_check(
    reports: list[Report],
    title: str = "DIRECTORY CONSISTENCY",
    *,
    outlier_limit: int = 5,
    recommended: bool = False,
) -> None:
    print(f"\n{'=' * 92}\n{title} ({len(reports)} recognized file(s))")
    groups = signature_groups(reports)
    signature_state = "[OK]" if len(groups) == 1 else "[WARNING]"
    print(f"  {signature_state} acquisition signatures: {len(groups)}")
    if len(groups) > 1:
        for index, (signature, members) in enumerate(sorted(groups.items(), key=lambda item: -len(item[1])), 1):
            print(f"    group {index}: n={len(members)}; detector={signature[0]}; pixel={signature[1]}; voltage={signature[2]}; mag={signature[3]}; frames={signature[4]}; exposure={signature[5]}; gain={signature[6]}")
    for key, label in [
        ("detector", "detector"),
        ("pixel", "pixel size (A/px)"),
        ("voltage", "voltage (kV)"),
        ("magnification", "magnification"),
        ("frames", "fractions"),
        ("exposure", "exposure time (s)"),
        ("gain", "gain reference"),
    ]:
        vals = [report_value(report, key) for report in reports if report_value(report, key) is not None]
        if not vals:
            if key == "gain":
                print(f"  [MANUAL] {label}: not present in supplied metadata")
            continue
        if isinstance(vals[0], str):
            state = "[OK]" if len(set(vals)) == 1 else "[WARNING]"
            print(f"  {state} {label}: n={len(vals)}; {', '.join(map(str, sorted(set(vals))))}")
        else:
            low, high = min(vals), max(vals)
            median = statistics.median(vals)
            state = "[OK]" if math.isclose(low, high, rel_tol=STRICT_REL_TOLERANCE) else "[WARNING]"
            print(f"  {state} {label}: n={len(vals)}; median={median:.6g}; range={low:.6g}-{high:.6g}")
    print("  [MANUAL] spherical aberration (Cs): not present in supplied metadata")
    print_dose_summary(reports, "dose_per_frame", "dose per frame (e-/A^2/frame)", outlier_limit)
    print_dose_summary(reports, "total_dose", "total exposure dose (e-/A^2)", outlier_limit)
    if any(report_value(report, "camera_dose") is not None for report in reports):
        print_dose_summary(reports, "camera_dose",
                           "dose at camera (e-/A^2; varies with ice; very low = blank/blocked, high = empty holes)",
                           outlier_limit, informational=True)
    print_extra_summary(reports)
    if recommended:
        print_recommended_import(reports)


def print_extra_summary(reports: list[Report]) -> None:
    """Dataset-level view of the EPU extras (K2/K3 since v2.4, Falcon since v2.5)."""
    if not any(report.extras for report in reports):
        return
    print("  -- EPU extras --")
    for key, label in [
        ("epu_nominal_movie_pixel_A", "EPU nominal movie pixel (A)"),
        ("dose_rate_e_per_movie_px_s", "dose rate (e-/movie px/s)"),
        ("epu_total_dose_e_per_A2", "EPU total dose (e-/A^2, nominal px)"),
        ("total_dose_with_calibrated_pixel", "total dose with calibrated px (e-/A^2)"),
        ("dose_rate_on_sample_e_per_px_s", "dose rate on sample (e-/px/s)"),
        ("dose_on_camera_e_per_px", "dose at camera (e-/px)"),
        ("camera_to_sample_ratio", "camera/sample dose (transmission)"),
        ("minus_ln_transmission", "-ln(transmission), relative ice path"),
        ("energy_slit_eV", "energy slit (eV)"),
    ]:
        vals = [float(r.extras[key]) for r in reports if r.extras.get(key) is not None]
        if vals:
            print(f"  {label}: n={len(vals)}; median={statistics.median(vals):.5g}; "
                  f"P05-P95={percentile(vals, 0.05):.5g}-{percentile(vals, 0.95):.5g}; range={min(vals):.5g}-{max(vals):.5g}")
    units = [str(r.extras["detector_total_dose_unit"]) for r in reports if r.extras.get("detector_total_dose_unit")]
    if units:
        counts = {v: units.count(v) for v in sorted(set(units))}
        print("  detector TotalDose unit: " + ", ".join(f"{k} (n={n})" for k, n in counts.items()))
    tilts = [round(float(r.extras["stage_tilt_deg"]), 1) for r in reports if r.extras.get("stage_tilt_deg") is not None]
    if tilts:
        counts_t = {v: tilts.count(v) for v in sorted(set(tilts))}
        print("  stage tilt (deg): " + ", ".join(f"{k:g} (n={n})" for k, n in counts_t.items()))
    for key, label in [("instrument", "instrument"), ("movie_size_px", "movie size from XML")]:
        vals = [str(r.extras[key]) for r in reports if r.extras.get(key)]
        if vals:
            counts = {v: vals.count(v) for v in sorted(set(vals))}
            print(f"  {label}: " + ", ".join(f"{k} (n={n})" for k, n in counts.items()))
    defocus = [round(float(r.extras["applied_defocus_um"]), 2) for r in reports if r.extras.get("applied_defocus_um") is not None]
    if defocus:
        counts = {v: defocus.count(v) for v in sorted(set(defocus))}
        print("  applied defocus (um): " + ", ".join(f"{k:g} (n={n})" for k, n in counts.items()))
    with_shift = sum(1 for r in reports if r.extras.get("beam_shift_x") is not None)
    print(f"  beam shift present: {with_shift}/{len(reports)}")
    hours: dict[str, list[float]] = {}
    for r in reports:
        stamp = r.extras.get("acquisition_time")
        if stamp:
            hours.setdefault(str(stamp)[:13], []).append(r.extras.get("dose_rate_e_per_movie_px_s"))
    if hours and any(rate is not None for values in hours.values() for rate in values):
        print("  time course (local acquisition hour: n movies, median dose rate e-/px/s):")
        for hour in sorted(hours):
            rates = [x for x in hours[hour] if x is not None]
            rate_text = f"{statistics.median(rates):.4g}" if rates else "n/a"
            print(f"    {hour.replace('T', ' ')}h  n={len(hours[hour])}  rate={rate_text}")


# ---------------------------------------------------------------------------
# v2.6: compact, answer-first summary for directories
# ---------------------------------------------------------------------------
WIDTH = 100            # wrap summary lines at this many characters
BLANK_FRACTION = 0.10  # camera dose below this fraction of the median = blank or blocked exposure
FULL_BEAM = 0.98       # camera/sample ratio at or above this = (nearly) empty hole


def emit(tag: str, text: str) -> None:
    """One check line, wrapped at WIDTH with a hanging indent under the text."""
    head = f"  {tag:<10}" if tag else "  "
    print(textwrap.fill(text, width=WIDTH, initial_indent=head, subsequent_indent=" " * len(head),
                        break_long_words=False, break_on_hyphens=False))


def field_line(label: str, value: str, note: str = "") -> None:
    """'label  value  note' in fixed columns; long values (paths) get the note on the next line."""
    if len(value) > 9:
        print(f"  {label:<28}{value}")
        if note:
            print(textwrap.fill(note, width=WIDTH, initial_indent=" " * 30, subsequent_indent=" " * 30,
                                break_long_words=False, break_on_hyphens=False))
        return
    head = f"  {label:<28}{value:<9} "
    if not note:
        print(head.rstrip())
        return
    print(textwrap.fill(note, width=WIDTH, initial_indent=head, subsequent_indent=" " * len(head),
                        break_long_words=False, break_on_hyphens=False))


def short_path(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


@dataclass
class Spread:
    """How one quantity varies across movies.  `value` is exact when `uniform`, else the median."""
    value: Optional[float]
    low: Optional[float]
    high: Optional[float]
    n: int
    uniform: bool
    max_error: float  # largest relative deviation of any movie from `value`


def spread_of(values: list[float], tol: float = STRICT_REL_TOLERANCE) -> Spread:
    if not values:
        return Spread(None, None, None, 0, True, 0.0)
    median = statistics.median(values)
    low, high = min(values), max(values)
    uniform = math.isclose(low, high, rel_tol=tol, abs_tol=1e-9)
    error = max(abs(low - median), abs(high - median)) / abs(median) if median else 0.0
    return Spread(median, low, high, len(values), uniform, error)


def value_spread(reports: list[Report], key: str) -> Spread:
    return spread_of([float(v) for r in reports if (v := report_value(r, key)) is not None])


def extra_spread(reports: list[Report], key: str) -> Spread:
    return spread_of([float(r.extras[key]) for r in reports if r.extras.get(key) is not None])


def num(value: Optional[float], digits: int = 6) -> str:
    return "NOT FOUND" if value is None else f"{value:.{digits}g}"


def shown(item: Spread, digits: int = 6) -> tuple[str, str]:
    """Value text plus a note that says when it is a median and how far movies stray from it."""
    if item.value is None:
        return "NOT FOUND", ""
    if item.uniform:
        return num(item.value, digits), ""
    return num(item.value, digits), (f"median; movies range {num(item.low, digits)}-{num(item.high, digits)}, "
                                     f"up to {100 * item.max_error:.3g} % from this value")


def folder_pattern(paths: list[Path], base: Path) -> Optional[str]:
    """Common folder pattern of the movie XMLs relative to base, e.g. GridSquare_*/Data."""
    patterns = set()
    for path in paths:
        parts = Path(short_path(path.parent, base)).parts
        parts = tuple("GridSquare_*" if p.lower().startswith("gridsquare_")
                      else "Images-Disc*" if p.lower().startswith("images-disc") else p for p in parts)
        patterns.add(str(Path(*parts)) if parts else ".")
    return patterns.pop() if len(patterns) == 1 else None


def resolve_gain(gain: str, base: Path, reports: list[Report]) -> tuple[str, bool]:
    """Turn EPU's relative gain path into an existing absolute path where possible."""
    raw = Path(gain.replace("\\", "/"))
    if raw.is_absolute():
        return str(raw), raw.exists()
    for folder in (base, *list(base.parents)[:3], reports[0].path.parent):
        if (folder / raw).exists():
            return str(folder / raw), True
    try:
        hit = next(base.rglob(raw.name), None)
    except OSError:
        hit = None
    return (str(hit), True) if hit else (gain, False)


def grid_square_name(path: Path, owners: dict[Path, Path]) -> str:
    owner = owners.get(path)
    if owner is not None:
        return owner.parent.name
    for parent in path.parents:
        if parent.name.lower().startswith("gridsquare_"):
            return parent.name
    return path.parent.name


def dose_note(reports: list[Report]) -> str:
    totals = [r.values["total_dose"] for r in reports if r.values.get("total_dose") is not None and r.values["total_dose"].value is not None]
    if not totals:
        return "MANUAL - not in the metadata; use the dose rate measured over vacuum"
    if len(totals) < len(reports):
        return f"missing in {len(reports) - len(totals):,}/{len(reports):,} movies - see CHECKS"
    if any(t.status == "UNVERIFIED" for t in totals):
        return "UNVERIFIED - see CHECKS"
    rescaled = "; for the calibrated pixel" if any("calibrated pixel" in t.source for t in totals) else ""
    if all(t.source.startswith("DoseOnSample / 1e20, validated") for t in totals):
        return "dose on sample, cross-checked against DoseRate" + rescaled
    if all(t.source.startswith("DoseOnSample") for t in totals):
        return "dose on sample (not cross-checked; see CHECKS)"
    return "from " + totals[0].source


def warning_digest(reports: list[Report]) -> list[tuple[int, str]]:
    """Per-file warnings grouped by their wording (numbers ignored), most frequent first."""
    groups: dict[str, list[str]] = {}
    for report in reports:
        for text in report.warnings:
            if text.startswith("Pixel size is EPU's nominal"):
                continue  # reported once as INFO
            groups.setdefault(re.sub(r"[-+]?\d[\d.eE+-]*", "#", text), []).append(text)
    return sorted(((len(v), v[0]) for v in groups.values()), key=lambda item: -item[0])


def print_cryosparc_block(reports: list[Report], base: Path) -> None:
    is_xml = all(r.path.suffix.lower() == ".xml" for r in reports)
    hint = xml_suffix_hint(reports) if is_xml else None
    print("\nCRYOSPARC - Import Movies (fields in the order of the job form)")
    # Movies and gain paths
    if is_xml:
        pattern = folder_pattern([r.path for r in reports], base)
        if hint and pattern:
            field_line("Movies data path", str(base / pattern / f"*{hint.movie_suffix}"))
        else:
            field_line("Movies data path", "NOT FOUND", "no movie files next to the XML files; point it at the movies")
    else:
        stems = {Path(r.path.stem).suffix for r in reports if r.path.suffix.lower() == ".mdoc"}
        pattern = folder_pattern([r.path for r in reports], base)
        if pattern and len(stems) == 1 and next(iter(stems)):
            field_line("Movies data path", str(base / pattern / f"*{next(iter(stems))}"))
    gains = sorted({str(r.values["gain"].value) for r in reports if r.values["gain"].value is not None})
    if len(gains) == 1:
        gain_path, found = resolve_gain(gains[0], base, reports)
        field_line("Gain reference path", gain_path, "" if found else "as written by EPU; file not found under the data folder")
    elif gains:
        field_line("Gain reference path", "MIXED", f"{len(gains)} different gain references; see the TSV")
    else:
        field_line("Gain reference path", "NOT FOUND", "not in the metadata; leave blank only if the movies are gain-corrected")
    # Optics
    pixel_value, pixel_note = shown(value_spread(reports, "pixel"))
    epu = any(r.format.startswith("EPU XML") for r in reports)
    calibrated = any(r.values["pixel"].status == "MANUAL" and r.values["pixel"].value for r in reports)
    if epu and not calibrated:
        pixel_note = "; ".join(filter(None, [pixel_note, "EPU nominal calibration"]))
    elif calibrated:
        nominal = extra_spread(reports, "epu_nominal_movie_pixel_A")
        epu_text = (f"; EPU nominal {num(nominal.value)} ({100 * (nominal.value - value_spread(reports, 'pixel').value) / value_spread(reports, 'pixel').value:+.2f}%)"
                    if nominal.value and value_spread(reports, "pixel").value else "")
        pixel_note = "; ".join(filter(None, [pixel_note, "calibrated, from --pixel-size" + epu_text]))
    field_line("Pixel size (A)", pixel_value, pixel_note)
    field_line("Accelerating Voltage (kV)", *shown(value_spread(reports, "voltage")))
    field_line("Spherical Aberration (mm)", "MANUAL", "not in the metadata; ask the facility")
    # Dose
    total = value_spread(reports, "total_dose")
    total_value, total_note = shown(total, 4)
    field_line("Total exposure dose (e/A^2)", total_value, "; ".join(filter(None, [dose_note(reports), total_note])))
    frames = value_spread(reports, "frames")
    per_frame = value_spread(reports, "dose_per_frame")
    if per_frame.value is not None:
        per_value, per_note = shown(per_frame, 3)
        basis = f"{num(total.value, 4)} / {num(frames.value)} fractions" if frames.uniform else "total / fractions per movie"
        field_line("Dose per frame (e/A^2)", per_value,
                   "; ".join(filter(None, [basis, per_note, "for RELION and Scipion; cryoSPARC takes the total"])))
    # EER
    eer = any("eer" in g.lower() for g in gains) or bool(hint and hint.movie_suffix.lower().endswith(".eer"))
    if eer:
        if frames.value and 0 < frames.value < 100000 and total.value:
            n = int(frames.value)
            field_line("EER Number of Fractions", str(n),
                       f"as recorded by EPU: {total.value / n:.3g} e/A^2 per fraction "
                       f"(cryoSPARC default 40: {total.value / 40:.3g} each)")
        field_line("EER Upsampling Factor", "1", "pixel size above is for the 4k sensor, as cryoSPARC expects")
    # XML import: the four cut fields, with their exact cryoSPARC labels and a worked example
    if is_xml:
        print("  -- XML Import --")
        with_shift = sum(1 for r in reports if r.extras.get("beam_shift_x") is not None)
        xml_field("Import Beam Shift Values from XML Files", "on" if with_shift else "off",
                  f"in {with_shift:,}/{len(reports):,} files")
        pattern = folder_pattern([r.path for r in reports], base)
        if pattern:
            xml_field("EPU XML metadata path", str(base / pattern / "*.xml"))
        if hint:
            xml_name, movie_name = hint.example_xml, hint.example_movie
            common = xml_name[:-len(hint.xml_suffix)]
            xml_field("Length of input filename prefix to cut for XML correspondence", "0")
            xml_field("Length of input filename suffix to cut for XML correspondence", str(len(hint.movie_suffix)),
                      f"cuts '{hint.movie_suffix}'")
            xml_field("Length of XML filename prefix to cut for input correspondence", "0")
            xml_field("Length of XML filename suffix to cut for input correspondence", str(len(hint.xml_suffix)),
                      f"cuts '{hint.xml_suffix}'")
            print(f"  {'Check (one file pair):':<24}{movie_name}  minus last {len(hint.movie_suffix)}")
            print(f"  {'':<24}{xml_name}  minus last {len(hint.xml_suffix)}")
            print(f"  {'':<24}both leave {common}  -> match")
            print(f"  {'':<24}(same suffix found for {hint.found:,} of {hint.checked:,} sampled XML files)")
        else:
            xml_field("Length of input filename suffix to cut for XML correspondence", "NOT FOUND",
                      "no movie file next to the XML files; count the characters the movie name has after the XML name")


def xml_field(label: str, value: str, note: str = "") -> None:
    """cryoSPARC XML Import field: full label, then the value (and a short note) in a column."""
    if len(label) > 61 or len(value) > 9:
        print(f"  {label}")
        print(textwrap.fill(f"{value}   {note}".rstrip(), width=WIDTH, initial_indent=" " * 6,
                            subsequent_indent=" " * 6, break_long_words=False, break_on_hyphens=False))
        return
    head = f"  {label:<63}{value:<6} "
    print(textwrap.fill(note, width=WIDTH, initial_indent=head, subsequent_indent=" " * len(head),
                        break_long_words=False, break_on_hyphens=False) if note else head.rstrip())


def print_checks(reports: list[Report], base: Path, outlier_limit: int) -> None:
    print("\nCHECKS")
    n = len(reports)
    emit("[OK]", f"Same detector, pixel size, voltage, magnification, fractions, exposure time and gain "
                 f"reference in all {n:,} movies.")
    # Dose on sample
    total = value_spread(reports, "total_dose")
    statuses = [r.values["total_dose"].status for r in reports if "total_dose" in r.values]
    validated = sum(1 for r in reports if r.values.get("total_dose") is not None
                    and r.values["total_dose"].source.startswith("DoseOnSample / 1e20, validated"))
    unverified = statuses.count("UNVERIFIED")
    missing = n - total.n
    scope = "all movies" if not missing else f"the {total.n:,} movies that have one"
    if total.value is None:
        emit("[MANUAL]", "No dose on sample in the metadata: enter the dose measured over vacuum (dose rate x exposure).")
    elif total.uniform:
        emit("[OK]", f"Total dose identical in {scope}: {num(total.value, 4)} e/A^2"
                     + (f"; cross-checked against DoseRate in {validated:,}/{n:,}." if validated else "."))
    else:
        emit("[WARNING]", f"Total dose varies between movies: median {num(total.value, 4)}, range "
                          f"{num(total.low, 4)}-{num(total.high, 4)} e/A^2. One value is off by up to "
                          f"{100 * total.max_error:.3g} % for some movies; above about 5 %, import the dose groups "
                          f"separately (TSV column 13).")
    if missing and total.value is not None:
        emit("[WARNING]", f"No usable total dose in {missing:,}/{n:,} movies (reason in the warnings below); "
                          "check them before using one value for all.")
    if unverified:
        emit("[WARNING]", f"Dose unit could not be verified in {unverified:,}/{n:,} movies; confirm the total dose "
                          "with the dose rate measured over vacuum.")
    # What the detector TotalDose field is
    units = [str(r.extras["detector_total_dose_unit"]) for r in reports if r.extras.get("detector_total_dose_unit")]
    if units and units.count("e-/px at camera") == len(units):
        cam_px = extra_spread(reports, "dose_on_camera_e_per_px")
        emit("[INFO]", f"EPU's TotalDose / DoseOnCamera is the dose at the camera in e-/px (median {num(cam_px.value, 3)}), "
                       "not the import dose. v2.4 and earlier used it by mistake.")
    # Tilt
    tilt = extra_spread(reports, "stage_tilt_deg")
    if tilt.value is not None:
        if tilt.uniform or (tilt.high - tilt.low) < 0.5:
            emit("[INFO]", f"Stage tilt {tilt.value:.1f} deg in all movies.")
        else:
            tilts = [round(float(r.extras["stage_tilt_deg"])) for r in reports if r.extras.get("stage_tilt_deg") is not None]
            counts = ", ".join(f"{t} deg (n={tilts.count(t):,})" for t in sorted(set(tilts)))
            emit("[INFO]", f"Stage tilt varies: {counts}.")
    # Camera dose, transmission, blank exposures
    camera = value_spread(reports, "camera_dose")
    if camera.value is not None:
        cams = [float(v) for r in reports if (v := report_value(r, "camera_dose")) is not None]
        ratio = extra_spread(reports, "camera_to_sample_ratio")
        emit("[INFO]", f"Dose at camera: median {num(camera.value, 3)} e/A^2 (P05-P95 {num(percentile(cams, 0.05), 3)}-"
                       f"{num(percentile(cams, 0.95), 3)}); median transmission {num(ratio.value, 2)}. It follows ice "
                       "thickness and tilt and is for quality control only.")
        blank = sorted((r for r in reports if report_value(r, "camera_dose") is not None
                        and report_value(r, "camera_dose") < BLANK_FRACTION * camera.value),
                       key=lambda r: report_value(r, "camera_dose"))
        if blank:
            emit("[FLAG]", f"{len(blank):,} movie(s) with almost no dose at the camera (<{BLANK_FRACTION:.0%} of the "
                           "median): blank or blocked exposures. Curate Exposures should remove them; all are listed "
                           "in the TSV (camera_dose_outlier_dataset).")
            for r in blank[:outlier_limit]:
                print(f"{'':11}{num(report_value(r, 'camera_dose'), 3):>8}  {short_path(r.path, base)}")
            if len(blank) > outlier_limit:
                print(f"{'':11}... {len(blank) - outlier_limit:,} more")
        full = sum(1 for r in reports if r.extras.get("camera_to_sample_ratio") is not None
                   and r.extras["camera_to_sample_ratio"] >= FULL_BEAM)
        if full:
            emit("[INFO]", f"{full:,} movie(s) receive >= {FULL_BEAM:.0%} of the beam at the camera: empty holes or "
                           "very thin ice.")
    elif not total.uniform and total.value is not None:
        values, value_reports, outliers = numeric_summary(reports, "total_dose")
        if outliers:
            emit("[FLAG]", f"{len(outliers):,} movie(s) with an outlying total dose (listed in the TSV).")
    nominal_dose = extra_spread(reports, "epu_total_dose_e_per_A2")
    nominal_px = extra_spread(reports, "epu_nominal_movie_pixel_A")
    pixel = value_spread(reports, "pixel")
    if any(r.values["pixel"].status == "MANUAL" and r.values["pixel"].value for r in reports) and nominal_px.value and pixel.value:
        emit("[INFO]", f"Pixel size {num(pixel.value)} A from --pixel-size; EPU's nominal value is {num(nominal_px.value)} A "
                       f"({100 * (nominal_px.value - pixel.value) / pixel.value:+.2f} %). Doses per A^2 are re-expressed for the "
                       f"calibrated pixel (x{(nominal_px.value / pixel.value) ** 2:.4f})"
                       + (f"; EPU's own total dose is {num(nominal_dose.value, 4)} e/A^2." if nominal_dose.value else "."))
    emit("[MANUAL]", "Spherical aberration (Cs) is not in the metadata.")
    if any(r.format.startswith("EPU XML") for r in reports) and not any(
            r.values["pixel"].status == "MANUAL" and r.values["pixel"].value for r in reports):
        emit("[INFO]", "The pixel size is EPU's nominal calibration; use the facility-calibrated value if known "
                       "(it matters when merging datasets from different microscopes).")
    for count, text in warning_digest(reports)[:8]:
        emit("[WARNING]", f"{text}" + (f" ({count:,} files)" if count > 1 else ""))


def print_grid_table(reports: list[Report], owners: dict[Path, Path]) -> None:
    groups: dict[str, list[Report]] = {}
    for report in reports:
        groups.setdefault(grid_square_name(report.path, owners), []).append(report)
    if len(groups) < 2:
        return
    camera_present = any(report_value(r, "camera_dose") is not None for r in reports)
    overall = value_spread(reports, "camera_dose").value if camera_present else None
    print(f"\nPER GRID SQUARE ({len(groups)})" + (" - camera dose and transmission follow the ice; "
                                                   f"blank = <{BLANK_FRACTION:.0%} of the median" if camera_present else ""))
    print(f"  {'Grid square':<22}{'Movies':>7}{'Total dose':>12}{'Cam. dose':>11}{'Transm.':>9}{'Tilt':>7}{'Blank':>7}")
    for name, members in sorted(groups.items()):
        total = value_spread(members, "total_dose")
        cam = value_spread(members, "camera_dose")
        ratio = extra_spread(members, "camera_to_sample_ratio")
        tilt = extra_spread(members, "stage_tilt_deg")
        blank = sum(1 for r in members if overall and report_value(r, "camera_dose") is not None
                    and report_value(r, "camera_dose") < BLANK_FRACTION * overall)
        total_text = num(total.value, 4) + ("" if total.uniform else "*")
        print(f"  {name[:21]:<22}{len(members):>7,}{total_text:>12}"
              f"{(num(cam.value, 3) if cam.value is not None else '-'):>11}"
              f"{(num(ratio.value, 2) if ratio.value is not None else '-'):>9}"
              f"{(f'{tilt.value:.1f}' if tilt.value is not None else '-'):>7}"
              f"{(str(blank) if camera_present else '-'):>7}")
    if any(not value_spread(m, "total_dose").uniform for m in groups.values()):
        print("  * total dose varies inside this grid square (median shown)")


def print_compact_summary(reports: list[Report], base: Path, owners: dict[Path, Path], grid_data_mode: bool,
                          outlier_limit: int, skipped: int,
                          shift_groups: Optional[dict[tuple[Any, ...], BeamShiftGroups]] = None) -> bool:
    """Answer-first summary.  Returns False when there is no movie group (caller falls back)."""
    groups = signature_groups(reports)
    movie_groups = sorted((m for s, m in groups.items() if s[4] is not None), key=len, reverse=True)
    images = sum(len(m) for s, m in groups.items() if s[4] is None)
    if not movie_groups:
        return False
    movies = sum(len(m) for m in movie_groups)
    squares = {grid_square_name(r.path, owners) for m in movie_groups for r in m}
    print(f"\n{'=' * WIDTH}\ncryo_import_metadata {VERSION} | {base}")
    parts = [f"{movies:,} movie metadata files" + (f" in {len(squares):,} grid squares" if len(squares) > 1 else "")]
    if grid_data_mode:
        parts.append("scope: GridSquare_*/Data folders only")
    if images:
        parts.append(f"{images:,} single images left out (atlas, grid square, foil hole)")
    if skipped:
        parts.append(f"{skipped:,} files not recognised (listed on stderr)")
    emit("", "; ".join(parts) + ".")
    if len(movie_groups) > 1:
        emit("[WARNING]", f"{len(movie_groups)} movie groups with different acquisition settings; import each "
                          "group as a separate Import Movies job.")
    for index, members in enumerate(movie_groups, 1):
        if len(movie_groups) > 1:
            print(f"\n{'-' * WIDTH}\nMOVIE GROUP {index} of {len(movie_groups)} ({len(members):,} movies)")
        print_cryosparc_block(members, base)
        if all(r.path.suffix.lower() == ".xml" for r in members):
            print_exposure_group_block(members, (shift_groups or {}).get(acquisition_signature(members[0])))
        print_checks(members, base, outlier_limit)
        print_grid_table(members, owners)
    print(f"{'=' * WIDTH}")
    return True


# ---------------------------------------------------------------------------
# v2.8: AFIS / beam-shift groups for cryoSPARC Exposure Group Utilities
# ---------------------------------------------------------------------------
@dataclass
class BeamShiftGroups:
    count: int                  # recommended number of clusters (beam-shift groups, ~ hole positions)
    plateau: float              # how stable that count is: max/min grid resolution over which it holds
    sizes: list[int]            # movies per group
    sub_count: Optional[int]    # a finer stable level (e.g. shots within each hole), if any
    with_shift: int             # movies with a beam shift
    total: int                  # movies in the group
    clear: bool                 # True when the grouping is well separated
    labels: list[int]           # group number per movie with a beam shift (0 = stray movie)
    low: int                    # smallest and largest count seen over the stable range
    high: int


def grid_components(points: list[tuple[float, float]], resolution: int) -> list[int]:
    """Label points by 8-connected occupied cells of a resolution x resolution grid (single linkage)."""
    cells: dict[tuple[int, int], list[int]] = {}
    for index, (u, v) in enumerate(points):
        cells.setdefault((min(int(u * resolution), resolution - 1), min(int(v * resolution), resolution - 1)), []).append(index)
    labels = [-1] * len(points)
    seen: set[tuple[int, int]] = set()
    current = 0
    for start in cells:
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        while stack:
            cx, cy = stack.pop()
            for index in cells[(cx, cy)]:
                labels[index] = current
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    neighbour = (cx + dx, cy + dy)
                    if neighbour in cells and neighbour not in seen:
                        seen.add(neighbour)
                        stack.append(neighbour)
        current += 1
    return labels


def substantial_count(labels: list[int], min_points: int) -> tuple[int, dict[int, int], int]:
    """Groups of at least `min_points` movies and at least 2 % of the largest group (stray movies ignored)."""
    sizes: dict[int, int] = {}
    for label in labels:
        sizes[label] = sizes.get(label, 0) + 1
    threshold = max(min_points, int(0.02 * max(sizes.values())))
    return sum(1 for size in sizes.values() if size >= threshold), sizes, threshold


def beam_shift_groups(reports: list[Report]) -> Optional[BeamShiftGroups]:
    """Count well-separated beam-shift groups (AFIS hole positions) without extra packages.

    Movies are linked when their beam shifts fall in neighbouring cells of a grid,
    and the grid is refined step by step (single linkage at many length scales).
    The number of groups that stays the same over the widest range of scales is the
    natural number of clusters.  A second stable level at a finer scale is reported
    as sub-groups (several shots per hole).  Groups smaller than 0.05 % of the
    movies (at least 3) are treated as stray movies.
    """
    shifted = [r for r in reports if r.extras.get("beam_shift_x") is not None and r.extras.get("beam_shift_y") is not None]
    n = len(shifted)
    if n < 20:
        return None
    xs = [float(r.extras["beam_shift_x"]) for r in shifted]
    ys = [float(r.extras["beam_shift_y"]) for r in shifted]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    if span <= 0:
        return BeamShiftGroups(1, float("inf"), [n], None, n, len(reports), True, [1] * n, 1, 1)
    x0, y0 = min(xs), min(ys)
    unit = [((x - x0) / span * 0.999999, (y - y0) / span * 0.999999) for x, y in zip(xs, ys)]
    min_points = max(3, int(0.0005 * n))
    levels: list[tuple[int, int]] = []
    resolution = 2.0
    while resolution <= 4096:
        count, _, _ = substantial_count(grid_components(unit, int(resolution)), min_points)
        levels.append((int(resolution), count))
        resolution *= 1.15
    # Stable ranges: windows of consecutive resolutions whose counts differ by at most 10 % (at least 2),
    # scored by width (max/min resolution).  Sparse edge holes make the count wobble by a few groups,
    # so an exact plateau would be too strict for real data.
    def windows(lo: int, hi: int) -> list[tuple[float, int, int, int, int, int]]:
        found = []
        for i in range(lo, hi):
            j = i
            while j + 1 < hi:
                part = [level[1] for level in levels[i:j + 2]]
                if max(part) - min(part) > max(2, 0.10 * min(part)) or min(part) <= 1:
                    break
                j += 1
            part = sorted(level[1] for level in levels[i:j + 1])
            found.append((levels[j][0] / levels[i][0], part[len(part) // 2], i, j, part[0], part[-1]))
        return [w for w in found if 1 < w[1] <= n / 5]
    # A multi-group answer must hold over at least a 1.5x range of length scales; otherwise there
    # are no separated groups (one position with scatter, or a continuous spread of beam shifts).
    candidates = [w for w in windows(0, len(levels)) if w[0] >= 1.5]
    if not candidates:
        return BeamShiftGroups(1, 1.0, [n], None, n, len(reports), False, [1] * n, 1, 1)
    best = max(candidates, key=lambda run: run[0])
    width, count, first, last, low, high = best
    # label with the level inside the run whose count is closest to the median, nearest the middle
    middle = (first + last) / 2
    pick = min(range(first, last + 1), key=lambda i: (abs(levels[i][1] - count), abs(i - middle)))
    labels = grid_components(unit, levels[pick][0])
    _, sizes, threshold = substantial_count(labels, min_points)
    order: dict[int, int] = {}
    for label in sorted(sizes, key=lambda item: -sizes[item]):
        if sizes[label] >= threshold:
            order[label] = len(order) + 1
    group_labels = [order.get(label, 0) for label in labels]
    group_sizes = sorted((size for size in sizes.values() if size >= threshold), reverse=True)
    finer = [w for w in windows(last + 1, len(levels)) if w[1] >= 2 * count and w[0] >= 1.5]
    sub = max(finer, key=lambda w: w[0])[1] if finer else None
    others = [w[0] for w in windows(0, first) + windows(last + 1, len(levels))]
    clear = width >= 2.5 and (not others or width >= 1.3 * max(others))
    return BeamShiftGroups(count, width, group_sizes, sub, n, len(reports), clear, group_labels, low, high)


def label_beam_shift_groups(reports: list[Report]) -> dict[tuple[Any, ...], BeamShiftGroups]:
    """Find the beam-shift groups per movie group and store each movie's group number in its extras."""
    result: dict[tuple[Any, ...], BeamShiftGroups] = {}
    for signature, members in signature_groups(reports).items():
        if signature[4] is None:
            continue
        groups = beam_shift_groups(members)
        if groups is None:
            continue
        result[signature] = groups
        shifted = [r for r in members if r.extras.get("beam_shift_x") is not None and r.extras.get("beam_shift_y") is not None]
        for report, label in zip(shifted, groups.labels):
            report.extras["beam_shift_group"] = label
    return result


def shots_per_hole(reports: list[Report]) -> Optional[int]:
    """Distinct EPU acquisition-area template IDs (FoilHole_<hole>_Data_<template>_...) = shots per hole."""
    templates = set()
    for report in reports:
        match = re.search(r"FoilHole_\d+_Data_(\d+)_", report.path.name)
        if match:
            templates.add(match.group(1))
    return len(templates) if templates else None


def eg_field(label: str, value: str, note: str = "") -> None:
    """Exposure Group Utilities field: cryoSPARC label, value, and a wrapped note."""
    head = f"  {label:<33}{value:<15}"
    if not note:
        print(head.rstrip())
        return
    print(textwrap.fill(note, width=WIDTH, initial_indent=head, subsequent_indent=" " * len(head),
                        break_long_words=False, break_on_hyphens=False))


def print_exposure_group_block(reports: list[Report], groups: Optional[BeamShiftGroups]) -> None:
    print("\nCRYOSPARC - Exposure Group Utilities (beam-shift / AFIS groups; run after Patch Motion and Patch CTF)")
    if groups is None or groups.with_shift == 0:
        emit("", "No beam-shift values in the XML files: exposure groups cannot be made from beam shift.")
        return
    shots = shots_per_hole(reports)
    sizes = groups.sizes
    eg_field("Input Selection", "exposure")
    eg_field("Action", "cluster&split")
    if groups.count == 1:
        if groups.clear:
            eg_field("Number of clusters", "1", "all movies share one beam-shift position: nothing to split")
        else:
            eg_field("Number of clusters", "MANUAL", "no well-separated beam-shift groups (one position with scatter, "
                       "or a continuous spread); check the beam-shift plot. For a continuous spread use kmeans and "
                       "choose a number that keeps enough particles per group")
        return
    spread = f"; {groups.low}-{groups.high} within that range" if groups.high > groups.low else ""
    note = f"beam-shift groups, stable over a {groups.plateau:.1f}x range of length scales{spread}"
    if not groups.clear:
        note += "; the grouping is NOT clearly separated - check the beam-shift plot"
    eg_field("Number of clusters", str(groups.count), note)
    eg_field("Clustering method", "agglomerative" if groups.clear else "kmeans",
               "well-separated groups" if groups.clear else "continuous spread: kmeans gives more even groups")
    eg_field("Split Outputs by Exposure Group", "off", "one output; every exposure carries its group ID")
    eg_field("Correspond particles ...", "off", "turn on only when particles are connected as input too")
    emit("", f"Movies per group: median {statistics.median(sizes):.0f}, range {min(sizes)}-{max(sizes)} "
             f"({groups.with_shift:,} of {groups.total:,} movies have a beam shift"
             + ("; the others form one extra group in cryoSPARC)." if groups.with_shift < groups.total else ")."))
    if shots and shots > 1:
        sub = f"; the beam-shift plot also shows {groups.sub_count} finer sub-groups" if groups.sub_count else ""
        emit("", f"EPU collected {shots} acquisition areas per hole (Data template IDs){sub}. One cluster per group "
                 f"above (all shots of a hole together) is the usual choice; {groups.count * shots} clusters "
                 "(one per shot) only if each would still hold enough particles.")
    small = [s for s in sizes if s < 0.2 * statistics.median(sizes)]
    if small:
        emit("", f"{len(small)} group(s) hold fewer than 20 % of the median number of movies (edge positions); "
                 "their per-group aberration fit will be less precise.")


def grid_data_owner(path: Path) -> Optional[Path]:
    """Return GridSquare_x/Data for files inside EPU movie-data folders (Images-Disc* layout)."""
    for parent in path.parents:
        if (
            parent.name.lower() == "data"
            and parent.parent.name.lower().startswith("gridsquare_")
            and parent.parent.parent.name.lower().startswith("images-disc")
        ):
            return parent
    return None


def copied_grid_data_owner(path: Path) -> Optional[Path]:
    """v2.5: GridSquare_x/Data directly holding the file, for sessions copied without Images-Disc*."""
    parent = path.parent
    if parent.name.lower() == "data" and parent.parent.name.lower().startswith("gridsquare_"):
        return parent
    return None


def discover_files(input_path: Path, scope: str) -> tuple[list[Path], dict[Path, Path], bool]:
    """Discover metadata generically or restrict it to EPU GridSquare movie data."""
    if input_path.is_file():
        return [input_path], {}, False
    candidates = sorted([*input_path.rglob("*.xml"), *input_path.rglob("*.mdoc")])
    owners = {path: owner for path in candidates if (owner := grid_data_owner(path)) is not None}
    if not owners:
        # No Images-Disc* layout: accept GridSquare_*/Data folders of a copied session.
        owners = {path: owner for path in candidates if (owner := copied_grid_data_owner(path)) is not None}
    if scope == "epu-grid-data":
        return sorted(owners), owners, True
    if scope == "auto" and owners:
        # Suppress atlas, grid-square, foil-hole and session XML outside the movie Data folders.
        return sorted(owners), owners, True
    return candidates, {}, False


def dose_outlier_paths_by_signature(reports: list[Report], key: str = "total_dose") -> set[Path]:
    result: set[Path] = set()
    for members in signature_groups(reports).values():
        values, value_reports, indexes = numeric_summary(members, key)
        if values:
            result.update(value_reports[index].path for index in indexes)
    return result


def dose_outlier_paths_by_owner(reports: list[Report], owners: dict[Path, Path], key: str = "total_dose") -> set[Path]:
    """Flag dose outliers within each GridSquare/acquisition signature."""
    grouped: dict[tuple[Optional[Path], tuple[Any, ...]], list[Report]] = {}
    for report in reports:
        grouped.setdefault((owners.get(report.path), acquisition_signature(report)), []).append(report)
    result: set[Path] = set()
    for members in grouped.values():
        values, value_reports, indexes = numeric_summary(members, key)
        if values:
            result.update(value_reports[index].path for index in indexes)
    return result


def write_table(path: Path, reports: list[Report], owners: dict[Path, Path]) -> None:
    """Export one auditable row per recognized movie metadata file."""
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    dataset_outlier_paths = dose_outlier_paths_by_signature(reports)
    local_outlier_paths = dose_outlier_paths_by_owner(reports, owners)
    camera_dataset_outliers = dose_outlier_paths_by_signature(reports, "camera_dose")
    camera_local_outliers = dose_outlier_paths_by_owner(reports, owners, "camera_dose")
    has_camera = any(report_value(report, "camera_dose") is not None for report in reports)
    # Columns 1-30 are as in v2.4 (total_dose and dose_rate now refer to the sample);
    # v2.5 columns are appended at the end.
    fields = [
        "file", "grid_square", "format", "detector", "pixel_A_per_px", "voltage_kV",
        "cs_mm", "magnification", "fractions", "exposure_s", "dose_rate",
        "dose_per_frame_e_per_A2", "total_dose_e_per_A2", "gain_reference",
        "total_dose_status", "total_dose_outlier_dataset", "total_dose_outlier_grid_square",
    ] + EXTRA_FIELDS + ["camera_dose_outlier_dataset", "camera_dose_outlier_grid_square", "beam_shift_group"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=delimiter)
        writer.writeheader()
        for report in reports:
            owner = owners.get(report.path)
            writer.writerow({
                "file": str(report.path),
                "grid_square": owner.parent.name if owner else "",
                "format": report.format,
                "detector": report.detector.value,
                "pixel_A_per_px": report.values["pixel"].value,
                "voltage_kV": report.values["voltage"].value,
                "cs_mm": report.values["cs"].value,
                "magnification": report.values["magnification"].value,
                "fractions": report.values["frames"].value,
                "exposure_s": report.values["exposure"].value,
                "dose_rate": report.values["dose_rate"].value,
                "dose_per_frame_e_per_A2": report.values["dose_per_frame"].value,
                "total_dose_e_per_A2": report.values["total_dose"].value,
                "gain_reference": report.values["gain"].value,
                "total_dose_status": report.values["total_dose"].status,
                "total_dose_outlier_dataset": "yes" if report.path in dataset_outlier_paths else "no",
                "total_dose_outlier_grid_square": "yes" if report.path in local_outlier_paths else "no",
                **{name: report.extras.get(name) for name in EXTRA_FIELDS},
                "camera_dose_outlier_dataset": ("yes" if report.path in camera_dataset_outliers else "no") if has_camera else "",
                "camera_dose_outlier_grid_square": ("yes" if report.path in camera_local_outliers else "no") if has_camera else "",
                "beam_shift_group": report.extras.get("beam_shift_group", ""),
            })


def main() -> int:
    parser = argparse.ArgumentParser(description="Detector-aware cryo-EM import metadata reporter for EPU/Ceta/Falcon and SerialEM MDOC.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("input", type=Path, help="a .xml/.mdoc file or a directory to scan recursively")
    parser.add_argument("--sample", type=int, default=0, help="maximum files to process in directory mode (0 = all)")
    parser.add_argument("--summary-only", action="store_true", help="omit per-file output; print the summary only")
    parser.add_argument("--details", action="store_true",
                        help="after the summary, also print the long per-GridSquare and dataset-wide summaries (pre-2.6 layout)")
    parser.add_argument("--table", type=Path, help="write one row per recognized file as CSV (or TSV when filename ends in .tsv)")
    parser.add_argument("--outlier-limit", type=int, default=5, help="maximum dose-outlier paths shown per summary (default: 5)")
    parser.add_argument("--pixel-size", type=float, default=None,
                        help="facility-calibrated movie pixel size in A for EPU movies (Falcon and K2/K3); doses per A^2 "
                             "are re-expressed for it. EPU's own value is nominal. Single images keep EPU's value")
    parser.add_argument(
        "--scope",
        choices=("auto", "all", "epu-grid-data"),
        default="auto",
        help=(
            "auto: use EPU GridSquare Data folders when detected, otherwise scan all; "
            "all: scan every XML/MDOC recursively; epu-grid-data: only GridSquare_*/Data (Images-Disc* parent optional)"
        ),
    )
    args = parser.parse_args()
    if not args.input.exists():
        parser.error(f"does not exist: {args.input}")
    if args.table and not args.table.parent.is_dir():
        parser.error(f"folder for --table does not exist: {args.table.parent}  (create it with: mkdir -p \"{args.table.parent}\")")
    files, owners, grid_data_mode = discover_files(args.input, args.scope)
    if args.sample:
        files = files[:args.sample]
    if not files:
        if args.scope == "epu-grid-data":
            parser.error("no XML/MDOC files found under GridSquare_*/Data")
        parser.error("no .xml or .mdoc files found")
    reports: list[Report] = []
    skipped = 0
    for path in files:
        try:
            reports.append(parse_file(path, args.pixel_size))
        except ValueError as exc:
            skipped += 1
            print(f"[SKIPPED] {path}: {exc}", file=sys.stderr)
    if not reports:
        print("No recognized metadata files found.", file=sys.stderr)
        return 2
    if args.outlier_limit < 0:
        parser.error("--outlier-limit must be zero or greater")
    shift_groups = label_beam_shift_groups(reports) if args.input.is_dir() else {}
    if args.table:
        write_table(args.table, reports, owners)
        print(f"TABLE: {args.table} ({len(reports)} row(s))")
    if not args.summary_only:
        for report in reports:
            print_report(report)
    if args.input.is_dir():
        shown_compact = print_compact_summary(reports, args.input, owners, grid_data_mode, args.outlier_limit, skipped,
                                              shift_groups)
        if args.details or not shown_compact:
            if grid_data_mode:
                grouped: dict[Path, list[Report]] = {}
                for report in reports:
                    grouped.setdefault(owners[report.path], []).append(report)
                for data_dir, group_reports in sorted(grouped.items()):
                    directory_check(group_reports, f"GRID SQUARE: {data_dir.parent.name}", outlier_limit=args.outlier_limit)
                directory_check(
                    reports,
                    "DATASET-WIDE SUMMARY ACROSS ALL GRID-SQUARE DATA FOLDERS",
                    outlier_limit=args.outlier_limit,
                    recommended=True,
                )
            else:
                directory_check(reports, outlier_limit=args.outlier_limit, recommended=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
