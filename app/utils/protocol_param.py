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
from pyworkflow.object import CsvList
from pyworkflow.protocol.params import (
    BooleanParam,
    EnumParam,
    FloatParam,
    IntParam,
    StringParam,
)


def castProtocolParamValue(param, rawValue):
    """Cast a raw form value to its Scipion parameter type."""
    if isinstance(param, EnumParam):
        if isinstance(rawValue, int):
            return rawValue

        try:
            return param.choices.index(str(rawValue))
        except ValueError:
            for index, choice in enumerate(param.choices):
                if str(choice).lower() == str(rawValue).lower():
                    return index

            return 0

    if isinstance(param, IntParam):
        return int(rawValue) if rawValue not in (None, "") else None

    if isinstance(param, FloatParam):
        return float(rawValue) if rawValue not in (None, "") else None

    if isinstance(param, BooleanParam):
        return str(rawValue).lower() in (
            "true",
            "1",
            "yes",
            "y",
        )

    if isinstance(param, StringParam):
        return str(rawValue) if rawValue is not None else None

    if isinstance(param, CsvList):
        return [rawValue]

    return rawValue