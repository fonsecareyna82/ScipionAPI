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
import app.backend.api.services.protocol_catalog_service as protocolCatalogModule

from app.backend.api.services.protocol_catalog_service import ProtocolCatalogService


class ProtocolClassStub:
    @classmethod
    def getClassLabel(cls):
        return "Import movies"


def test_ProtocolCatalogResolvesDefaultLabelsFromStableDomainSnapshot(monkeypatch):
    rawTree = {
        "childs": [
            {
                "text": "default",
                "tag": "protocol",
                "value": "pwem.protocols.ProtImportMovies",
                "childs": [],
            }
        ]
    }

    monkeypatch.setattr(protocolCatalogModule, "_protocolsTreeCache", {})
    monkeypatch.setattr(protocolCatalogModule, "_invalidateProtocolsTreeCacheIfNeeded", lambda: 1)
    monkeypatch.setattr(protocolCatalogModule, "getScipionProtocolsSnapshot", lambda: {"ProtImportMovies": ProtocolClassStub})

    service = ProtocolCatalogService()
    monkeypatch.setattr(service, "_buildProtocolsTreeInSubprocess", lambda: rawTree)

    result = service.getProtocols(currentProject=object())

    assert result["childs"][0]["text"] == "Import movies"
    assert rawTree["childs"][0]["text"] == "default"