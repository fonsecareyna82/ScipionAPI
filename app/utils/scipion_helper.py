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
from pyworkflow.object import Scalar


def toSerializable(obj):
    """Convert complex Python objects into JSON-serializable structures, preserving full dict order recursively."""
    from datetime import datetime, date
    from decimal import Decimal

    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    elif isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        ordered_dict = {}
        for k, v in obj.items():
            ordered_dict[k] = toSerializable(v)
        return ordered_dict
    elif isinstance(obj, (list, tuple, set)):
        return [toSerializable(item) for item in obj]
    elif hasattr(obj, "get") and callable(getattr(obj, "get")):  # Scalar support
        return obj.get()
    elif hasattr(obj, "__dict__"):  # Custom class
        excluded_keys = ['__module__', '__init__', '__doc__', '_dist', '_plugin']
        param_dict = {}
        for k, v in obj.__dict__.items():
            if k not in excluded_keys:
                param_dict[k] = toSerializable(v)
        return param_dict
    else:
        return str(obj)

def serializeToJson(obj):
    """Serialize any Python object to JSON, preserving order of all dictionaries and nested structures."""
    return toSerializable(obj)

