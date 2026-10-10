import pytest
from typer.testing import CliRunner

from scipionapi_cli.cli import app


def test_PluginsCommandIsAvailable():
    result = CliRunner().invoke(app, ["plugins", "--help"])
    assert result.exit_code == 0, result.output
    assert "install" in result.output


def test_PluginsInstallSupportsNormalAndDevelModes():
    result = CliRunner().invoke(app, ["plugins", "install", "--help"])
    assert result.exit_code == 0, result.output
    assert "--devel" in result.output
    assert "--skip-binaries" in result.output


def test_PluginsDevelInstallOffersForce():
    result = CliRunner().invoke(app, ["plugins", "install", "--help"])
    assert result.exit_code == 0, result.output
    assert "--force" in result.output


def test_PluginsDevelInstallForwardsForce(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_devel_service

    calls = []

    class FakeDevelService:
        def installDevelPlugin(self, pluginPath, taskId=None, skipBinaries=False, force=False):
            calls.append({"path": pluginPath, "skipBinaries": skipBinaries, "force": force})
            return {"installed": "SUCCESS", "pipName": "scipion-em-example"}

    monkeypatch.setattr(plugin_devel_service, "PluginDevelService", FakeDevelService)
    result = CliRunner().invoke(app, ["plugins", "install", "--devel", str(tmp_path), "--force", "--skip-binaries"])

    assert result.exit_code == 0, result.output
    assert calls == [{"path": str(tmp_path.resolve()), "skipBinaries": True, "force": True}]

def test_PluginsNormalInstallLoadsConfiguredEnvironment(monkeypatch, tmp_path):
    import os
    from app.backend.api.services import plugin_service

    scipion_home = tmp_path / "scipion_home"
    scipion_home.mkdir()
    (scipion_home / ".env").write_text("SCIPIONAPI_PLUGIN_CLI_TEST_VALUE=from-configured-home\n", encoding="utf-8")
    monkeypatch.setenv("SCIPION_HOME", str(scipion_home))
    monkeypatch.delenv("SCIPIONAPI_PLUGIN_CLI_TEST_VALUE", raising=False)
    calls = []

    class FakePluginService:
        def installPlugin(self, pluginName, skipBinaries=False):
            calls.append((pluginName, skipBinaries, os.environ.get("SCIPIONAPI_PLUGIN_CLI_TEST_VALUE")))
            return {"installed": "SUCCESS"}

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    result = CliRunner().invoke(app, ["plugins", "install", "scipion-em-example", "--skip-binaries"])

    assert result.exit_code == 0, result.output
    assert calls == [("scipion-em-example", True, "from-configured-home")]


def test_PluginsDevelInstallLoadsConfiguredEnvironment(monkeypatch, tmp_path):
    import os
    from app.backend.api.services import plugin_devel_service

    scipion_home = tmp_path / "scipion_home"
    scipion_home.mkdir()
    (scipion_home / ".env").write_text("SCIPIONAPI_PLUGIN_CLI_TEST_VALUE=from-configured-home\n", encoding="utf-8")
    monkeypatch.setenv("SCIPION_HOME", str(scipion_home))
    monkeypatch.delenv("SCIPIONAPI_PLUGIN_CLI_TEST_VALUE", raising=False)
    calls = []

    class FakeDevelService:
        def installDevelPlugin(self, pluginPath, taskId=None, skipBinaries=False, force=False):
            calls.append((pluginPath, skipBinaries, os.environ.get("SCIPIONAPI_PLUGIN_CLI_TEST_VALUE")))
            return {"installed": "SUCCESS", "pipName": "scipion-em-example"}

    monkeypatch.setattr(plugin_devel_service, "PluginDevelService", FakeDevelService)
    result = CliRunner().invoke(app, ["plugins", "install", "--devel", str(tmp_path), "--skip-binaries"])

    assert result.exit_code == 0, result.output
    assert calls == [(str(tmp_path.resolve()), True, "from-configured-home")]

def test_PluginsNormalInstallNotifiesRunningServices(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []

    class FakePluginService:
        def installPlugin(self, pluginName, skipBinaries=False):
            calls.append(("install", pluginName, skipBinaries))
            return {"installed": "SUCCESS"}

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: calls.append("revision"))
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: calls.append("reload"))

    result = CliRunner().invoke(app, ["plugins", "install", "scipion-em-example", "--skip-binaries"])

    assert result.exit_code == 0, result.output
    assert calls == [("install", "scipion-em-example", True), "revision", "reload"]


