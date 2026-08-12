from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SCRIPT = REPO_ROOT / "install.sh"


def test_GuidedInstallerHasValidBashSyntax():
    result = subprocess.run(
        ["bash", "-n", str(INSTALL_SCRIPT)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_GuidedInstallerHelpIsAvailableWithoutPreflight():
    result = subprocess.run(
        ["bash", str(INSTALL_SCRIPT), "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "ScipionWeb administrator username" in result.stdout
    assert "--check-only" in result.stdout
    assert "--non-interactive" in result.stdout
