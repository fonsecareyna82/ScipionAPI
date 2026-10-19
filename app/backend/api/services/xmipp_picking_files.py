"""Session files of Xmipp's supervised particle picker.

The desktop picker (Java, JMetaDataIO) keeps one ``<micrograph>.pos`` file per
micrograph and a ``config.xmd`` in the protocol's ``extra`` folder. They are
read and written here in exactly the same format, so a session can move
between the web and the desktop picker, and Scipion's readSetOfCoordinates
and Xmipp's automatic picking keep reading them.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

MICROGRAPH_STATES = ("Manual", "Supervised", "Corrected", "Available", "Auto", "Review", "Automatic")
PICKER_MODES = ("Manual", "Supervised", "Available", "Review", "ReadOnly", "Extract", "Automatic")
DEFAULT_PARTICLE_SIZE = 100
DEFAULT_AUTOPICK_PERCENT = 50
DEFAULT_COLOR = -16711936  # java.awt.Color.GREEN, the first picker color.
CONFIG_FILE = "config.xmd"
_HEADER = "# XMIPP_STAR_1 * \n#\n"
_VALUE = "%20s"


@dataclass
class MicrographPicks:
    """Contents of one micrograph's .pos file."""
    state: str = "Available"
    autopickPercent: int = DEFAULT_AUTOPICK_PERCENT
    threshold: float = 0.0
    manual: List[Tuple[int, int]] = field(default_factory=list)
    # (x, y, cost, enabled); enabled is 1, or -1 for rejected particles.
    automatic: List[Tuple[int, int, float, int]] = field(default_factory=list)

    def hasData(self) -> bool:
        return bool(self.manual or self.automatic)

    def activeAutomatic(self) -> List[Tuple[int, int, float, int]]:
        """Automatic particles the picker counts: not rejected, not below threshold."""
        return [p for p in self.automatic if p[3] != -1 and p[2] >= self.threshold]


@dataclass
class PickerConfig:
    """Contents of config.xmd."""
    micrograph: str = ""
    color: int = DEFAULT_COLOR
    particleSize: int = DEFAULT_PARTICLE_SIZE
    autopickPercent: int = DEFAULT_AUTOPICK_PERCENT
    templatesNum: int = 1
    mode: str = "Manual"
    manualParticlesNum: int = 0
    autoParticlesNum: int = 0
    # As stored in config.xmd (IJCommand's encoding). A new session, or a
    # config.xmd without a filters block, has the picker's default filters.
    filters: List[Tuple[str, str]] = field(default_factory=lambda: [
        (encodeFilterText(command), encodeFilterText(options) or "NULL") for command, options in DEFAULT_FILTERS])

    def imageFilters(self) -> List[Tuple[str, str]]:
        """The ImageJ filters the picker applies to the micrographs (command, options)."""
        return [(decodeFilterText(command), "" if args == "NULL" else decodeFilterText(args))
                for command, args in self.filters if command]


# As ParticlePicker when config.xmd has no filters.
DEFAULT_FILTERS = (("Gaussian Blur...", "sigma=2"), ("Enhance Contrast", "saturated=0.4"))


def decodeFilterText(text: str) -> str:
    """A filter command or options as stored by IJCommand (spaces as '_', '_' as '&')."""
    return str(text or "").replace("_", " ").replace("&", "_")


def encodeFilterText(text: str) -> str:
    """As IJCommand.getMdCommand."""
    return str(text or "").replace("_", "&").replace(" ", "_")


def posFileName(micrographFile: str) -> str:
    """Session file of a micrograph: its base name with the .pos extension."""
    base = os.path.basename(str(micrographFile).split("@")[-1])
    return os.path.splitext(base)[0] + ".pos"


def _readBlocks(path: str) -> Dict[str, Tuple[List[str], List[List[str]]]]:
    """Blocks of an XMIPP_STAR loop file: name -> (labels, rows of tokens)."""
    blocks: Dict[str, Tuple[List[str], List[List[str]]]] = {}
    current = None
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("data_"):
                current = line[len("data_"):]
                blocks[current] = ([], [])
            elif current is None or line == "loop_":
                continue
            elif line.startswith("_"):
                blocks[current][0].append(line[1:].split()[0])
            else:
                blocks[current][1].append(line.split())
    return blocks


def _rows(blocks, name) -> List[Dict[str, str]]:
    labels, rows = blocks.get(name, ([], []))
    return [dict(zip(labels, row)) for row in rows]