def test_PluginsDevelInstallNotifiesRunningServices(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_devel_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []

    class FakeDevelService:
        def installDevelPlugin(self, pluginPath, taskId=None, skipBinaries=False, force=False):
            calls.append(("devel", pluginPath, skipBinaries, force))
            return {"installed": "SUCCESS", "pipName": "scipion-em-example"}

    monkeypatch.setattr(plugin_devel_service, "PluginDevelService", FakeDevelService)
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: calls.append("revision"))
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: calls.append("reload"))

    result = CliRunner().invoke(app, ["plugins", "install", "--devel", str(tmp_path), "--force"])

    assert result.exit_code == 0, result.output
    assert calls == [("devel", str(tmp_path.resolve()), False, True), "revision", "reload"]


def test_PluginsFailedInstallDoesNotNotifyRunningServices(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []

    class FakePluginService:
        def installPlugin(self, pluginName, skipBinaries=False):
            calls.append("install")
            raise RuntimeError("simulated installation failure")

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: calls.append("revision"))
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: calls.append("reload"))

    result = CliRunner().invoke(app, ["plugins", "install", "scipion-em-example"])

    assert result.exit_code != 0
    assert "simulated installation failure" in result.output
    assert calls == ["install"]

def test_PluginsDevelInstallFailureReturnsErrorWithoutNotification(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_devel_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []

    class FakeDevelService:
        def installDevelPlugin(self, pluginPath, taskId=None, skipBinaries=False, force=False):
            calls.append("install")
            raise RuntimeError("simulated devel installation failure")

    monkeypatch.setattr(plugin_devel_service, "PluginDevelService", FakeDevelService)
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: calls.append("revision"))
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: calls.append("reload"))

    result = CliRunner().invoke(app, ["plugins", "install", "--devel", str(tmp_path)])

    assert result.exit_code == 1
    assert "simulated devel installation failure" in result.output
    assert "Plugin installed" not in result.output
    assert calls == ["install"]


def test_PluginsUnexpectedInstallResultReturnsErrorWithoutNotification(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []

    class FakePluginService:
        def installPlugin(self, pluginName, skipBinaries=False):
            calls.append("install")
            return {"installed": "FAILURE"}

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: calls.append("revision"))
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: calls.append("reload"))

    result = CliRunner().invoke(app, ["plugins", "install", "scipion-em-example"])

    assert result.exit_code == 1
    assert "Unexpected installation result" in result.output
    assert "Plugin installed" not in result.output
    assert calls == ["install"]


