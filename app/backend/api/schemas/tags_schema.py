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
import re
from typing import List, Optional

from pydantic import BaseModel, Field, validator

TITLE_MAX = 80
DESCRIPTION_MAX = 1000
TAG_ID_MAX = 128
MAX_TAGS_PER_PROTOCOL = 200
# #rgb, #rgba, #rrggbb or #rrggbbaa
COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
TAG_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")


def _cleanTitle(value):
    if value is None:
        return value
    value = str(value).strip()
    if not value:
        raise ValueError("The title cannot be empty")
    if len(value) > TITLE_MAX:
        raise ValueError("The title can have at most %d characters" % TITLE_MAX)
    return value


def _cleanColor(value):
    if value is None:
        return value
    value = str(value).strip()
    if value and not COLOR_PATTERN.match(value):
        raise ValueError("The colour must be a hex colour such as #3b82f6")
    return value or None


def _cleanDescription(value):
    if value is None:
        return value
    value = str(value)
    if len(value) > DESCRIPTION_MAX:
        raise ValueError("The description can have at most %d characters" % DESCRIPTION_MAX)
    return value


class ProtocolTagCreateIn(BaseModel):
    id: Optional[str] = None
    title: str
    description: Optional[str] = None
    color: Optional[str] = None

    @validator("id")
    def _id(cls, value):
        if value is None:
            return value
        value = str(value).strip()
        if not value:
            return None
        if len(value) > TAG_ID_MAX or not TAG_ID_PATTERN.match(value):
            raise ValueError("Invalid tag id")
        return value

    _title = validator("title", allow_reuse=True)(_cleanTitle)
    _description = validator("description", allow_reuse=True)(_cleanDescription)
    _color = validator("color", allow_reuse=True)(_cleanColor)


class ProtocolTagUpdateIn(BaseModel):
    """Only the fields sent change; description and color can be cleared with null or ""."""

    title: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None

    _title = validator("title", allow_reuse=True)(_cleanTitle)
    _description = validator("description", allow_reuse=True)(_cleanDescription)
    _color = validator("color", allow_reuse=True)(_cleanColor)


class ProtocolTagsSetIn(BaseModel):
    tagIds: List[str] = Field(default_factory=list, max_items=MAX_TAGS_PER_PROTOCOL)

    @validator("tagIds", each_item=True)
    def _tagId(cls, value):
        value = str(value).strip()
        if len(value) > TAG_ID_MAX:
            raise ValueError("Invalid tag id")
        return value