def _int(value, default=0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def readPos(path: str) -> MicrographPicks:
    if not os.path.isfile(path):
        return MicrographPicks()
    blocks = _readBlocks(path)
    picks = MicrographPicks()
    header = _rows(blocks, "header")
    if header:
        state = header[0].get("pickingMicrographState", "Available")
        picks.state = state if state in MICROGRAPH_STATES else "Available"
        picks.autopickPercent = _int(header[0].get("autopickPercent"), DEFAULT_AUTOPICK_PERCENT)
        picks.threshold = _float(header[0].get("cost"))
    picks.manual = [(_int(r.get("xcoor")), _int(r.get("ycoor"))) for r in _rows(blocks, "particles")]
    picks.automatic = [(_int(r.get("xcoor")), _int(r.get("ycoor")), _float(r.get("cost")),
                        -1 if _int(r.get("enabled"), 1) == -1 else 1)
                       for r in _rows(blocks, "particles_auto")]
    return picks


def _formatFloat(value: float) -> str:
    # Java's String.valueOf(double): always with a decimal part.
    text = repr(float(value))
    return text if ("." in text or "e" in text or "E" in text or "n" in text) else text + ".0"


def writePos(path: str, picks: MicrographPicks) -> None:
    """Write as JMetaDataIO.saveData; a micrograph without particles has no file."""
    if not picks.hasData():
        if os.path.exists(path):
            os.remove(path)
        return
    lines = [_HEADER + "data_header\nloop_\n",
             "_pickingMicrographState\n_autopickPercent\n_cost\n",
             _VALUE % picks.state + _VALUE % int(picks.autopickPercent)
             + _VALUE % _formatFloat(picks.threshold) + "\n",
             "data_particles\nloop_\n_xcoor\n_ycoor\n"]
    lines.extend(_VALUE % int(x) + _VALUE % int(y) + "\n" for x, y in picks.manual)
    if picks.automatic:
        lines.append("data_particles_auto\nloop_\n_xcoor\n_ycoor\n_cost\n_enabled\n")
        lines.extend(_VALUE % int(x) + _VALUE % int(y) + _VALUE % _formatFloat(cost)
                     + _VALUE % (1 if enabled != -1 else -1) + "\n"
                     for x, y, cost, enabled in picks.automatic)
    atomicWrite(path, "".join(lines))


def readConfig(path: str) -> Optional[PickerConfig]:
    if not os.path.isfile(path):
        return None
    blocks = _readBlocks(path)
    properties = _rows(blocks, "properties")
    config = PickerConfig()
    if properties:
        row = properties[0]
        config.micrograph = row.get("micrograph", "")
        config.color = _int(row.get("color"), DEFAULT_COLOR)
        config.particleSize = _int(row.get("particleSize"), DEFAULT_PARTICLE_SIZE) or DEFAULT_PARTICLE_SIZE
        config.autopickPercent = _int(row.get("autopickPercent"), DEFAULT_AUTOPICK_PERCENT) or DEFAULT_AUTOPICK_PERCENT
        config.templatesNum = _int(row.get("templatesNum"), 1) or 1
        mode = row.get("pickingState", "Manual")
        config.mode = mode if mode in PICKER_MODES else "Manual"
        config.manualParticlesNum = _int(row.get("manualParticlesNum"))
        config.autoParticlesNum = _int(row.get("autoParticlesNum"))
    if "filters" in blocks:
        config.filters = []
    labels, rows = blocks.get("filters", ([], []))
    for row in rows:
        values = dict(zip(labels, row))
        config.filters.append((values.get("macroCmd", ""), values.get("macroCmdArgs", "")))
    return config


def writeConfig(path: str, config: PickerConfig) -> None:
    """Write as JMetaDataIO.saveConfig."""
    if not config.micrograph or any(c.isspace() for c in config.micrograph):
        # The desktop picker reopens at this micrograph; a blank would also
        # shift every column of the STAR row.
        raise ValueError("config.xmd needs the name of the current micrograph")
    text = (_HEADER + "data_properties\nloop_\n"
            "_micrograph\n_color\n_particleSize\n_autopickPercent\n_templatesNum\n"
            "_pickingState\n_manualParticlesNum\n_autoParticlesNum\n"
            + _VALUE % config.micrograph + _VALUE % int(config.color)
            + _VALUE % int(config.particleSize) + _VALUE % int(config.autopickPercent)
            + _VALUE % int(config.templatesNum) + _VALUE % config.mode
            + _VALUE % int(config.manualParticlesNum) + _VALUE % int(config.autoParticlesNum) + "\n"
            + "data_filters\nloop_\n_macroCmd\n_macroCmdArgs\n"
            + "".join(_VALUE % command + "%80s" % args + "\n" for command, args in config.filters))
    atomicWrite(path, text)


def atomicWrite(path: str, text: str) -> None:
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    temporary = os.path.join(folder, ".%s.%d.tmp" % (os.path.basename(path), os.getpid()))
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temporary, path)
