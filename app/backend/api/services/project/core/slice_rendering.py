"""Pure 2D-slice pixel manipulation shared by every "render a tomogram/volume
slice as an image" preview path (Coordinates3D, Volumes, metadata image
cells). No Scipion runtime or PostgreSQL state involved - just numpy/PIL.
"""
import io
from typing import Optional, Union

import numpy as np
from fastapi import HTTPException, Response

from app.backend.utils.constants import maxThumbSize


def coords3dPilTo2dTile(imgStk, pilImg) -> Optional[np.ndarray]:
    """
    Convert a PIL tomogram slice into a small 2D float array.

    - Downsamples to <= maxThumbSize without upscaling.
    - Converts to grayscale if needed.
    - Applies highlightSlice/normalizeSlice at most once.
    - Returns float32 2D array; caller can decide final uint8/colormap.
    """
    try:
        width, height = pilImg.size
        scale = min(
            maxThumbSize / float(width),
            maxThumbSize / float(height),
            1.0,
        )
        thumbWidth = max(1, int(round(width * scale)))
        thumbHeight = max(1, int(round(height * scale)))

        if pilImg.mode not in ("L", "I;16", "F"):
            pilGray = pilImg.convert("L")
        else:
            pilGray = pilImg

        if thumbWidth < width or thumbHeight < height:
            pilGray = pilGray.copy()
            pilGray.thumbnail((thumbWidth, thumbHeight))

        arr = np.asarray(pilGray, dtype=np.float32)

        arr = np.squeeze(arr)
        if arr.ndim != 2 or arr.size == 0:
            return None

        try:
            arr = imgStk.highlightSlice(arr)
            arr = imgStk.normalizeSlice(arr)
        except Exception:
            pass

        return arr.astype(np.float32, copy=False)
    except Exception:
        return None


def normalize2dSlice(a: np.ndarray, mode: str = "minmax") -> np.ndarray:
    """
    Normalize a 2D slice into uint8 according to mode: 'minmax' | 'zscore' | 'none'.

    Safeguards:
    - Accepts any numeric dtype.
    - If already uint8 and mode in ('minmax', 'none'), returns a copy directly.
    - Handles NaNs and constant arrays without blowing up.
    """
    if a.ndim != 2:
        raise ValueError("Expected 2D slice")

    arr = np.asarray(a)

    if arr.dtype == np.uint8 and (mode or "minmax").lower() in ("minmax", "none"):
        return arr.copy()

    arr = arr.astype(np.float32, copy=False)
    mode = (mode or "minmax").lower()

    finiteMask = np.isfinite(arr)
    if not finiteMask.all():
        if finiteMask.any():
            fillVal = float(np.nanmedian(arr[finiteMask]))
        else:
            fillVal = 0.0
        arr = np.where(finiteMask, arr, fillVal)

    if mode == "zscore":
        mu = float(np.mean(arr))
        sd = float(np.std(arr))
        if sd == 0.0 or not np.isfinite(sd):
            return np.zeros_like(arr, dtype=np.uint8)
        arr = (arr - mu) / sd
        arr = np.clip(arr, -3.0, 3.0)
        amin, amax = float(arr.min()), float(arr.max())
        if amax <= amin:
            return np.zeros_like(arr, dtype=np.uint8)
        arr = (arr - amin) / (amax - amin + 1e-12)
        return (255.0 * arr).astype(np.uint8)

    amin, amax = float(arr.min()), float(arr.max())
    if (not np.isfinite(amin)) or (not np.isfinite(amax)) or amax <= amin:
        return np.zeros_like(arr, dtype=np.uint8)

    arr = (arr - amin) / (amax - amin + 1e-12)
    return (255.0 * arr).astype(np.uint8)


