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
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import psycopg2.extras


class ScipionObjectPostgresqlMapper:
    """Register Scipion object classes and their persistent attributes in PostgreSQL."""

    def __init__(self, db):
        self.db = db

    def registerObjectTypeFromObject(
        self,
        scipionObj: Any,
        mapperKind: Optional[str] = None,
        includeProperties: bool = True,
        includeNestedProperties: bool = True,
        classSchema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        typeId = self.registerObjectType(scipionObj, mapperKind=mapperKind, classSchema=classSchema)
        propertiesCount = 0

        if includeProperties:
            propertiesCount = self.registerObjectTypeProperties(
                typeId,
                scipionObj,
                includeNestedProperties=includeNestedProperties,
            )

        return {
            "typeId": typeId,
            "className": self._getClassName(scipionObj),
            "propertiesCount": propertiesCount,
        }

    def registerObjectType(
        self,
        scipionObj: Any,
        mapperKind: Optional[str] = None,
        classSchema: Optional[Dict[str, Any]] = None,
    ) -> int:
        className = self._getClassName(scipionObj)
        if not className:
            raise ValueError("Cannot register a Scipion object type without className")

        moduleName = self._getModuleName(scipionObj)
        baseClassName = self._getBaseClassName(scipionObj)
        resolvedMapperKind = mapperKind or self._guessMapperKind(scipionObj)
        schema = classSchema or {}

        cur = self.db.execute(
            """
            INSERT INTO scipion_object_types (
                "className",
                "moduleName",
                "baseClassName",
                "mapperKind",
                "schema"
            )
            VALUES (%s, %s, %s, %s, %s::jsonb)
            ON CONFLICT ("className")
            DO UPDATE SET
                "moduleName" = EXCLUDED."moduleName",
                "baseClassName" = EXCLUDED."baseClassName",
                "mapperKind" = EXCLUDED."mapperKind",
                "schema" = scipion_object_types."schema" || EXCLUDED."schema",
                "updatedAt" = NOW()
            RETURNING id
            """,
            (
                className,
                moduleName,
                baseClassName,
                resolvedMapperKind,
                self._jsonParam(schema),
            ),
        )
        row = cur.fetchone()
        return int(row["id"])

    def registerObjectTypeProperties(
        self,
        typeId: int,
        scipionObj: Any,
        includeNestedProperties: bool = True,
    ) -> int:
        properties = list(self._iterProperties(scipionObj, includeNestedProperties=includeNestedProperties))
        if not properties:
            return 0

        with self.db.transaction():
            for prop in properties:
                self.db.execute(
                    """
                    INSERT INTO scipion_object_type_properties (
                        "typeId",
                        "propertyPath",
                        "className",
                        "valueKind",
                        "isPointer",
                        "isNested",
                        "schema"
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT ("typeId", "propertyPath")
                    DO UPDATE SET
                        "className" = EXCLUDED."className",
                        "valueKind" = EXCLUDED."valueKind",
                        "isPointer" = EXCLUDED."isPointer",
                        "isNested" = EXCLUDED."isNested",
                        "schema" = scipion_object_type_properties."schema" || EXCLUDED."schema",
                        "updatedAt" = NOW()
                    """,
                    (
                        typeId,
                        prop["propertyPath"],
                        prop["className"],
                        prop["valueKind"],
                        prop["isPointer"],
                        prop["isNested"],
                        self._jsonParam(prop.get("schema") or {}),
                    ),
                    commit=False,
                )

        return len(properties)

    def getObjectType(self, className: str) -> Optional[Dict[str, Any]]:
        return self.db.fetchOne(
            """
            SELECT id, "className", "moduleName", "baseClassName", "mapperKind", "schema", "createdAt", "updatedAt"
              FROM scipion_object_types
             WHERE "className" = %s
            """,
            (className,),
        )

    def listObjectTypeProperties(self, className: str) -> List[Dict[str, Any]]:
        return self.db.fetchAll(
            """
            SELECT p.id,
                   p."typeId",
                   p."propertyPath",
                   p."className",
                   p."valueKind",
                   p."isPointer",
                   p."isNested",
                   p."schema",
                   p."createdAt",
                   p."updatedAt"
              FROM scipion_object_type_properties p
              JOIN scipion_object_types t
                ON t.id = p."typeId"
             WHERE t."className" = %s
             ORDER BY p."propertyPath" ASC
            """,
            (className,),
        )

    def _iterProperties(
        self,
        scipionObj: Any,
        prefix: str = "",
        includeNestedProperties: bool = True,
        visited: Optional[Set[int]] = None,
    ) -> Iterable[Dict[str, Any]]:
        visited = visited or set()
        objIdentity = id(scipionObj)
        if objIdentity in visited:
            return
        visited.add(objIdentity)

        for attrName, attrValue in self._getAttributesToStore(scipionObj):
            propertyPath = f"{prefix}.{attrName}" if prefix else str(attrName)
            childAttributes = self._getAttributesToStore(attrValue)
            isPointer = self._isPointer(attrValue)
            isNested = bool(childAttributes)

            yield {
                "propertyPath": propertyPath,
                "className": self._getClassName(attrValue),
                "valueKind": self._getValueKind(attrValue, isPointer=isPointer, isNested=isNested),
                "isPointer": isPointer,
                "isNested": isNested,
                "schema": {
                    "moduleName": self._getModuleName(attrValue),
                    "baseClassName": self._getBaseClassName(attrValue),
                },
            }

            if includeNestedProperties and isNested:
                yield from self._iterProperties(
                    attrValue,
                    prefix=propertyPath,
                    includeNestedProperties=includeNestedProperties,
                    visited=visited,
                )

    def _getAttributesToStore(self, scipionObj: Any) -> List[Tuple[str, Any]]:
        getter = getattr(scipionObj, "getAttributesToStore", None)
        if not callable(getter):
            return []

        try:
            return [(str(name), value) for name, value in getter()]
        except Exception:
            return []

    def _getClassName(self, scipionObj: Any) -> Optional[str]:
        getter = getattr(scipionObj, "getClassName", None)
        if callable(getter):
            try:
                className = getter()
                if className:
                    return str(className)
            except Exception:
                pass

        if scipionObj is None:
            return None
        return scipionObj.__class__.__name__

    def _getModuleName(self, scipionObj: Any) -> Optional[str]:
        if scipionObj is None:
            return None
        moduleName = getattr(scipionObj.__class__, "__module__", None)
        return str(moduleName) if moduleName else None

    def _getBaseClassName(self, scipionObj: Any) -> Optional[str]:
        if scipionObj is None:
            return None
        bases = getattr(scipionObj.__class__, "__bases__", None) or []
        if not bases:
            return None
        return bases[0].__name__

    def _guessMapperKind(self, scipionObj: Any) -> str:
        className = self._getClassName(scipionObj) or ""
        if self._isPointer(scipionObj):
            return "pointer"
        if className.startswith("SetOf"):
            return "flat_set"
        if self._getAttributesToStore(scipionObj):
            return "tree"
        return "scalar"

    def _getValueKind(self, scipionObj: Any, isPointer: bool, isNested: bool) -> str:
        if isPointer:
            return "pointer"
        if isNested:
            return "object"
        className = self._getClassName(scipionObj)
        if className:
            return className
        return "scalar"

    def _isPointer(self, scipionObj: Any) -> bool:
        checker = getattr(scipionObj, "isPointer", None)
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception:
            return False

    def _jsonParam(self, value: Dict[str, Any]) -> Any:
        return psycopg2.extras.Json(value or {}, dumps=json.dumps)