def test_PluginsInstallRejectsConflictingModes(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_service, plugin_devel_service

    class UnexpectedService:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Service must not be created for conflicting CLI modes")

    monkeypatch.setattr(plugin_service, "PluginService", UnexpectedService)
    monkeypatch.setattr(plugin_devel_service, "PluginDevelService", UnexpectedService)

    result = CliRunner().invoke(app, ["plugins", "install", "scipion-em-example", "--devel", str(tmp_path)])

    assert result.exit_code != 0
    assert "exactly one" in result.output


def test_PluginsInstallRejectsForceOutsideDevel(monkeypatch):
    from app.backend.api.services import plugin_service

    class UnexpectedService:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Normal installation must not run with --force")

    monkeypatch.setattr(plugin_service, "PluginService", UnexpectedService)

    result = CliRunner().invoke(app, ["plugins", "install", "scipion-em-example", "--force"])

    assert result.exit_code != 0
    assert "--force is only supported with --devel" in result.output

@pytest.fixture(autouse=True)
def _stubPluginRuntimePreparation(monkeypatch):
    # Keep unit tests isolated from Scipion Vars.init(), domain loading and os.chdir().
    from app.backend.api.services import environment
    monkeypatch.setattr(environment, "prepareEnvironment", lambda: None)


def test_PluginsNormalInstallPreparesScipionRuntimeBeforeService(monkeypatch, tmp_path):
    from app.backend.api.services import environment, plugin_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []
    monkeypatch.setattr(environment, "prepareEnvironment", lambda: calls.append("prepare"))
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: None)
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: None)

    class FakePluginService:
        def __init__(self):
            calls.append("create_service")

        def installPlugin(self, pluginName, skipBinaries=False):
            calls.append(("install", pluginName, skipBinaries))
            return {"installed": "SUCCESS"}

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    result = CliRunner().invoke(app, ["plugins", "install", "scipion-em-example"])

    assert result.exit_code == 0, result.output
    assert calls == ["prepare", "create_service", ("install", "scipion-em-example", False)]


def test_PluginsNormalInstallStopsWhenRuntimePreparationFails(monkeypatch, tmp_path):
    from app.backend.api.services import environment, plugin_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []

    def failingPrepare():
        calls.append("prepare")
        raise RuntimeError("simulated Scipion runtime preparation failure")

    class UnexpectedService:
        def __init__(self):
            calls.append("create_service")
            raise AssertionError("Plugin service must not run when preparation fails")

    monkeypatch.setattr(environment, "prepareEnvironment", failingPrepare)
    monkeypatch.setattr(plugin_service, "PluginService", UnexpectedService)
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: calls.append("revision"))
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: calls.append("reload"))

    result = CliRunner().invoke(app, ["plugins", "install", "scipion-em-example"])

    assert result.exit_code == 1
    assert "simulated Scipion runtime preparation failure" in result.output
    assert calls == ["prepare"]


def _fakePluginsForCliListing():
    return [
        {"pipName": "scipion-em-appion", "installed": True, "pipVersion": "3.1.0", "installMode": "standard", "devel": False},
        {"pipName": "scipion-em-motioncorr", "installed": True, "pipVersion": "4.0.1", "installMode": "devel", "devel": True},
        {"pipName": "scipion-em-example", "installed": False, "pipVersion": "", "latestRelease": "1.5.0", "installMode": "standard", "devel": False},
    ]


def test_PluginsListShowsInstalledVersionsAndModes(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_service

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []

    class FakePluginService:
        def getPlugins(self):
            calls.append("list")
            return _fakePluginsForCliListing()

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    result = CliRunner().invoke(app, ["plugins", "list"])

    assert result.exit_code == 0, result.output
    assert calls == ["list"]
    assert "scipion-em-appion" in result.output
    assert "scipion-em-motioncorr" in result.output
    assert "3.1.0" in result.output
    assert "4.0.1" in result.output
    assert "standard" in result.output
    assert "devel" in result.output
    assert "scipion-em-example" not in result.output


def test_PluginsListAllIncludesAvailablePlugins(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_service

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))

    class FakePluginService:
        def getPlugins(self):
            return _fakePluginsForCliListing()

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    result = CliRunner().invoke(app, ["plugins", "list", "--all"])

    assert result.exit_code == 0, result.output
    assert "scipion-em-example" in result.output
    assert "scipion-em-appion" in result.output
    assert "scipion-em-motioncorr" in result.output


def test_PluginsListDevelFiltersNonDevelPlugins(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_service

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))

    class FakePluginService:
        def getPlugins(self):
            return _fakePluginsForCliListing()

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    result = CliRunner().invoke(app, ["plugins", "list", "--devel"])

    assert result.exit_code == 0, result.output
    assert "scipion-em-motioncorr" in result.output
    assert "scipion-em-appion" not in result.output
    assert "scipion-em-example" not in result.output


