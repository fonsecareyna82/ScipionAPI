from pathlib import Path

import pytest

from scipionapi_cli.uninstall import (
    _validateFullInstallationRoot,
    _validateGuidedInstallationMarker,
    _validateLegacyInstallationRoot,
)
from scipionapi_cli.uninstall import (
    _validateFullInstallationRoot,
    _validateFullScipionHome,
    _validateGuidedInstallationMarker,
    _validateLegacyInstallationRoot,
)


def _writeMarker(repo_root: Path, install_root: Path) -> None:
    (repo_root / ".scipionweb-installation").write_text(
        "FORMAT=1\n"
        "INSTALL_TYPE=guided\n"
        f"INSTALL_ROOT={install_root}\n"
        f"SCIPION_HOME={install_root / 'scipion_home'}\n"
        "VERSION=v4.0.0\n",
        encoding="utf-8",
    )


def _writeLegacyLayout(repo_root: Path) -> None:
    (repo_root / "scripts").mkdir(parents=True)
    (repo_root / "scipion_home").mkdir(parents=True)
    (repo_root / "pyproject.toml").write_text("", encoding="utf-8")
    (repo_root / "alembic.ini").write_text("", encoding="utf-8")
    (repo_root / "scripts" / "scipionapi").write_text("", encoding="utf-8")
    (repo_root / "scipion_home" / ".env").write_text("", encoding="utf-8")


def test_ValidateGuidedInstallationMarkerAcceptsMatchingRoot(tmp_path):
    repo_root = tmp_path / "scipionweb"
    repo_root.mkdir()
    _writeMarker(repo_root, repo_root.resolve())

    marker = _validateGuidedInstallationMarker(repo_root)

    assert marker == repo_root / ".scipionweb-installation"


def test_ValidateGuidedInstallationMarkerRejectsMissingMarker(tmp_path):
    repo_root = tmp_path / "scipionweb"
    repo_root.mkdir()

    with pytest.raises(RuntimeError, match="guided installation marker"):
        _validateGuidedInstallationMarker(repo_root)


def test_ValidateGuidedInstallationMarkerRejectsMismatchedRoot(tmp_path):
    repo_root = tmp_path / "scipionweb"
    repo_root.mkdir()
    _writeMarker(repo_root, tmp_path / "something-else")

    with pytest.raises(RuntimeError, match="does not match"):
        _validateGuidedInstallationMarker(repo_root)


def test_ValidateFullInstallationRootUsesGuidedMarker(tmp_path):
    repo_root = tmp_path / "scipionweb"
    repo_root.mkdir()
    _writeMarker(repo_root, repo_root.resolve())

    assert _validateFullInstallationRoot(
        repo_root,
        legacyInstall=False,
    ) == "guided"


def test_ValidateLegacyInstallationRootAcceptsPackagedLayout(tmp_path):
    repo_root = tmp_path / "scipionweb"
    repo_root.mkdir()
    _writeLegacyLayout(repo_root)

    _validateLegacyInstallationRoot(repo_root)

    assert _validateFullInstallationRoot(
        repo_root,
        legacyInstall=True,
    ) == "legacy"


def test_ValidateLegacyInstallationRootRejectsGitCheckout(tmp_path):
    repo_root = tmp_path / "scipionweb"
    repo_root.mkdir()
    _writeLegacyLayout(repo_root)
    (repo_root / ".git").mkdir()

    with pytest.raises(RuntimeError, match="Git checkout"):
        _validateLegacyInstallationRoot(repo_root)


def test_ValidateFullScipionHomeAcceptsInstallationHome(tmp_path):
    repo_root = tmp_path / "scipionweb"
    scipion_home = repo_root / "scipion_home"

    repo_root.mkdir()
    scipion_home.mkdir()

    assert _validateFullScipionHome(
        repo_root,
        scipion_home,
    ) == scipion_home.resolve()


def test_ValidateFullScipionHomeRejectsExternalHome(tmp_path):
    repo_root = tmp_path / "scipionweb"
    external_home = tmp_path / "other-scipion-home"

    repo_root.mkdir()
    external_home.mkdir()

    with pytest.raises(
        RuntimeError,
        match="outside this installation",
    ):
        _validateFullScipionHome(
            repo_root,
            external_home,
        )


def test_ValidateFullScipionHomeRejectsSymlink(tmp_path):
    repo_root = tmp_path / "scipionweb"
    external_home = tmp_path / "external-home"

    repo_root.mkdir()
    external_home.mkdir()

    (repo_root / "scipion_home").symlink_to(
        external_home,
        target_is_directory=True,
    )

    with pytest.raises(
        RuntimeError,
        match="symbolic link",
    ):
        _validateFullScipionHome(
            repo_root,
            external_home,
        )