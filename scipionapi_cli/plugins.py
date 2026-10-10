"""Plugin installation commands for the ScipionAPI CLI."""
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(no_args_is_help=True, help="Manage Scipion plugins.")


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