def test_PluginsBinariesListShowsTargetsAndInstallStatus(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_service

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []

    class FakePluginService:
        def getPlugin(self, pluginName):
            calls.append(pluginName)
            return {
                "pipName": "scipion-em-appion",
                "installed": True,
                "binaries": [
                    {"name": "dogpicker", "version": "0.2.1.1", "target": "dogpicker-0.2.1.1", "installed": True, "default": True},
                    {"name": "dogpicker", "version": "0.3.0", "target": "dogpicker-0.3.0", "installed": False, "default": False},
                ],
            }

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    result = CliRunner().invoke(app, ["plugins", "binaries", "list", "scipion-em-appion"])

    assert result.exit_code == 0, result.output
    assert calls == ["scipion-em-appion"]
    assert "dogpicker-0.2.1.1" in result.output
    assert "dogpicker-0.3.0" in result.output
    assert "installed" in result.output.lower()
    assert "not installed" in result.output.lower()
    assert "default" in result.output.lower()


def test_PluginsBinariesListRejectsUnknownPlugin(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_service

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))

    class FakePluginService:
        def getPlugin(self, pluginName):
            return None

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    result = CliRunner().invoke(app, ["plugins", "binaries", "list", "scipion-em-unknown"])

    assert result.exit_code != 0
    assert "scipion-em-unknown" in result.output
    assert "not found" in result.output.lower()


def test_PluginsBinariesListHandlesPluginWithoutBinaries(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_service

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))

    class FakePluginService:
        def getPlugin(self, pluginName):
            return {"pipName": pluginName, "installed": True, "binaries": []}

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    result = CliRunner().invoke(app, ["plugins", "binaries", "list", "scipion-em-empty"])

    assert result.exit_code == 0, result.output
    assert "scipion-em-empty" in result.output
    assert "no binaries" in result.output.lower()


def test_PluginsBinariesInstallCallsServiceAndNotifiesBackend(monkeypatch, tmp_path):
    from app.backend.api.services import environment, plugin_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []
    monkeypatch.setattr(environment, "prepareEnvironment", lambda: calls.append("prepare"))
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: calls.append("revision"))
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: calls.append("reload"))

    class FakePluginService:
        def __init__(self):
            calls.append("service")

        def installPluginBinary(self, pluginName, binaryTarget, taskId=None):
            calls.append(("install", pluginName, binaryTarget))
            return {"installed": "SUCCESS", "binaryTarget": binaryTarget, "alreadyInstalled": False}

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    result = CliRunner().invoke(app, ["plugins", "binaries", "install", "scipion-em-appion", "dogpicker-0.2.1.1"])

    assert result.exit_code == 0, result.output
    assert "dogpicker-0.2.1.1" in result.output
    assert calls == ["prepare", "service", ("install", "scipion-em-appion", "dogpicker-0.2.1.1"), "revision", "reload"]


def test_PluginsBinariesInstallHandlesAlreadyInstalledTarget(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    notifications = []
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: notifications.append("revision"))
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: notifications.append("reload"))

    class FakePluginService:
        def installPluginBinary(self, pluginName, binaryTarget, taskId=None):
            return {"installed": "SUCCESS", "binaryTarget": binaryTarget, "alreadyInstalled": True}

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    result = CliRunner().invoke(app, ["plugins", "binaries", "install", "scipion-em-appion", "dogpicker-0.2.1.1"])

    assert result.exit_code == 0, result.output
    assert "already installed" in result.output.lower()
    assert notifications == ["revision", "reload"]


def test_PluginsBinariesInstallFailureDoesNotNotifyBackend(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: calls.append("revision"))
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: calls.append("reload"))

    class FakePluginService:
        def installPluginBinary(self, pluginName, binaryTarget, taskId=None):
            calls.append("install")
            raise RuntimeError("simulated binary install failure")

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    result = CliRunner().invoke(app, ["plugins", "binaries", "install", "scipion-em-appion", "dogpicker-0.2.1.1"])

    assert result.exit_code == 1
    assert "simulated binary install failure" in result.output
    assert calls == ["install"]