def renderTomogramSliceFromPath(
        volumePath: str,
        tomogramId: Union[int, str],
        sliceIndex: int,
        axis: str = "z",
        colormap: Optional[str] = None,
        normalize: Optional[str] = "minmax",
        scale: float = 1.0,
        inline: bool = True,
        fmt: str = "webp",
        thumb: Optional[int] = 128,
        fast: bool = True,
        quality: int = 75,
) -> Response:
    from pwem.emlib.image.image_readers import ImageReadersRegistry
    from PIL import Image as PILImage

    from app.backend.utils.volume_utils import readVolumeSlice2d

    axis = (axis or "z").lower()
    if axis not in ("x", "y", "z"):
        axis = "z"

    fmtLower = (fmt or "png").lower()
    if fmtLower in ("jpg", "jpeg"):
        pilFormat = "JPEG"
        mediaType = "image/jpeg"
        saveKw = {"quality": int(quality or 75)}
    elif fmtLower == "webp":
        pilFormat = "WEBP"
        mediaType = "image/webp"
        saveKw = {"quality": int(quality or 75)}
    else:
        pilFormat = "PNG"
        mediaType = "image/png"
        saveKw = {}

    usedColormap = colormap
    gray: Optional[np.ndarray] = None
    depth = 1

    try:
        requestedIndex = int(sliceIndex or 0)
    except Exception:
        requestedIndex = 0
    requestedIndex = max(0, requestedIndex)

    sliceUsed = requestedIndex
    if axis == "z" and fast:
        try:
            reader = ImageReadersRegistry.open(volumePath)

            try:
                images = reader.getImages()
                if hasattr(images, "ndim") and images.ndim == 3:
                    zdim, ydim, xdim = int(images.shape[0]), int(images.shape[1]), int(images.shape[2])
                elif hasattr(images, "ndim") and images.ndim == 2:
                    zdim, ydim, xdim = 1, int(images.shape[0]), int(images.shape[1])
                else:
                    zdim, ydim, xdim = 1, 0, 0
            except Exception:
                zdim, ydim, xdim = 1, 0, 0

            depth = max(zdim, 1)

            k = requestedIndex
            if zdim > 0:
                k = max(0, min(k, zdim - 1))

            try:
                pilImg = reader.getImage(index=k, pilImage=True)
            except Exception:
                try:
                    pilImg = reader.getCentralImage(pilImage=True)
                    if zdim > 0:
                        k = max(0, min(zdim // 2, max(zdim - 1, 0)))
                    else:
                        k = 0
                except Exception:
                    pilImg = reader.getImage(index=0, pilImage=True)
                    k = 0

            arr2d = coords3dPilTo2dTile(reader, pilImg)
            if arr2d is None:
                arrRaw = np.asarray(pilImg)
                if arrRaw.ndim == 3:
                    arr2d = arrRaw.mean(axis=-1)
                else:
                    arr2d = arrRaw.astype(np.float32, copy=False)

            gray = normalize2dSlice(arr2d, mode=normalize)
            sliceUsed = k
        except Exception:
            gray = None

    if gray is None:
        try:
            slice2d, _props, sliceMeta = readVolumeSlice2d(
                str(volumePath),
                sliceIndex=requestedIndex,
                axis=axis,
                maxSide=thumb,
            )
        except HTTPException:
            raise
        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail="Tomogram file not found on disk",
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to read tomogram slice: {e}",
            )

        zdim, ydim, xdim = sliceMeta.get("dims", (1, 1, 1))
        depth = max(int(zdim), 1)

        gray = normalize2dSlice(slice2d, mode=normalize)
        sliceUsed = int(sliceMeta.get("index", requestedIndex))

    if thumb is not None and thumb > 0:
        pilTmp = PILImage.fromarray(gray.astype(np.uint8), mode="L")
        pilTmp.thumbnail((thumb, thumb))
        gray = np.asarray(pilTmp)

        if gray.dtype != np.uint8:
            gray = gray.astype(np.uint8, copy=False)

    imgArray = gray.astype(np.uint8, copy=False)
    pilMode = "L"

    if usedColormap:
        try:
            import matplotlib.cm as cm
            sliceNorm = imgArray.astype(np.float32) / 255.0
            cmapObj = cm.get_cmap(usedColormap)
            rgba = cmapObj(sliceNorm)
            rgb = (rgba[..., :3] * 255.0).clip(0, 255).astype(np.uint8)
            imgArray = rgb
            pilMode = "RGB"
        except Exception:
            usedColormap = None
            imgArray = gray.astype(np.uint8, copy=False)
            pilMode = "L"

    if scale is not None and scale != 1.0:
        try:
            pilScale = PILImage.fromarray(imgArray, mode=pilMode)
            newW = max(1, int(round(pilScale.width * float(scale))))
            newH = max(1, int(round(pilScale.height * float(scale))))
            pilScale = pilScale.resize((newW, newH), resample=PILImage.Resampling.BILINEAR)
            imgArray = np.asarray(pilScale, copy=False)
        except Exception:
            pass

    img = PILImage.fromarray(imgArray, mode=pilMode)

    buf = io.BytesIO()
    img.save(buf, format=pilFormat, **saveKw)

    disp = "inline" if inline else "attachment"
    filename = f"coords3d_{tomogramId}_axis-{axis}_slice-{sliceUsed}.{fmtLower}"

    headers = {
        "Content-Disposition": f'{disp}; filename="{filename}"',
        "Access-Control-Expose-Headers": (
            "Content-Disposition, "
            "X-Preview-Mime, "
            "X-Preview-Width, "
            "X-Preview-Height, "
            "X-Preview-Depth, "
            "X-Preview-Colormap, "
            "X-Preview-Format, "
            "X-Preview-TomogramId"
        ),
        "X-Preview-Mime": mediaType,
        "X-Preview-Width": str(img.width),
        "X-Preview-Height": str(img.height),
        "X-Preview-Depth": str(depth),
        "X-Preview-Colormap": usedColormap or "",
        "X-Preview-Format": pilFormat,
        "X-Preview-TomogramId": str(tomogramId),
    }

    return Response(content=buf.getvalue(), media_type=mediaType, headers=headers)
