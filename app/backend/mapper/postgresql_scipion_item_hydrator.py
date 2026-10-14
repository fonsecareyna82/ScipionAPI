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
    Boolean,
    Float,
    Integer,
    String,
    Pointer,
    PointerList,
    Set as ScipionSet,
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
    _PLAIN_SCALARS = frozenset((Boolean, Float, Integer, String))

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

        # SCIPIONAPI-HYDRATOR-PATHS-GREEN-71
        # Derived once per hydrator from its persisted column schema.
        # When columns change, the factory creates a fresh hydrator.
        # Unknown per-row paths remain supported without an unbounded cache.
        self._pathPartsCache = {}
        self._nestedPathPrefixes = set()
        # Pointer-free value path sets, keyed by the exact set of row paths.
        self._refillablePaths = {}
        for path in self._classByPath:
            rawParts = str(path).split(".")
            self._pathPartsCache[str(path)] = tuple(
                part for part in rawParts if part
            )
            # Raw prefixes preserve even unusual path spelling.
            for index in range(1, len(rawParts)):
                self._nestedPathPrefixes.add(".".join(rawParts[:index]))

        self.itemClass = self._resolveClass(
            self.itemClassName,
            required=True,
        )
        self._orderedPaths = tuple(sorted(
            (path for path in self._classByPath if path != self.SELF_LABEL),
            key=lambda path: (path.count("."), path),
        ))

        # Cache path metadata only. Owners, native setters and missing classes
        # are resolved again for each row and path to preserve plugin hooks.
        self._hydrationPlan = tuple(
            (path,
             tuple((part, ".".join(parts[:index + 1]))
                   for index, part in enumerate(parts[:-1])),
             parts[-1], path in self._nestedPathPrefixes)
            for path in self._orderedPaths
            for parts in (self._pathPartsCache[path],)
            if parts
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

        shape = self._getRefillShape(row, values)
        if shape is not None and self._isRefillableShape(values):
            item._runtimeRowShape = shape

        return item

    def refill(self, item, row: Dict[str, Any]):
        """Refill an item returned by build() with a row of the same shape.

        Native Scipion iteration refills one template object per row. Here a
        previous item is reused only when the row carries exactly the value
        paths and optional metadata of the row it was built from: the same
        setters then overwrite every attribute build() would set on a fresh
        object, and all other attributes keep their construction defaults.
        Returns None when that cannot be guaranteed; the caller builds anew.
        """
        row = dict(row or {})
        values = self._normalizeValues(row.get("values"))
        shape = self._getRefillShape(row, values)
        if (
                shape is None
                or type(item) is not self.itemClass
                or getattr(item, "_runtimeRowShape", None) != shape
        ):
            return None

        self._applyBasicMetadata(item, row)
        self._hydratePlannedAttributes(item, values)
        item._postgresqlRuntimeValues = dict(values)
        return item

    def _getRefillShape(self, row: Dict[str, Any], values: Dict[str, Any]):
        # Only the planned hydration of known paths is refill-safe. Custom
        # hydrator hooks, unknown paths and nested Sets always build anew.
        if type(self) is not PostgresqlScipionItemHydrator or any(
                name in vars(self) for name in _REFILL_HOOK_NAMES):
            return None
        if isinstance(self.itemClass, type) and issubclass(self.itemClass, ScipionSet):
            return None
        if not all(isinstance(path, str) and path in self._classByPath for path in values):
            return None
        return (
            id(self),
            frozenset(values),
            row.get("creation") is None,
            row.get("enabled") is None,
        )

    def _isRefillableShape(self, values: Dict[str, Any]) -> bool:
        """Decide from class metadata only, without touching the item.

        Refilling assumes each path is a plain instance attribute: owners must
        use standard attribute access (List appends on __setattr__), no path
        name may be defined on a class (properties, descriptors), and Pointers
        keep resolution state. Anything else is built anew on every row.
        """
        paths = frozenset(values)
        eligible = self._refillablePaths.get(paths)
        if eligible is None:
            eligible = all(self._isRefillablePath(path) for path in paths)
            if len(self._refillablePaths) < 64:
                self._refillablePaths[paths] = eligible
        return eligible

    def _isRefillablePath(self, path: str) -> bool:
        parts = self._pathPartsCache.get(path)
        if not parts:
            return False
        ownerClass = self.itemClass
        for index, part in enumerate(parts):
            if not _hasPlainAttributeAccess(ownerClass):
                return False
            if any(part in vars(klass) for klass in ownerClass.__mro__):
                return False
            attributeClass = self._resolveClass(
                self._classByPath.get(".".join(parts[:index + 1])), required=False,
            )
            if attributeClass is None or issubclass(attributeClass, (Pointer, PointerList)):
                return False
            ownerClass = attributeClass
        return True

    # ------------------------------------------------------------------
    # Native object construction
    # ------------------------------------------------------------------

    def _hydrateAttributes(
            self,
            item,
            values: Dict[str, Any],
    ) -> None:
        """
        Hydrate only the attributes represented by this PostgreSQL row.

        scipion_set_columns describes the union schema of the Set, but
        optional embedded Objects may be absent from an individual item.
        Those absent Objects must remain None so native methods such as
        hasCTF(), hasTransform(), hasOrigin() and hasCoordinate() preserve
        their original Scipion semantics.
        """
        # Reuse the schema order without constructing absent optional objects.
        # Unknown plugin paths and non-string keys retain the generic ordering.
        if all(isinstance(path, str) and path in self._classByPath
               for path in values):
            # Custom hydration hooks retain their original invocation order.
            if (getattr(self._setAttributeValue, "__func__", None)
                    is _DEFAULT_SET_ATTRIBUTE_VALUE
                    and getattr(self._hasNestedPaths, "__func__", None)
                    is _DEFAULT_HAS_NESTED_PATHS
                    and getattr(self._splitPath, "__func__", None)
                    is _DEFAULT_SPLIT_PATH):
                self._hydratePlannedAttributes(item, values)
            else:
                for path in self._orderedPaths:
                    if path in values:
                        self._setAttributeValue(item=item, path=path, value=values[path])
            return

        rowAttributes = [
            (
                str(path),
                value,
            )
            for path, value in values.items()
            if str(path) != self.SELF_LABEL
        ]

        # Parent paths are applied before their descendants:
        #
        # _ctfModel
        # _ctfModel._defocusU
        # _ctfModel._defocusV
        #
        # _setAttributeValue() can still construct missing parents on
        # demand when only a descendant path is available.
        for path, value in sorted(
                rowAttributes,
                key=lambda entry: (
                    entry[0].count("."),
                    entry[0],
                ),
        ):
            self._setAttributeValue(
                item=item,
                path=path,
                value=value,
            )

    def _hydratePlannedAttributes(self, item, values: Dict[str, Any]) -> None:
        """Apply the same native operations as _setAttributeValue to known paths.

        Do not retain owners between paths: a descriptor or traced setter can
        replace a parent while the row is being hydrated. Unknown paths and
        overridden path hooks use the generic method instead.
        """
        for path, parents, attributeName, hasNestedPaths in self._hydrationPlan:
            if path not in values:
                continue
            owner = item
            for part, prefix in parents:
                attribute = getattr(owner, part, None)
                if attribute is None:
                    attributeClass = self._resolveClass(
                        self._classByPath.get(prefix), required=False,
                    )
                    if attributeClass is None:
                        break
                    attribute = self._instantiateClass(
                        attributeClass, self._classByPath.get(prefix),
                    )
                    setattr(owner, part, attribute)
                owner = attribute
            else:
                attribute = getattr(owner, attributeName, None)
                if attribute is None:
                    attributeClass = self._resolveClass(
                        self._classByPath.get(path), required=False,
                    )
                    if attributeClass is None:
                        continue
                    attribute = self._instantiateClass(
                        attributeClass, self._classByPath.get(path),
                    )
                    setattr(owner, attributeName, attribute)
                value = values[path]
                if type(attribute) not in self._PLAIN_SCALARS:
                    if isinstance(attribute, PointerList):
                        self._hydratePointerList(pointerList=attribute, value=value)
                        continue
                    if isinstance(attribute, Pointer):
                        self._hydratePointer(pointer=attribute, value=value)
                        continue
                if value is None and hasNestedPaths:
                    continue
                setter = getattr(attribute, "set", None)
                if callable(setter):
                    setter(value)
                else:
                    setattr(owner, attributeName, value)

    def _setAttributeValue(
            self,
            item,
            path: str,
            value: Any,
    ) -> bool:
        parts = self._pathPartsCache.get(path)
        if parts is None:
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

        # Most paths hold a native scalar. Its exact type cannot be a Pointer
        # or PointerList; custom classes retain the generic type checks.
        if type(attribute) not in self._PLAIN_SCALARS:
            if isinstance(attribute, PointerList):
                return self._hydratePointerList(pointerList=attribute, value=value)
            if isinstance(attribute, Pointer):
                return self._hydratePointer(pointer=attribute, value=value)

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
        return str(path) in self._nestedPathPrefixes

    def _splitPath(
            self,
            path: str,
    ):
        path = str(path)
        parts = self._pathPartsCache.get(path)
        if parts is not None:
            # Preserve the previous public return type and independence.
            return list(parts)

        # Do not retain arbitrary dynamic per-item attribute names.
        return [part for part in path.split(".") if part]

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


# Keep the original identities even when a plugin monkeypatches class methods.
def _hasPlainAttributeAccess(objectClass) -> bool:
    return (
        isinstance(objectClass, type)
        and objectClass.__setattr__ is object.__setattr__
        and objectClass.__getattribute__ is object.__getattribute__
        and getattr(objectClass, "__getattr__", None) is None
    )


# Instance-level replacements of these disable refilling.
_REFILL_HOOK_NAMES = (
    "build", "refill", "_applyBasicMetadata", "_callSetter", "_hydrateAttributes",
    "_hydratePlannedAttributes", "_setAttributeValue", "_hasNestedPaths", "_splitPath",
    "_instantiateClass", "_normalizeValues", "_hydratePointer", "_hydratePointerList",
)
_DEFAULT_SET_ATTRIBUTE_VALUE = PostgresqlScipionItemHydrator._setAttributeValue
_DEFAULT_HAS_NESTED_PATHS = PostgresqlScipionItemHydrator._hasNestedPaths
_DEFAULT_SPLIT_PATH = PostgresqlScipionItemHydrator._splitPath
