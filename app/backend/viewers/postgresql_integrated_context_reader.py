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
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper
from app.backend.viewers.postgresql_coords3d_reader import PostgresqlCoords3dReader
from app.backend.viewers.postgresql_ctftomo_reader import PostgresqlCtftomoReader
from app.backend.viewers.postgresql_tiltseries_reader import PostgresqlTiltSeriesReader

logger = logging.getLogger(__name__)


class PostgresqlIntegratedContextReader:
    def __init__(self, db, projectId: int, protocolId: int, outputName: str):
        self.db = db
        self.projectId = projectId
        self.protocolId = protocolId
        self.outputName = outputName
        self.setMapper = ScipionSetPostgresqlMapper(db)
        self._rootStoredSet = None
        self.lastSkipReason = None

    def hasOutput(self) -> bool:
        storedSet = self._getRootStoredSet()
        return storedSet is not None and self._getIntegratedKind(storedSet) is not None

    def getContext(self) -> Optional[Dict[str, Any]]:
        self.lastSkipReason = None

        storedSet = self._getRootStoredSet()
        if storedSet is None:
            self.lastSkipReason = "stored_set_not_found"
            return None

        rootKind = self._getIntegratedKind(storedSet)
        if rootKind is None:
            self.lastSkipReason = "unsupported_integrated_context_kind"
            return None

        links = {
            "tiltSeries": None,
            "ctf": None,
            "tomogram": None,
            "coordinates3d": None,
        }
        summaries = {
            "tiltSeries": None,
            "ctf": None,
            "tomogram": None,
            "coordinates3d": None,
        }
        relationsByKey: Dict[str, Dict[str, Any]] = {}

        links[rootKind] = self._buildLink(
            protocolId=self.protocolId,
            outputName=self.outputName,
            storedSet=storedSet,
            statusValue="available",
        )
        summaries[rootKind] = self._buildSummary(storedSet)

        self._mergeRootRelations(
            rootKind=rootKind,
            storedSet=storedSet,
            relationsByKey=relationsByKey,
            links=links,
            summaries=summaries,
        )

        self._mergeRelatedStoredSets(
            rootStoredSet=storedSet,
            links=links,
            summaries=summaries,
            relationsByKey=relationsByKey,
        )

        return {
            "root": {
                "projectId": self.projectId,
                "protocolId": self.protocolId,
                "outputName": self.outputName,
                "outputClass": storedSet.get("setClassName") or storedSet.get("itemClassName"),
            },
            "links": self._safeValue(links),
            "summaries": self._safeValue(summaries),
            "relations": self._safeValue(
                {
                    "items": list(relationsByKey.values()),
                }
            ),
        }

    def _getRootStoredSet(self) -> Optional[Dict[str, Any]]:
        if self._rootStoredSet is None:
            try:
                self._rootStoredSet = self.setMapper.getStoredSet(
                    projectId=self.projectId,
                    protocolDbId=self.protocolId,
                    outputName=self.outputName,
                    limit=None,
                    offset=0,
                )
            except Exception:
                logger.debug(
                    "Could not load PostgreSQL root stored set for integrated context. "
                    "projectId=%s protocolId=%s outputName=%s",
                    self.projectId,
                    self.protocolId,
                    self.outputName,
                    exc_info=True,
                )
                self._rootStoredSet = None

        return self._rootStoredSet

    def _getIntegratedKind(self, storedSet: Dict[str, Any]) -> Optional[str]:
        classText = "%s %s" % (
            storedSet.get("setClassName") or "",
            storedSet.get("itemClassName") or "",
        )
        classText = classText.replace(" ", "").lower()

        if "setofcoordinates3d" in classText or "coordinate3d" in classText:
            return "coordinates3d"

        if "setofctftomoseries" in classText or "ctftomoseries" in classText:
            return "ctf"

        if "setoftiltseries" in classText or "tiltseries" in classText:
            return "tiltSeries"

        if "setoftomograms" in classText or "tomogram" in classText:
            return "tomogram"

        return None

    def _getStoredSetProperty(
            self,
            storedSet: Dict[str, Any],
            key: str,
            default=None,
    ):
        properties = storedSet.get("properties") or {}

        if isinstance(properties, str):
            try:
                properties = json.loads(properties)
            except Exception:
                properties = {}

        if isinstance(properties, dict) and key in properties:
            return properties.get(key)

        for item in storedSet.get("setProperties") or []:
            if str(item.get("key")) == str(key):
                return item.get("value")

        return default

    def _buildLink(
            self,
            protocolId: Any,
            outputName: Any,
            storedSet: Dict[str, Any],
            label: Optional[str] = None,
            statusValue: str = "available",
    ) -> Dict[str, Any]:
        return {
            "protocolId": protocolId,
            "outputName": outputName,
            "itemId": storedSet.get("objectId") or storedSet.get("id"),
            "label": label or outputName,
            "status": statusValue,
        }

    def _buildSummary(
            self,
            storedSet: Dict[str, Any],
            extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        items = storedSet.get("items") or []
        itemsCount = self._getStoredSetProperty(storedSet, "itemsCount", None)

        if itemsCount is None:
            itemsCount = len(items)

        summary = {
            "objectClass": storedSet.get("setClassName") or storedSet.get("itemClassName"),
            "objectId": storedSet.get("objectId") or storedSet.get("id"),
            "size": itemsCount,
            "fileName": self._getStoredSetProperty(storedSet, "fileName", None),
            "samplingRate": self._getStoredSetProperty(storedSet, "samplingRate", None),
        }

        if extra:
            summary.update(extra)

        return summary

    def _firstValueByName(
            self,
            values: Dict[str, Any],
            names: List[str],
    ):
        normalizedNames = {
            self._normalizeName(name)
            for name in names
        }

        for key, value in (values or {}).items():
            if self._normalizeName(key) in normalizedNames:
                return value

        return None

    def _normalizeName(self, value: Any) -> str:
        return str(value).replace("_", "").replace(".", "").replace("-", "").lower()

    def _addRelation(
            self,
            relationsByKey: Dict[str, Dict[str, Any]],
            keyValue: Any,
            **values: Any,
    ) -> None:
        key = str(keyValue) if keyValue is not None else ""
        if not key:
            return

        relation = relationsByKey.setdefault(
            key,
            {
                "key": key,
                "label": key,
            },
        )

        for name, value in values.items():
            if value is not None:
                relation[name] = value

    def _addTiltSeriesRelations(
            self,
            relationsByKey: Dict[str, Dict[str, Any]],
            items: List[Dict[str, Any]],
    ) -> None:
        for index, item in enumerate(items or []):
            tiltSeriesId = item.get("tiltSeriesId") or item.get("id") or index
            label = item.get("label") or str(tiltSeriesId)

            self._addRelation(
                relationsByKey,
                tiltSeriesId,
                tiltSeriesId=tiltSeriesId,
                label=label,
            )

    def _addCtftomoRelations(
            self,
            relationsByKey: Dict[str, Dict[str, Any]],
            items: List[Dict[str, Any]],
    ) -> None:
        for index, item in enumerate(items or []):
            tiltSeriesId = item.get("tiltSeriesId") or item.get("id") or index
            label = item.get("label") or str(tiltSeriesId)

            self._addRelation(
                relationsByKey,
                tiltSeriesId,
                ctfSeriesId=tiltSeriesId,
                tiltSeriesId=tiltSeriesId,
                label=label,
            )

    def _addTomogramRelations(
            self,
            relationsByKey: Dict[str, Dict[str, Any]],
            items: List[Dict[str, Any]],
    ) -> None:
        for index, item in enumerate(items or []):
            tomogramId = (
                    item.get("tomoId")
                    or item.get("tomogramId")
                    or item.get("id")
                    or item.get("label")
                    or index
            )

            label = item.get("label") or item.get("name") or str(tomogramId)
            volumeId = item.get("tomogramVolumeId") or item.get("volumeId") or index

            self._addRelation(
                relationsByKey,
                tomogramId,
                tomogramId=tomogramId,
                tomogramVolumeId=volumeId,
                label=label,
            )

    def _addCoordinates3dRelations(
            self,
            relationsByKey: Dict[str, Dict[str, Any]],
            items: List[Dict[str, Any]],
    ) -> None:
        for index, item in enumerate(items or []):
            tomogramId = (
                    item.get("tomoId")
                    or item.get("tomogramId")
                    or item.get("id")
                    or item.get("label")
                    or index
            )

            label = item.get("label") or item.get("name") or str(tomogramId)
            volumeId = item.get("tomogramVolumeId") or item.get("volumeId") or index

            self._addRelation(
                relationsByKey,
                tomogramId,
                coordinatesTomogramId=tomogramId,
                tomogramId=tomogramId,
                tomogramVolumeId=volumeId,
                label=label,
            )

    def _mergeRootRelations(
            self,
            rootKind: str,
            storedSet: Dict[str, Any],
            relationsByKey: Dict[str, Dict[str, Any]],
            links: Dict[str, Optional[Dict[str, Any]]],
            summaries: Dict[str, Optional[Dict[str, Any]]],
    ) -> None:
        if rootKind == "tiltSeries":
            reader = PostgresqlTiltSeriesReader(
                db=self.db,
                projectId=self.projectId,
                protocolId=self.protocolId,
                outputName=self.outputName,
            )
            self._addTiltSeriesRelations(relationsByKey, reader.listTiltSeries())
            return

        if rootKind == "ctf":
            reader = PostgresqlCtftomoReader(
                db=self.db,
                projectId=self.projectId,
                protocolId=self.protocolId,
                outputName=self.outputName,
            )
            self._addCtftomoRelations(relationsByKey, reader.listCtftomoSeries())
            return

        if rootKind == "coordinates3d":
            reader = PostgresqlCoords3dReader(
                db=self.db,
                projectId=self.projectId,
                protocolId=self.protocolId,
                outputName=self.outputName,
            )
            tomograms = reader.listTomograms() or []
            self._addCoordinates3dRelations(relationsByKey, tomograms)

            if tomograms:
                links["tomogram"] = {
                    "protocolId": self.protocolId,
                    "outputName": self.outputName,
                    "itemId": None,
                    "label": "Tomograms",
                    "status": "derived",
                    "source": "coordinates3d",
                }
                summaries["tomogram"] = {
                    "objectClass": "SetOfTomograms",
                    "size": len(tomograms),
                    "source": "coordinates3d",
                }
            return

        if rootKind == "tomogram":
            items = self._buildTomogramItemsFromStoredSet(storedSet)
            self._addTomogramRelations(relationsByKey, items)

    def _buildTomogramItemsFromStoredSet(
            self,
            storedSet: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        items = []

        for index, item in enumerate(storedSet.get("items") or []):
            values = item.get("values") or {}

            tomogramId = self._firstValueByName(
                values,
                ["_tomoId", "tomoId", "tomogramId", "_tsId", "tsId"],
            )

            label = self._firstValueByName(
                values,
                ["_objLabel", "label", "_tsId", "tsId", "tomoId"],
            )

            publicId = tomogramId or item.get("scipionItemId") or index

            items.append(
                {
                    "id": publicId,
                    "tomoId": publicId,
                    "label": label or publicId,
                    "volumeId": index,
                }
            )

        return items

    def _listRelatedStoredSets(self) -> List[Dict[str, Any]]:
        try:
            rows = self.db.fetchAll(
                """
                WITH root_protocol AS (
                    SELECT id, "projectId", "protocolId", "protocolClassName"
                      FROM protocols
                     WHERE "projectId" = %s
                       AND (id = %s OR "protocolId" = %s)
                     LIMIT 1
                ),
                related_protocols AS (
                    SELECT
                        id,
                        "projectId",
                        "protocolId",
                        "protocolClassName",
                        'root' AS "relationRole",
                        0 AS distance
                      FROM root_protocol

                    UNION ALL

                    SELECT
                        parent.id,
                        parent."projectId",
                        parent."protocolId",
                        parent."protocolClassName",
                        'parent' AS "relationRole",
                        1 AS distance
                      FROM protocol_dependencies d
                      JOIN root_protocol root
                        ON root.id = d."childProtocolDbId"
                       AND root."projectId" = d."projectId"
                      JOIN protocols parent
                        ON parent.id = d."parentProtocolDbId"
                       AND parent."projectId" = d."projectId"

                    UNION ALL

                    SELECT
                        child.id,
                        child."projectId",
                        child."protocolId",
                        child."protocolClassName",
                        'child' AS "relationRole",
                        1 AS distance
                      FROM protocol_dependencies d
                      JOIN root_protocol root
                        ON root.id = d."parentProtocolDbId"
                       AND root."projectId" = d."projectId"
                      JOIN protocols child
                        ON child.id = d."childProtocolDbId"
                       AND child."projectId" = d."projectId"
                )
                SELECT DISTINCT ON (s.id)
                    s.id,
                    s."projectId",
                    s."protocolDbId",
                    s."objectId",
                    s."outputName",
                    s."setClassName",
                    s."itemClassName",
                    s.properties,
                    s."createdAt",
                    s."updatedAt",
                    rp."protocolId" AS "publicProtocolId",
                    rp."protocolClassName",
                    rp."relationRole",
                    rp.distance
                  FROM related_protocols rp
                  JOIN scipion_sets s
                    ON s."projectId" = rp."projectId"
                   AND s."protocolDbId" = rp.id
                 ORDER BY s.id, rp.distance ASC, rp."relationRole" ASC
                """,
                (
                    self.projectId,
                    int(self.protocolId),
                    str(self.protocolId),
                ),
            )
        except Exception:
            logger.debug(
                "Could not list related PostgreSQL stored sets for integrated context. "
                "projectId=%s protocolId=%s outputName=%s",
                self.projectId,
                self.protocolId,
                self.outputName,
                exc_info=True,
            )
            return []

        result = [dict(row) for row in rows or []]
        result.sort(
            key=lambda item: (
                int(item.get("distance") or 0),
                str(item.get("relationRole") or ""),
                int(item.get("protocolDbId") or 0),
                str(item.get("outputName") or ""),
            )
        )
        return result

    def _mergeRelatedStoredSets(
            self,
            rootStoredSet: Dict[str, Any],
            links: Dict[str, Optional[Dict[str, Any]]],
            summaries: Dict[str, Optional[Dict[str, Any]]],
            relationsByKey: Dict[str, Dict[str, Any]],
    ) -> None:
        for candidate in self._listRelatedStoredSets():
            if self._isSameStoredSet(candidate, rootStoredSet):
                continue

            candidateKind = self._getIntegratedKind(candidate)
            if candidateKind is None or candidateKind not in links:
                continue

            rootKind = self._getIntegratedKind(rootStoredSet)

            if rootKind == "coordinates3d" and candidateKind == "tomogram":
                continue

            if self._shouldReplaceLink(links.get(candidateKind)):
                links[candidateKind] = self._buildLink(
                    protocolId=self._getCandidateProtocolId(candidate),
                    outputName=candidate.get("outputName"),
                    storedSet=candidate,
                    statusValue="related",
                )
                summaries[candidateKind] = self._buildSummary(candidate)

            allowedRelationKeys = None
            rootKind = self._getIntegratedKind(rootStoredSet)

            if rootKind == "coordinates3d":
                allowedRelationKeys = set(relationsByKey.keys())

            self._mergeRelationsForCandidate(
                candidate=candidate,
                candidateKind=candidateKind,
                relationsByKey=relationsByKey,
                allowedRelationKeys=allowedRelationKeys,
            )

    def _filterIntegratedItemsByAllowedKeys(
            self,
            items: List[Dict[str, Any]],
            allowedRelationKeys: Optional[set],
    ) -> List[Dict[str, Any]]:
        if not allowedRelationKeys:
            return items or []

        filteredItems = []

        for item in items or []:
            candidates = [
                item.get("key"),
                item.get("label"),
                item.get("id"),
                item.get("tomoId"),
                item.get("tomogramId"),
                item.get("tiltSeriesId"),
                item.get("ctfSeriesId"),
                item.get("coordinatesTomogramId"),
            ]

            if any(str(value) in allowedRelationKeys for value in candidates if value is not None):
                filteredItems.append(item)

        return filteredItems

    def _mergeRelationsForCandidate(
            self,
            candidate: Dict[str, Any],
            candidateKind: str,
            relationsByKey: Dict[str, Dict[str, Any]],
            allowedRelationKeys: Optional[set] = None,
    ) -> None:
        protocolDbId = candidate.get("protocolDbId")
        outputName = candidate.get("outputName")

        if protocolDbId is None or not outputName:
            return

        if candidateKind == "tiltSeries":
            reader = PostgresqlTiltSeriesReader(
                db=self.db,
                projectId=self.projectId,
                protocolId=protocolDbId,
                outputName=outputName,
            )
            items = self._filterIntegratedItemsByAllowedKeys(
                reader.listTiltSeries(),
                allowedRelationKeys,
            )
            self._addTiltSeriesRelations(relationsByKey, items)
            self._addTiltSeriesRelations(relationsByKey, reader.listTiltSeries())
            return

        if candidateKind == "ctf":
            reader = PostgresqlCtftomoReader(
                db=self.db,
                projectId=self.projectId,
                protocolId=protocolDbId,
                outputName=outputName,
            )
            items = self._filterIntegratedItemsByAllowedKeys(
                reader.listCtftomoSeries(),
                allowedRelationKeys,
            )
            self._addCtftomoRelations(relationsByKey, items)
            return

        if candidateKind == "coordinates3d":
            reader = PostgresqlCoords3dReader(
                db=self.db,
                projectId=self.projectId,
                protocolId=protocolDbId,
                outputName=outputName,
            )
            items = self._filterIntegratedItemsByAllowedKeys(
                reader.listTomograms() or [],
                allowedRelationKeys,
            )
            self._addCoordinates3dRelations(relationsByKey, items)
            return

        if candidateKind == "tomogram":
            storedSet = self.setMapper.getStoredSet(
                projectId=self.projectId,
                protocolDbId=protocolDbId,
                outputName=outputName,
                limit=None,
                offset=0,
            )

            if storedSet is None:
                return

            items = self._filterIntegratedItemsByAllowedKeys(
                self._buildTomogramItemsFromStoredSet(storedSet),
                allowedRelationKeys,
            )
            self._addTomogramRelations(relationsByKey, items)

    def _isSameStoredSet(
            self,
            left: Dict[str, Any],
            right: Dict[str, Any],
    ) -> bool:
        return (
                str(left.get("protocolDbId")) == str(right.get("protocolDbId"))
                and str(left.get("outputName")) == str(right.get("outputName"))
        )

    def _shouldReplaceLink(
            self,
            existingLink: Optional[Dict[str, Any]],
    ) -> bool:
        if existingLink is None:
            return True

        protocolId = existingLink.get("protocolId")
        outputName = existingLink.get("outputName")
        statusValue = str(existingLink.get("status") or "")

        if protocolId is None and outputName is None:
            return True

        return statusValue == "inferred" and protocolId is None

    def _getCandidateProtocolId(self, candidate: Dict[str, Any]) -> Any:
        return candidate.get("publicProtocolId") or candidate.get("protocolDbId")

    def _safeValue(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): self._safeValue(item)
                for key, item in value.items()
            }

        if isinstance(value, (list, tuple, set)):
            return [
                self._safeValue(item)
                for item in value
            ]

        if isinstance(value, (datetime, date)):
            return value.isoformat()

        if hasattr(value, "item"):
            try:
                return value.item()
            except Exception:
                pass

        return value