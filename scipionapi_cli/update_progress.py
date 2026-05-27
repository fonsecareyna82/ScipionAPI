from __future__ import annotations

from typing import Callable

from scipionapi_cli import update as baseUpdate


class UpdateProgress:
    # Lightweight progress helper for the update command.
    def __init__(self) -> None:
        self.stepIndex = 0

    def step(self, title: str, detail: str = "") -> None:
        self.stepIndex += 1
        prefix = f"[{self.stepIndex:02d}]"
        if baseUpdate._HAS_RICH:
            if detail:
                baseUpdate._console.print(
                    f"[bold magenta]{prefix} {title}[/bold magenta] [dim]{detail}[/dim]"
                )
            else:
                baseUpdate._console.print(f"[bold magenta]{prefix} {title}[/bold magenta]")
        else:
            if detail:
                print(f"\n{prefix} {title} | {detail}", flush=True)
            else:
                print(f"\n{prefix} {title}", flush=True)


def updateCommand(*args, **kwargs) -> None:
    # Run the original updater with numbered live progress steps.
    progress = UpdateProgress()
    originalPrintStep: Callable[..., None] = baseUpdate._printStep

    try:
        baseUpdate._printStep = progress.step
        return baseUpdate.updateCommand(*args, **kwargs)
    finally:
        baseUpdate._printStep = originalPrintStep
