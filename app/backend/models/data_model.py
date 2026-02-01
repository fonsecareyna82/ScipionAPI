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

from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Union


class Volume3dResponse(BaseModel):
    dims: List[int] = Field(..., description="Volume dimensions in Z,Y,X order")
    values: List[float] = Field(..., description="Flattened voxel values (Z-major)")


class AnalyzeViewerResolveContextIn(BaseModel):
    outputName: str = Field(..., min_length=1)
    protocolLabel: Optional[str] = None
    pointerClass: Optional[str] = None
    paramClass: Optional[str] = None
    info: Optional[str] = None
    value: Optional[str] = None
    parentId: Optional[Union[int, str]] = None

    class Config:
        extra = "ignore"


class AnalyzeViewerResolveDecisionOut(BaseModel):
    handled: bool = False
    url: Optional[str] = None
    target: Literal["_self", "_blank"] = "_blank"
    kind: Optional[str] = None
    message: Optional[str] = None

    class Config:
        extra = "ignore"


class RemoteEntryModel(BaseModel):
    name: str
    path: str  # leaf basename (client joins cwd + leaf)
    isDir: bool
    size: Optional[int] = None
    mime: Optional[str] = None


class RemoteListResultModel(BaseModel):
    cwd: str  # root-relative dir path ("" means root)
    dirName: Optional[str] = None  # absolute dir path (debug/compat)
    items: List[RemoteEntryModel]