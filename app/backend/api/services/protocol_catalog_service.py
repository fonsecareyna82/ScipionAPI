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
# * All comments concerning this program package may be sent to the
# * e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
import copy
import logging
import threading
from typing import Any, Dict

from pyworkflow.config import Config

from app.backend.api.services.plugins_revision import getPluginsRevision
from app.backend.api.services.json_subprocess_runner import JsonSubprocessRunner


logger = logging.getLogger(__name__)

_protocolsTreeLock = threading.Lock()
_protocolsTreeCache: Dict[str, Dict[str, Any]] = {}
_lastProtocolsTreeRevision = -1


def _invalidateProtocolsTreeCacheIfNeeded() -> int:
    global _lastProtocolsTreeRevision

    revision = int(getPluginsRevision() or 0)

    with _protocolsTreeLock:
        if revision != _lastProtocolsTreeRevision:
            _protocolsTreeCache.clear()
            _lastProtocolsTreeRevision = revision

    return revision


class ProtocolCatalogService:
    """Build and cache the available Scipion protocols catalog."""

    def getProtocols(
            self,
            *,
            currentProject,
    ) -> dict:
        _invalidateProtocolsTreeCacheIfNeeded()

        cacheKey = "protocolsTree"

        with _protocolsTreeLock:
            cached = _protocolsTreeCache.get(cacheKey)

            if cached is not None:
                protocolsTree = copy.deepcopy(cached)
                self._walkAndReplaceProtocols(
                    protocolsTree,
                    currentProject,
                )
                return protocolsTree

        protocolsTree = self._buildProtocolsTreeInSubprocess()

        with _protocolsTreeLock:
            _protocolsTreeCache[cacheKey] = protocolsTree

        protocolsTree = copy.deepcopy(protocolsTree)

        self._walkAndReplaceProtocols(
            protocolsTree,
            currentProject,
        )

        return protocolsTree

    def _buildProtocolsTreeInSubprocess(
            self,
    ) -> Dict[str, Any]:
        code = """
    import contextlib
    import os
    import sys

    with contextlib.redirect_stdout(sys.stderr):
        from pyworkflow import Config
        from pyworkflow.gui.project.viewprotocols_extra import ProtocolTreeConfig
        from app.utils.scipion_helper import serializeToJson

        Config.setDomain("pwem")
        domain = Config.getDomain()

        protConf = os.path.join(
            Config.SCIPION_LOCAL_CONFIG,
            Config.SCIPION_PROTOCOLS,
        )

        tree = ProtocolTreeConfig.load(
            domain,
            protConf,
        )

        _scipionPayload = serializeToJson(tree)
    """

        jsonSubprocessRunner = JsonSubprocessRunner()

        return jsonSubprocessRunner.run(
            code=code,
            operationName="Build protocols tree",
        )

    def _walkAndReplaceProtocols(
            self,
            data,
            currentProject,
    ) -> None:
        if isinstance(data, dict):
            for value in data.values():
                if isinstance(value, dict):
                    self._replaceDefaultProtocolText(
                        value,
                        currentProject,
                    )

                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            self._replaceDefaultProtocolText(
                                item,
                                currentProject,
                            )

        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    self._replaceDefaultProtocolText(
                        item,
                        currentProject,
                    )

    def _replaceDefaultProtocolText(
            self,
            node: dict,
            currentProject,
    ) -> None:
        if isinstance(node, dict):
            text = node.get("text")
            tag = node.get("tag")
            children = node.get("childs", [])

        else:
            text = getattr(node, "text", None)
            tag = getattr(node, "tag", None)
            children = getattr(node, "childs", [])

        if text == "default" and tag == "protocol":
            newText = self._getProtocolName(
                node,
                currentProject,
            )

            if newText:
                if isinstance(node, dict):
                    node["text"] = newText
                else:
                    setattr(node, "text", newText)

        for child in children:
            self._replaceDefaultProtocolText(
                child,
                currentProject,
            )

    def _getProtocolName(
            self,
            node,
            currentProject,
    ):
        text = node.get("text")

        if text:
            value = node.get("value") if node.get("value") is not None else text
            protocolClassName = value.split(".")[-1]

            protocolClass = self._getProtocolClassForTreeLabel(
                currentProject,
                protocolClassName,
            )

            if node.get("tag") == "protocol" and text == "default":
                if protocolClass is None:
                    logger.warning(
                        "Protocol className '%s' not found!!!.\n"
                        "Fix your config/protocols.conf configuration.",
                        protocolClassName,
                    )
                    return

                return protocolClass.getClassLabel()

        return "default"

    def _getProtocolClassForTreeLabel(
            self,
            currentProject,
            protocolClassName: str,
    ):
        try:
            if currentProject is not None:
                protocolClass = (
                    currentProject
                    .getDomain()
                    .getProtocols()
                    .get(protocolClassName, None)
                )

                if protocolClass is not None:
                    return protocolClass

        except Exception:
            pass

        try:
            return (
                Config
                .getDomain()
                .getProtocols()
                .get(protocolClassName, None)
            )

        except Exception:
            logger.warning(
                "Protocol className '%s' not found while resolving "
                "protocol tree label.",
                protocolClassName,
            )

            return None