from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[3]
WRAPPER = REPO_ROOT / "scripts" / "scipionapi"


def test_ScipionApiWrapperHasValidBashSyntax():
    result = subprocess.run(
        ["bash", "-n", str(WRAPPER)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_ScipionApiWrapperProtectsFullUninstallRoot():
    content = WRAPPER.read_text(encoding="utf-8")

    assert ".scipionweb-installation" in content
    assert "validateFullInstallRoot" in content
    assert "--legacy-install" in content
    assert '"${cmd}" == "uninstall"' in content

    assert 'local allowCleanedLegacy="${2:-0}"' in content
    assert 'validateFullInstallRoot "${allowLegacy}" "1"' in content
    assert 'SCIPION_HOME=${repoRoot}/scipion_home' in content


def test_ScipionApiWrapperBootstrapsJava21():
    content = WRAPPER.read_text(encoding="utf-8")

    assert 'javaPackage="${SCIPIONAPI_JAVA_PACKAGE:-openjdk=21}"' in content
    assert "ensureJavaRuntime()" in content
    assert "javaMajorVersion()" in content
    assert "ensureJavaRuntime" in content
    assert "conda-forge" in content