def test_PluginsBinariesInstallRejectsUnexpectedServiceResult(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: calls.append("revision"))
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: calls.append("reload"))

    class FakePluginService:
        def installPluginBinary(self, pluginName, binaryTarget, taskId=None):
            calls.append("install")
            return {"installed": "FAILURE", "binaryTarget": binaryTarget}

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    result = CliRunner().invoke(app, ["plugins", "binaries", "install", "scipion-em-appion", "dogpicker-0.2.1.1"])

    assert result.exit_code == 1
    assert "Unexpected" in result.output
    assert calls == ["install"]


def test_PluginsBinariesUninstallCallsServiceAndNotifiesBackend(monkeypatch, tmp_path):
    from app.backend.api.services import environment, plugin_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []
    monkeypatch.setattr(environment, "prepareEnvironment", lambda: calls.append("prepare"))
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: calls.append("revision"))
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: calls.append("reload"))

    class FakePluginService:
        def __init__(self):
            calls.append("service")

        def uninstallPluginBinary(self, pluginName, binaryTarget, taskId=None):
            calls.append(("uninstall", pluginName, binaryTarget))
            return {"uninstalled": "SUCCESS", "binaryTarget": binaryTarget, "alreadyUninstalled": False}

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    result = CliRunner().invoke(app, ["plugins", "binaries", "uninstall", "scipion-em-appion", "dogpicker-0.2.1.1"])

    assert result.exit_code == 0, result.output
    assert "dogpicker-0.2.1.1" in result.output
    assert calls == ["prepare", "service", ("uninstall", "scipion-em-appion", "dogpicker-0.2.1.1"), "revision", "reload"]


def test_PluginsBinariesUninstallHandlesAlreadyUninstalledTarget(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    notifications = []
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: notifications.append("revision"))
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: notifications.append("reload"))

    class FakePluginService:
        def uninstallPluginBinary(self, pluginName, binaryTarget, taskId=None):
            return {"uninstalled": "SUCCESS", "binaryTarget": binaryTarget, "alreadyUninstalled": True}

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    result = CliRunner().invoke(app, ["plugins", "binaries", "uninstall", "scipion-em-appion", "dogpicker-0.2.1.1"])

    assert result.exit_code == 0, result.output
    assert "already uninstalled" in result.output.lower() or "not installed" in result.output.lower()
    assert notifications == ["revision", "reload"]


def test_PluginsBinariesUninstallFailureDoesNotNotifyBackend(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: calls.append("revision"))
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: calls.append("reload"))

    class FakePluginService:
        def uninstallPluginBinary(self, pluginName, binaryTarget, taskId=None):
            calls.append("uninstall")
            raise RuntimeError("simulated binary uninstall failure")

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    result = CliRunner().invoke(app, ["plugins", "binaries", "uninstall", "scipion-em-appion", "dogpicker-0.2.1.1"])

    assert result.exit_code == 1
    assert "simulated binary uninstall failure" in result.output
    assert "Binary uninstalled:" not in result.output
    assert calls == ["uninstall"]


def test_PluginsBinariesUninstallRejectsUnexpectedServiceResult(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: calls.append("revision"))
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: calls.append("reload"))

    class FakePluginService:
        def uninstallPluginBinary(self, pluginName, binaryTarget, taskId=None):
            calls.append("uninstall")
            return {"uninstalled": "FAILURE", "binaryTarget": binaryTarget}

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    result = CliRunner().invoke(app, ["plugins", "binaries", "uninstall", "scipion-em-appion", "dogpicker-0.2.1.1"])

    assert result.exit_code == 1
    assert "Unexpected" in result.output
    assert "Binary uninstalled:" not in result.output
    assert calls == ["uninstall"]


