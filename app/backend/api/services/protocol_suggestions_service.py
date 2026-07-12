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
import json
import logging
from typing import Any, Callable, Dict, List, Tuple
from urllib.request import urlopen

from pyworkflow.config import Config


logger = logging.getLogger(__name__)


class ProtocolSuggestionsService:
    """Load and enrich next-protocol suggestions."""

    def getNextProtocolSuggestions(
            self,
            *,
            mapper,
            projectId: int,
            protocolId: int,
            currentProject,
            getScipionProtocolForRuntimeCallback: Callable,
    ) -> List[Dict[str, Any]]:
        protocol = getScipionProtocolForRuntimeCallback(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        protocolClassName = protocol.getClassName()

        try:
            url = (
                Config.SCIPION_STATS_SUGGESTION
                % protocolClassName
            )

            rawSuggestions = json.loads(
                urlopen(url)
                .read()
                .decode("utf-8")
            )

            rankedSuggestions = [
                self._buildSuggestion(
                    currentProject=currentProject,
                    rawSuggestion=rawSuggestion,
                )
                for rawSuggestion in rawSuggestions
            ]

            rankedSuggestions.sort(
                key=lambda item: item[0],
                reverse=True,
            )

            return [
                suggestion
                for _, suggestion in rankedSuggestions
            ]

        except Exception:
            logger.exception(
                "Suggestions system not available"
            )
            return []

    def _buildSuggestion(
            self,
            *,
            currentProject,
            rawSuggestion,
    ) -> Tuple[int, Dict[str, Any]]:
        (
            nextProtocolName,
            count,
            name,
            package,
            description,
        ) = rawSuggestion

        if package is None and name is not None:
            package = "scipion-em-%s" % (
                name.split("-")[0].strip()
            )

        installed = (
            "Missing. Available in %s plugin."
            % package
        )

        protocolClass = (
            Config
            .getDomain()
            .getProtocols()
            .get(nextProtocolName, None)
        )

        if protocolClass is not None:
            name = protocolClass.getClassLabel().lower()
            description = (
                protocolClass.getHelpText()
                + "\n\n"
            )

            protocol = currentProject.newProtocol(
                protocolClass
            )

            references = protocol.citations()

            if references != ["No references provided"]:
                for reference in references:
                    description += reference + "\n"

            if protocolClass.isInstalled():
                installed = "installed"

        suggestion = {
            "protocolName": name,
            "protocolClass": nextProtocolName,
            "help": description,
            "installed": installed,
        }

        return int(count), suggestion