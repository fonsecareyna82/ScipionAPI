# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de  Bioinformatica of Centro Nacional de Biotecnologia , CSIC
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
# app/backend/utils/volume_utils.py
from pathlib import Path
from dataclasses import dataclass
from functools import lru_cache
from typing import Tuple, Dict, Any
import numpy as np
from pwem.emlib.image.image_readers import ImageReadersRegistry


@dataclass(frozen=True)
class VolumeSignature:
    path: str
    mtime_ns: int
    size: int


def buildVolumeSignature(p: Path) -> VolumeSignature:
    st = p.stat()
    return VolumeSignature(str(p), st.st_mtime_ns, st.st_size)


@lru_cache(maxsize=8)
def _readVolumeCached(sig: VolumeSignature) -> Tuple[np.ndarray, Dict[str, Any]]:
    imgStk = ImageReadersRegistry.open(sig.path)
    data = np.asarray(imgStk.getImages())
    if data.ndim not in (2, 3):
        data = np.squeeze(data)
        if data.ndim not in (2, 3):
            raise ValueError(f"Unsupported dimensionality: {data.shape}")
    try:
        props = imgStk.getProperties() or {}
    except Exception:
        props = {}
    return np.asarray(data, dtype=np.float32), props


def readVolumeArray3d(volumePath: str) -> Tuple[np.ndarray, Dict[str, Any]]:
    p = Path(volumePath)
    if not p.exists():
        raise FileNotFoundError(volumePath)
    sig = buildVolumeSignature(p)
    arr, props = _readVolumeCached(sig)
    if arr.ndim == 2:
        arr = arr[None, ...]  # (1, Y, X)
    elif arr.ndim != 3:
        raise ValueError(f"Unsupported volume shape {arr.shape}")
    return arr.astype(np.float32, copy=False), props
