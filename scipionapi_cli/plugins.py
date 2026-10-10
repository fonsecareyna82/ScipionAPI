"""Plugin installation commands for the ScipionAPI CLI."""
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(no_args_is_help=True, help="Manage Scipion plugins.")

binaries_app = typer.Typer(no_args_is_help=True, help="Manage individual plugin binaries.")
app.add_typer(binaries_app, name="binaries")


@binaries_app.command("install", help="Install a specific binary target for an installed plugin.")
def install_binary(plugin_name: str = typer.Argument(..., help="Plugin pip name."), binary_target: str = typer.Argument(..., help="Exact binary target from `plugins binaries list`.")) -> None:
    try:
        from app.backend.bootstrap import bootstrapEnv
        bootstrapEnv()
        from app.backend.api.services.environment import prepareEnvironment
        prepareEnvironment()
        from app.backend.api.services.plugin_service import PluginService
        result = PluginService().installPluginBinary(plugin_name, binary_target)
        if result.get("installed") != "SUCCESS":
            typer.echo(f"Unexpected binary installation result: {result!r}", err=True)
            raise typer.Exit(code=1)

        from app.backend.api.services.plugins_revision import bumpPluginsRevision
        from app.backend.api.services.reload_trigger import triggerBackendReloadIfEnabled
        bumpPluginsRevision()
        triggerBackendReloadIfEnabled()
        target = result.get("binaryTarget") or binary_target
        if result.get("alreadyInstalled"):
            typer.echo(f"Binary already installed: {target} ({plugin_name})")
        else:
            typer.echo(f"Binary installed: {target} ({plugin_name})")
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"Binary installation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@binaries_app.command("uninstall", help="Uninstall a specific binary target of an installed plugin.")
def uninstall_binary(plugin_name: str = typer.Argument(..., help="Plugin pip name."), binary_target: str = typer.Argument(..., help="Exact binary target from `plugins binaries list`.")) -> None:
    try:
        from app.backend.bootstrap import bootstrapEnv
        bootstrapEnv()
        from app.backend.api.services.environment import prepareEnvironment
        prepareEnvironment()
        from app.backend.api.services.plugin_service import PluginService
        result = PluginService().uninstallPluginBinary(plugin_name, binary_target)
        if result.get("uninstalled") != "SUCCESS":
            typer.echo(f"Unexpected binary uninstallation result: {result!r}", err=True)
            raise typer.Exit(code=1)

        from app.backend.api.services.plugins_revision import bumpPluginsRevision
        from app.backend.api.services.reload_trigger import triggerBackendReloadIfEnabled
        bumpPluginsRevision()
        triggerBackendReloadIfEnabled()
        target = result.get("binaryTarget") or binary_target
        if result.get("alreadyUninstalled"):
            typer.echo(f"Binary already uninstalled: {target} ({plugin_name})")
        else:
            typer.echo(f"Binary uninstalled: {target} ({plugin_name})")
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"Binary uninstallation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("uninstall", help="Uninstall a Scipion plugin, including binaries and devel registration when applicable.")
def uninstall_plugin(plugin_name: str = typer.Argument(..., help="Plugin pip name to uninstall.")) -> None:
    try:
        from app.backend.bootstrap import bootstrapEnv
        bootstrapEnv()
        from app.backend.api.services.environment import prepareEnvironment
        prepareEnvironment()
        from app.backend.api.services.plugin_service import PluginService
        result = PluginService().uninstallPlugin(plugin_name, refreshDomain=False)
        if result.get("uninstalled") != "SUCCESS":
            typer.echo(f"Unexpected plugin uninstallation result: {result!r}", err=True)
            raise typer.Exit(code=1)

        from app.backend.api.services.plugins_revision import bumpPluginsRevision
        from app.backend.api.services.reload_trigger import triggerBackendReloadIfEnabled
        bumpPluginsRevision()
        triggerBackendReloadIfEnabled()
        typer.echo(f"Plugin uninstalled: {plugin_name}")
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"Plugin uninstallation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("list", help="List installed plugins, or include available plugins with --all.")
def list_plugins(show_all: bool = typer.Option(False, "--all", help="Include plugins available but not installed."), devel_only: bool = typer.Option(False, "--devel", help="Show only editable/devel plugins.")) -> None:
    try:
        from app.backend.bootstrap import bootstrapEnv
        bootstrapEnv()
        from app.backend.api.services.environment import prepareEnvironment
        prepareEnvironment()
        from app.backend.api.services.plugin_service import PluginService
        catalog = PluginService().getPlugins()

        plugins = [plugin for plugin in catalog if (show_all or plugin.get("installed")) and (not devel_only or plugin.get("devel") or plugin.get("installMode") == "devel")]
        if not plugins:
            typer.echo("No matching plugins found.")
            return

        headers = ("PLUGIN", "VERSION", "MODE", "STATUS")
        rows = []
        for plugin in sorted(plugins, key=lambda item: str(item.get("pipName") or item.get("name") or "").lower()):
            installed = bool(plugin.get("installed"))
            name = str(plugin.get("pipName") or plugin.get("name") or "-")
            version = str(plugin.get("pipVersion") or (plugin.get("latestRelease") if not installed else "") or "-")
            mode = "devel" if plugin.get("devel") or plugin.get("installMode") == "devel" else "standard"
            rows.append((name, version, mode, "installed" if installed else "available"))

        widths = [max(len(header), max(len(row[index]) for row in rows)) for index, header in enumerate(headers)]
        typer.echo("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
        for row in rows:
            typer.echo("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
    except Exception as exc:
        typer.echo(f"Could not list plugins: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@binaries_app.command("list", help="List binary targets and their installation status for a plugin.")
def list_binaries(plugin_name: str = typer.Argument(..., help="Plugin pip name.")) -> None:
    try:
        from app.backend.bootstrap import bootstrapEnv
        bootstrapEnv()
        from app.backend.api.services.environment import prepareEnvironment
        prepareEnvironment()
        from app.backend.api.services.plugin_service import PluginService
        plugin = PluginService().getPlugin(plugin_name)
        if plugin is None:
            typer.echo(f"Plugin not found: {plugin_name}", err=True)
            raise typer.Exit(code=1)

        binaries = plugin.get("binaries") or []
        if not binaries:
            typer.echo(f"No binaries available for {plugin_name}.")
            return

        headers = ("NAME", "VERSION", "TARGET", "STATUS", "DEFAULT")
        rows = []
        for binary in binaries:
            rows.append((
                str(binary.get("name") or "-"),
                str(binary.get("version") or "-"),
                str(binary.get("target") or "-"),
                "installed" if binary.get("installed") else "not installed",
                "default" if binary.get("default") else "-",
            ))

        typer.echo(f"Binaries for {plugin_name}:")
        widths = [max(len(header), max(len(row[index]) for row in rows)) for index, header in enumerate(headers)]
        typer.echo("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
        for row in rows:
            typer.echo("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"Could not list plugin binaries: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("install", help="Install a Scipion plugin from the repository or a local devel checkout.")
def install(plugin_name: Optional[str] = typer.Argument(None, help="Plugin pip name for standard installations."), devel: Optional[Path] = typer.Option(None, "--devel", help="Install a local plugin directory in editable/devel mode."), skip_binaries: bool = typer.Option(False, "--skip-binaries", help="Skip installing plugin binaries."), force: bool = typer.Option(False, "--force", help="Force reinstall for devel plugins, when supported.")) -> None:
    if (plugin_name is None) == (devel is None):
        raise typer.BadParameter("Provide exactly one of PLUGIN_NAME or --devel PATH.")

    if force and devel is None:
        raise typer.BadParameter("--force is only supported with --devel.")

    try:
        from app.backend.bootstrap import bootstrapEnv
        bootstrapEnv()
        if devel is not None:
            from app.backend.api.services.plugin_devel_service import PluginDevelService
            result = PluginDevelService().installDevelPlugin(str(devel.expanduser().resolve()), skipBinaries=skip_binaries, force=force)
            name = result.get("pipName") or str(devel)
        else:
            from app.backend.api.services.environment import prepareEnvironment
            prepareEnvironment()
            from app.backend.api.services.plugin_service import PluginService
            result = PluginService().installPlugin(plugin_name, skipBinaries=skip_binaries)
        if result.get("installed") != "SUCCESS":
            typer.echo(f"Unexpected installation result: {result!r}", err=True)
            raise typer.Exit(code=1)
        from app.backend.api.services.plugins_revision import bumpPluginsRevision
        from app.backend.api.services.reload_trigger import triggerBackendReloadIfEnabled
        bumpPluginsRevision()
        triggerBackendReloadIfEnabled()
        typer.echo(f"Plugin installed in devel mode: {name}" if devel is not None else f"Plugin installed: {plugin_name}")
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"Plugin installation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
