from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .ctf import executeCtfPreviewWizard
from .filter import (
    executeFilterPreviewWizard,
    executeGaussianPreviewWizard,
)
from .generic import (
    executeBoxSizeWizard,
    executeComputeLaneSelectorWizard,
    executeConsensusRadiusWizard,
    executeGenericComputeWizard,
    executeNumberOfClassesWizard,
)
from .mask_radius import (
    executeMaskRadiusWizard,
    executeMaskRadiiWizard,
)
from .downsample import executeDownsamplePreviewWizard
from .point_in_volume import executePointInVolumeWizard

HANDLERS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "compute": executeGenericComputeWizard,
    "box_size": executeBoxSizeWizard,
    "consensus_radius": executeConsensusRadiusWizard,
    "number_of_classes": executeNumberOfClassesWizard,
    "compute_lane_selector": executeComputeLaneSelectorWizard,
    "mask_radius": executeMaskRadiusWizard,
    "mask_radii": executeMaskRadiiWizard,
    "ctf_preview": executeCtfPreviewWizard,
    "filter_preview": executeFilterPreviewWizard,
    "gaussian_preview": executeGaussianPreviewWizard,
    "downsample_preview": executeDownsamplePreviewWizard,
    "point_in_volume": executePointInVolumeWizard,
}


def executeWizardHandler(
    *,
    kind: str,
    wizardClass,
    protocol,
    paramName: str,
    descriptor: Optional[Dict[str, Any]] = None,
    wizardInputs: Optional[Dict[str, Any]] = None,
    currentProject=None,
    projectId: Optional[int] = None,
) -> Dict[str, Any]:
    handler = HANDLERS.get(kind, executeGenericComputeWizard)
    return handler(
        wizardClass=wizardClass,
        protocol=protocol,
        paramName=paramName,
        descriptor=descriptor or {},
        wizardInputs=wizardInputs or {},
        currentProject=currentProject,
        projectId=projectId,
    )