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
