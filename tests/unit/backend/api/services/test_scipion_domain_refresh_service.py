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
import threading
import app.backend.api.services.scipion_domain_refresh_service as domainRefreshModule


class DomainStub:
    _plugins = {
        "oldPlugin": object(),
    }

    _protocols = {
        "OldProtocol": object(),
    }

    _objects = {
        "OldObject": object(),
    }

    _viewers = {
        "OldViewer": object(),
    }

    _wizards = {
        "OldWizard": object(),
    }

    _pluginsLoaded = True

    _preferred_viewers = {
        "Volume": [
            "OldViewer",
        ],
    }

    _Domain__mapperDict = {
        "OldProtocol": object(),
    }

    _capabilityProviders = {
        "oldProvider": object(),
    }

    _capabilityProvidersLoaded = True

    getPluginsCalls = 0
    getProtocolsCalls = 0
    newProtocol = object()

    @classmethod
    def getPlugins(cls):
        cls.getPluginsCalls += 1

        cls._plugins = {
            "newPlugin": object(),
        }

        cls._pluginsLoaded = True

        return dict(
            cls._plugins
        )

    @classmethod
    def getProtocols(cls):
        cls.getProtocolsCalls += 1
        cls._protocols = {"NewProtocol": cls.newProtocol}
        return dict(cls._protocols)


def test_RefreshScipionDomainClearsCachedRegistries(monkeypatch):
    setDomainCalls = []
    invalidateCalls = []

    monkeypatch.setattr(
        domainRefreshModule,
        "_lastDomainRevision",
        3,
    )

    monkeypatch.setattr(
        domainRefreshModule,
        "getPluginsRevision",
        lambda: 4,
    )

    monkeypatch.setattr(
        domainRefreshModule.importlib,
        "invalidate_caches",
        lambda: invalidateCalls.append(True),
    )

    monkeypatch.setattr(
        domainRefreshModule.Config,
        "setDomain",
        lambda value: setDomainCalls.append(value),
    )

    monkeypatch.setattr(
        domainRefreshModule.Config,
        "getDomain",
        lambda: DomainStub,
    )

    refreshed = domainRefreshModule.refreshScipionDomain()

    assert refreshed is True
    assert setDomainCalls == [
        "pwem",
    ]
    assert invalidateCalls == [
        True,
    ]

    assert DomainStub._pluginsLoaded is True
    assert list(DomainStub._plugins) == [
        "newPlugin",
    ]

    assert DomainStub._protocols == {"NewProtocol": DomainStub.newProtocol}
    assert DomainStub._objects == {}
    assert DomainStub._viewers == {}
    assert DomainStub._wizards == {}
    assert DomainStub._preferred_viewers is None
    assert DomainStub._Domain__mapperDict is None
    # Regression: a newly (un)installed plugin's CapabilityProvider (e.g.
    # cryoSPARC's ProtImportParticles import provider) must stop showing
    # stale after a plugin-revision-triggered refresh, same as every
    # other Domain registry above -- this cache was originally missing
    # from _resetScipionDomainCaches entirely.
    assert DomainStub._capabilityProviders == {}
    assert DomainStub._capabilityProvidersLoaded is False
    assert DomainStub.getPluginsCalls == 1
    assert DomainStub.getProtocolsCalls == 1


def test_GetScipionProtocolsSnapshotWaitsForConcurrentRefresh(monkeypatch):
    resetStarted = threading.Event()
    allowRefresh = threading.Event()
    snapshotFinished = threading.Event()
    newProtocol = object()
    refreshErrors = []
    snapshot = {}

    class ConcurrentDomainStub:
        _plugins = {"oldPlugin": object()}
        _protocols = {"OldProtocol": object()}
        _objects = {}
        _viewers = {}
        _wizards = {}
        _pluginsLoaded = True
        _preferred_viewers = None
        _Domain__mapperDict = None

        @classmethod
        def getPlugins(cls):
            cls._plugins = {"newPlugin": object()}
            cls._pluginsLoaded = True
            return dict(cls._plugins)

        @classmethod
        def getProtocols(cls):
            if not cls._protocols:
                cls._protocols = {"NewProtocol": newProtocol}
            return dict(cls._protocols)

    originalReset = domainRefreshModule._resetScipionDomainCaches

    def pausedReset(domain):
        originalReset(domain)
        resetStarted.set()
        assert allowRefresh.wait(timeout=2)

    def runRefresh():
        try:
            domainRefreshModule.refreshScipionDomain()
        except Exception as exc:
            refreshErrors.append(exc)

    def readSnapshot():
        snapshot.update(domainRefreshModule.getScipionProtocolsSnapshot())
        snapshotFinished.set()

    monkeypatch.setattr(domainRefreshModule, "_lastDomainRevision", 3)
    monkeypatch.setattr(domainRefreshModule, "getPluginsRevision", lambda: 4)
    monkeypatch.setattr(domainRefreshModule.importlib, "invalidate_caches", lambda: None)
    monkeypatch.setattr(domainRefreshModule.Config, "setDomain", lambda value: None)
    monkeypatch.setattr(domainRefreshModule.Config, "getDomain", lambda: ConcurrentDomainStub)
    monkeypatch.setattr(domainRefreshModule, "_resetScipionDomainCaches", pausedReset)

    refreshThread = threading.Thread(target=runRefresh)
    refreshThread.start()

    assert resetStarted.wait(timeout=2)

    snapshotThread = threading.Thread(target=readSnapshot)
    snapshotThread.start()

    assert snapshotFinished.wait(timeout=0.05) is False

    allowRefresh.set()
    refreshThread.join(timeout=2)
    snapshotThread.join(timeout=2)

    assert refreshErrors == []
    assert snapshotFinished.is_set()
    assert snapshot == {"NewProtocol": newProtocol}


def test_RefreshScipionDomainSkipsUnchangedRevision(monkeypatch):
    monkeypatch.setattr(
        domainRefreshModule,
        "_lastDomainRevision",
        4,
    )

    monkeypatch.setattr(
        domainRefreshModule,
        "getPluginsRevision",
        lambda: 4,
    )

    monkeypatch.setattr(
        domainRefreshModule.Config,
        "getDomain",
        lambda: (_ for _ in ()).throw(
            AssertionError(
                "Domain must not reload when plugin revision has not changed"
            )
        ),
    )

    assert domainRefreshModule.refreshScipionDomain() is False