def test_PluginsUninstallCallsServiceAndNotifiesBackend(monkeypatch, tmp_path):
    from app.backend.api.services import environment, plugin_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []
    monkeypatch.setattr(environment, "prepareEnvironment", lambda: calls.append("prepare"))
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: calls.append("revision"))
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: calls.append("reload"))

    class FakePluginService:
        def __init__(self):
            calls.append("create_service")

        def uninstallPlugin(self, pluginName, taskId=None, refreshDomain=True):
            calls.append(("uninstall", pluginName, refreshDomain))
            return {"uninstalled": "SUCCESS"}

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    result = CliRunner().invoke(app, ["plugins", "uninstall", "scipion-em-appion"])

    assert result.exit_code == 0, result.output
    assert "scipion-em-appion" in result.output
    assert "uninstalled" in result.output.lower()
    assert calls == ["prepare", "create_service", ("uninstall", "scipion-em-appion", False), "revision", "reload"]


def test_PluginsUninstallUsesServiceForDevelPlugin(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_service, plugin_devel_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []

    class FakePluginService:
        def uninstallPlugin(self, pluginName, taskId=None, refreshDomain=True):
            calls.append((pluginName, refreshDomain))
            return {"uninstalled": "SUCCESS"}

    class UnexpectedDevelService:
        def __init__(self):
            raise AssertionError("The CLI must let PluginService clean up the devel manifest")

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    monkeypatch.setattr(plugin_devel_service, "PluginDevelService", UnexpectedDevelService)
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: None)
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: None)
    result = CliRunner().invoke(app, ["plugins", "uninstall", "scipion-em-motioncorr"])

    assert result.exit_code == 0, result.output
    assert "scipion-em-motioncorr" in result.output
    assert calls == [("scipion-em-motioncorr", False)]


def test_PluginsUninstallFailureDoesNotNotifyBackend(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: calls.append("revision"))
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: calls.append("reload"))

    class FakePluginService:
        def uninstallPlugin(self, pluginName, taskId=None, refreshDomain=True):
            calls.append("uninstall")
            raise RuntimeError("simulated plugin uninstall failure")

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    result = CliRunner().invoke(app, ["plugins", "uninstall", "scipion-em-appion"])

    assert result.exit_code == 1
    assert "simulated plugin uninstall failure" in result.output
    assert "Plugin uninstalled:" not in result.output
    assert calls == ["uninstall"]


def test_PluginsUninstallRejectsUnexpectedServiceResult(monkeypatch, tmp_path):
    from app.backend.api.services import plugin_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: calls.append("revision"))
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: calls.append("reload"))

    class FakePluginService:
        def uninstallPlugin(self, pluginName, taskId=None, refreshDomain=True):
            calls.append("uninstall")
            return {"uninstalled": "FAILURE"}

    monkeypatch.setattr(plugin_service, "PluginService", FakePluginService)
    result = CliRunner().invoke(app, ["plugins", "uninstall", "scipion-em-appion"])

    assert result.exit_code == 1
    assert "Unexpected" in result.output
    assert "Plugin uninstalled:" not in result.output
    assert calls == ["uninstall"]


def test_PluginsUninstallStopsIfRuntimePreparationFails(monkeypatch, tmp_path):
    from app.backend.api.services import environment, plugin_service, plugins_revision, reload_trigger

    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    calls = []

    def failing_prepare():
        calls.append("prepare")
        raise RuntimeError("simulated plugin uninstall runtime failure")

    class UnexpectedPluginService:
        def __init__(self):
            calls.append("create_service")
            raise AssertionError("Service must not run if Scipion runtime preparation fails")

    monkeypatch.setattr(environment, "prepareEnvironment", failing_prepare)
    monkeypatch.setattr(plugin_service, "PluginService", UnexpectedPluginService)
    monkeypatch.setattr(plugins_revision, "bumpPluginsRevision", lambda: calls.append("revision"))
    monkeypatch.setattr(reload_trigger, "triggerBackendReloadIfEnabled", lambda: calls.append("reload"))

    result = CliRunner().invoke(app, ["plugins", "uninstall", "scipion-em-appion"])

    assert result.exit_code == 1
    assert "simulated plugin uninstall runtime failure" in result.output
    assert calls == ["prepare"]
