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
import weakref
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Optional,
)

from pyworkflow.object import (
    OBJECTS_DICT,
    Pointer,
    PointerList,
)


logger = logging.getLogger(__name__)


def setPostgresqlRuntimeParentReference(
        runtimeObject,
        parent,
) -> None:
    """
    Keep the runtime parent available without adding it to the
    persistent Scipion Object graph.

    Native items reconstructed by SqliteFlatMapper keep the parent id,
    but they do not expose their containing Set through _objParent.
    """
    runtimeObject._objParent = None

    runtimeObject._postgresqlRuntimeParentRef = (
        weakref.ref(parent)
        if parent is not None
        else None
    )


def getPostgresqlRuntimeParent(
        runtimeObject,
):
    """
    Return either the native Scipion parent or the detached PostgreSQL
    runtime parent.
    """
    if runtimeObject is None:
        return None

    nativeParent = getattr(
        runtimeObject,
        "_objParent",
        None,
    )

    if nativeParent is not None:
        return nativeParent

    runtimeParentReference = getattr(
        runtimeObject,
        "_postgresqlRuntimeParentRef",
        None,
    )

    if not callable(
            runtimeParentReference
    ):
        return None

    try:
        return runtimeParentReference()

    except Exception:
        return None


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
            pointerResolver: Optional[
                Callable[[Dict[str, Any]], Any]
            ] = None,
    ):
        if not itemClassName:
            raise ValueError("itemClassName is required")

        self.itemClassName = str(itemClassName)
        self.parent = parent
        self.classes = self._loadClasses(classes)
        self.columns = self._normalizeColumns(
            columns
        )

        self.pointerResolver = (
            pointerResolver
            if callable(pointerResolver)
            else None
        )

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

        if isinstance(
                attribute,
                PointerList,
        ):
            return self._hydratePointerList(
                pointerList=attribute,
                value=value,
            )

        if isinstance(
                attribute,
                Pointer,
        ):
            return self._hydratePointer(
                pointer=attribute,
                value=value,
            )

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

    def _hydratePointer(
            self,
            pointer: Pointer,
            value: Any,
    ) -> bool:
        reference = (
            self._normalizePointerReference(
                value
            )
        )

        pointer._postgresqlRuntimeReference = dict(
            reference
        )

        target = self._resolvePointerReference(
            reference
        )

        if target is not None:
            pointer.set(
                target
            )

        extended = reference.get(
            "extended"
        )

        if extended not in (
                None,
                "",
        ):
            pointer.setExtended(
                str(extended)
            )

        return True

    def _hydratePointerList(
            self,
            pointerList: PointerList,
            value: Any,
    ) -> bool:
        references = (
            self._normalizePointerReferences(
                value
            )
        )

        pointerList.clear()

        normalizedReferences = []

        for reference in references:
            pointer = Pointer()

            self._hydratePointer(
                pointer=pointer,
                value=reference,
            )

            pointerList.append(
                pointer
            )

            normalizedReferences.append(
                dict(
                    getattr(
                        pointer,
                        "_postgresqlRuntimeReference",
                        {},
                    )
                )
            )

        pointerList._postgresqlRuntimeReferences = (
            normalizedReferences
        )

        return True

    def _resolvePointerReference(
            self,
            reference: Dict[str, Any],
    ):
        if not reference:
            return None

        if self.pointerResolver is None:
            return None

        try:
            return self.pointerResolver(
                dict(reference)
            )
        except Exception:
            logger.debug(
                "Could not resolve PostgreSQL item pointer. "
                "itemClass=%s reference=%s",
                self.itemClassName,
                reference,
                exc_info=True,
            )

            return None

    def _normalizePointerReference(
            self,
            value: Any,
    ) -> Dict[str, Any]:
        if isinstance(
                value,
                dict,
        ):
            return dict(value)

        if isinstance(
                value,
                str,
        ):
            value = value.strip()

            if not value:
                return {}

            try:
                parsed = json.loads(
                    value
                )
            except Exception:
                return {
                    "version": 0,
                    "kind": "pointer",
                    "uniqueId": value,
                    "extended": "",
                }

            if isinstance(
                    parsed,
                    dict,
            ):
                return dict(parsed)

        return {}

    def _normalizePointerReferences(
            self,
            value: Any,
    ):
        if value is None:
            return []

        if isinstance(
                value,
                str,
        ):
            value = value.strip()

            if not value:
                return []

            try:
                value = json.loads(
                    value
                )
            except Exception:
                return [
                    self._normalizePointerReference(
                        value
                    )
                ]

        if isinstance(
                value,
                dict,
        ):
            return [
                dict(value)
            ]

        if not isinstance(
                value,
                (
                        list,
                        tuple,
                ),
        ):
            return []

        return [
            reference
            for reference in (
                self._normalizePointerReference(
                    item
                )
                for item in value
            )
            if reference
        ]

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
            # Keep the runtime parent outside the Scipion Object graph.
            #
            # Otherwise clone()/copyInfo() may recursively copy:
            #
            # item -> Set -> protocol -> internal protocol attributes
            #
            # into a newly created output item and corrupt its SQLite
            # item schema.
            setPostgresqlRuntimeParentReference(
                runtimeObject=item,
                parent=self.parent,
            )

            parentIdGetter = getattr(
                self.parent,
                "getObjId",
                None,
            )

            if callable(parentIdGetter):
                try:
                    item._objParentId = (
                        parentIdGetter()
                    )

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