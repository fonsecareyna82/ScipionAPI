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
import json
import logging
from typing import Any, Dict, Iterable, Optional

from pyworkflow.object import (
    OBJECTS_DICT,
    Pointer,
    PointerList,
)


logger = logging.getLogger(__name__)


class PostgresqlScipionItemHydrator:
    """
    Build native Scipion objects from rows stored in scipion_set_items.

    Attribute paths and their Scipion classes come from
    scipion_set_columns.
    """

    SELF_LABEL = "self"

    def __init__(
            self,
            itemClassName: str,
            columns: Iterable[Dict[str, Any]],
            parent=None,
            classes: Optional[Dict[str, type]] = None,
    ):
        if not itemClassName:
            raise ValueError("itemClassName is required")

        self.itemClassName = str(itemClassName)
        self.parent = parent
        self.classes = self._loadClasses(classes)
        self.columns = self._normalizeColumns(columns)

        self._classByPath = {
            column["labelProperty"]: column.get("className")
            for column in self.columns
            if column.get("labelProperty")
        }

        self.itemClass = self._resolveClass(
            self.itemClassName,
            required=True,
        )

    def __call__(self, row: Dict[str, Any]):
        return self.build(row)

    def build(self, row: Dict[str, Any]):
        row = dict(row or {})
        item = self._instantiateClass(
            self.itemClass,
            self.itemClassName,
        )

        self._applyBasicMetadata(item, row)

        values = self._normalizeValues(
            row.get("values")
        )

        self._hydrateAttributes(
            item=item,
            values=values,
        )

        # Keep the complete PostgreSQL representation for debugging and for
        # values added for runtime convenience that are not native attributes.
        item._postgresqlRuntimeValues = dict(values)

        return item

    # ------------------------------------------------------------------
    # Native object construction
    # ------------------------------------------------------------------

    def _hydrateAttributes(
            self,
            item,
            values: Dict[str, Any],
    ) -> None:
        # Construct complex parent attributes before assigning nested values.
        for path in sorted(
                self._classByPath,
                key=lambda value: (
                    value.count("."),
                    value,
                ),
        ):
            self._ensureAttributePath(
                item,
                path,
            )

        for path, value in values.items():
            path = str(path)

            if path == self.SELF_LABEL:
                continue

            self._setAttributeValue(
                item=item,
                path=path,
                value=value,
            )

    def _ensureAttributePath(
            self,
            item,
            path: str,
    ):
        current = item
        parts = self._splitPath(path)

        for index, part in enumerate(parts):
            prefix = ".".join(
                parts[:index + 1]
            )

            attribute = getattr(
                current,
                part,
                None,
            )

            if attribute is None:
                className = self._classByPath.get(
                    prefix
                )

                attributeClass = self._resolveClass(
                    className,
                    required=False,
                )

                if attributeClass is None:
                    return None

                attribute = self._instantiateClass(
                    attributeClass,
                    className,
                )

                setattr(
                    current,
                    part,
                    attribute,
                )

            current = attribute

        return current

    def _setAttributeValue(
            self,
            item,
            path: str,
            value: Any,
    ) -> bool:
        parts = self._splitPath(path)

        if not parts:
            return False

        owner = item

        for index, part in enumerate(parts[:-1]):
            attribute = getattr(
                owner,
                part,
                None,
            )

            if attribute is None:
                prefix = ".".join(
                    parts[:index + 1]
                )

                attributeClass = self._resolveClass(
                    self._classByPath.get(prefix),
                    required=False,
                )

                if attributeClass is None:
                    return False

                attribute = self._instantiateClass(
                    attributeClass,
                    self._classByPath.get(prefix),
                )

                setattr(
                    owner,
                    part,
                    attribute,
                )

            owner = attribute

        attributeName = parts[-1]

        attribute = getattr(
            owner,
            attributeName,
            None,
        )

        if attribute is None:
            attributeClass = self._resolveClass(
                self._classByPath.get(path),
                required=False,
            )

            if attributeClass is None:
                # PostgreSQL may contain convenience values such as
                # bottomLeftX that are not native Scipion attributes.
                return False

            attribute = self._instantiateClass(
                attributeClass,
                self._classByPath.get(path),
            )

            setattr(
                owner,
                attributeName,
                attribute,
            )

        # Pointer relationships are restored separately from the canonical
        # PostgreSQL relation tables.
        if isinstance(
                attribute,
                (Pointer, PointerList),
        ):
            return False

        # Complex objects usually appear together with nested paths. Their
        # own stored value is commonly None, so do not replace the object.
        if (
                value is None
                and self._hasNestedPaths(path)
        ):
            return True

        setter = getattr(
            attribute,
            "set",
            None,
        )

        if callable(setter):
            setter(value)
        else:
            setattr(
                owner,
                attributeName,
                value,
            )

        return True

    # ------------------------------------------------------------------
    # Basic Scipion metadata
    # ------------------------------------------------------------------

    def _applyBasicMetadata(
            self,
            item,
            row: Dict[str, Any],
    ) -> None:
        itemId = row.get("scipionItemId")

        if itemId is None:
            itemId = row.get("id")

        self._callSetter(
            item,
            "setObjId",
            self._toOptionalInt(itemId),
        )

        self._callSetter(
            item,
            "setObjLabel",
            row.get("label") or "",
        )

        self._callSetter(
            item,
            "setObjComment",
            row.get("comment") or "",
        )

        if row.get("creation") is not None:
            self._callSetter(
                item,
                "setObjCreation",
                row.get("creation"),
            )

        enabled = row.get("enabled")

        if enabled is not None:
            self._callSetter(
                item,
                "setEnabled",
                bool(enabled),
            )

        if self.parent is not None:
            item._objParent = self.parent

            parentIdGetter = getattr(
                self.parent,
                "getObjId",
                None,
            )

            if callable(parentIdGetter):
                try:
                    item._objParentId = parentIdGetter()
                except Exception:
                    item._objParentId = None

    # ------------------------------------------------------------------
    # Class resolution
    # ------------------------------------------------------------------

    def _loadClasses(
            self,
            extraClasses: Optional[Dict[str, type]],
    ) -> Dict[str, type]:
        classes = dict(
            OBJECTS_DICT or {}
        )

        try:
            from pwem import Domain

            classes.update(
                Domain.getObjects() or {}
            )
        except Exception:
            logger.debug(
                "Could not load Scipion Domain objects.",
                exc_info=True,
            )

        if extraClasses:
            classes.update(
                extraClasses
            )

        return classes

    def _resolveClass(
            self,
            className: Optional[str],
            required: bool,
    ):
        if not className:
            if required:
                raise ValueError(
                    "Cannot resolve an empty Scipion class name"
                )

            return None

        objectClass = self.classes.get(
            str(className)
        )

        if objectClass is None and required:
            raise ValueError(
                "Scipion class '%s' was not found in Domain.getObjects() "
                "or pyworkflow.object.OBJECTS_DICT"
                % className
            )

        return objectClass

    def _instantiateClass(
            self,
            objectClass,
            className: str,
    ):
        try:
            return objectClass()
        except Exception as exc:
            raise TypeError(
                "Could not instantiate Scipion class '%s'"
                % className
            ) from exc

    # ------------------------------------------------------------------
    # Normalization helpers
    # ------------------------------------------------------------------

    def _normalizeColumns(
            self,
            columns,
    ):
        if isinstance(columns, dict):
            columns = columns.values()

        result = []

        for column in columns or []:
            column = dict(column or {})
            labelProperty = column.get(
                "labelProperty"
            )

            if not labelProperty:
                continue

            column["labelProperty"] = str(
                labelProperty
            )

            result.append(column)

        return result

    def _normalizeValues(
            self,
            values,
    ) -> Dict[str, Any]:
        if isinstance(values, dict):
            return dict(values)

        if isinstance(values, str):
            try:
                parsed = json.loads(values)
            except Exception:
                return {}

            return (
                dict(parsed)
                if isinstance(parsed, dict)
                else {}
            )

        return {}

    def _hasNestedPaths(
            self,
            path: str,
    ) -> bool:
        prefix = "%s." % path

        return any(
            candidate.startswith(prefix)
            for candidate in self._classByPath
        )

    def _splitPath(
            self,
            path: str,
    ):
        return [
            part
            for part in str(path).split(".")
            if part
        ]

    def _callSetter(
            self,
            item,
            setterName: str,
            value,
    ) -> None:
        setter = getattr(
            item,
            setterName,
            None,
        )

        if callable(setter):
            setter(value)
            return

        attributeName = {
            "setObjId": "_objId",
            "setObjLabel": "_objLabel",
            "setObjComment": "_objComment",
            "setObjCreation": "_objCreation",
            "setEnabled": "_objEnabled",
        }.get(setterName)

        if attributeName:
            setattr(
                item,
                attributeName,
                value,
            )

    def _toOptionalInt(
            self,
            value,
    ):
        if value in (None, ""):
            return None

        try:
            return int(value)
        except (TypeError, ValueError):
            return value