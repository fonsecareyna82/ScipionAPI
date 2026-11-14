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


def test_GuidedInstallerCreatesFullUninstallMarker():
    content = INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert 'INSTALL_MARKER_NAME=".scipionweb-installation"' in content
    assert "INSTALL_TYPE=guided" in content
    assert "INSTALL_ROOT=${INSTALL_DIR}" in content
    assert "write_install_marker" in content
    assert "./scripts/scipionapi uninstall --full" in content


def test_GuidedInstallerSupportsManagedCliAlias():
    content = INSTALL_SCRIPT.read_text(
        encoding="utf-8"
    )

    assert "--create-alias" in content
    assert "--no-create-alias" in content
    assert "SCIPIONWEB_CREATE_ALIAS" in content

    assert (
        'CLI_ALIAS_BEGIN='
        '"# >>> ScipionWeb scipionapi >>>"'
        in content
    )

    assert (
        'CLI_ALIAS_END='
        '"# <<< ScipionWeb scipionapi <<<"'
        in content
    )

    assert "configure_cli_alias" in content
    assert "alias scipionapi=" in content

# Downloads: GitHub first, then the CNB server ----------------------------------------------------------------

import json
import sys

GITHUB = "https://github.com/fonsecareyna82/ScipionWeb/releases/download/v4.0.0/"
GITHUB_API = "https://api.github.com/repos/fonsecareyna82/ScipionWeb/releases?per_page=1"
CNB = "https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/"
MANIFEST = {"latest": "v4.0.0", "releases": {"v4.0.0": {
    "api": {"file": "ScipionAPI-v4.0.0.zip", "sha256": "aaa"},
    "web": {"file": "ScipionWeb-v4.0.0-dist.zip", "sha256": "bbb"}}}}


def runInstallerFunctions(tmp_path, served, commands, extraEnv=None):
    """Loads install.sh's functions with a curl that only serves `served` ({url: text}) and runs `commands`."""
    files = tmp_path / "served"
    files.mkdir(exist_ok=True)
    table = []
    for index, (url, text) in enumerate(served.items()):
        path = files / str(index)
        path.write_text(text, encoding="utf-8")
        table.append('[%s]=%s' % (json.dumps(url), json.dumps(str(path))))
    # The download addresses come from the script's defaults, not from this machine's settings
    script = """
set -euo pipefail
source %(installer)s
declare -A SERVED=(%(table)s)
curl() {
  local destination="" url=""
  while [[ $# -gt 0 ]]; do
    case "$1" in -o) destination="$2"; shift 2 ;; -*) shift ;; *) url="$1"; shift ;; esac
  done
  echo "GET ${url}" >> %(log)s
  [[ -n "${SERVED[$url]:-}" ]] || return 22
  cp "${SERVED[$url]}" "${destination}"
}
CONDA_PYTHON=%(python)s
DOWNLOAD_TOOL=curl
TMP_DIR=%(tmp)s/work  # removed when the installer exits
mkdir -p "${TMP_DIR}"
LOCAL_DIR=%(tmp)s/nothing-here
%(commands)s
""" % {"installer": INSTALL_SCRIPT, "table": " ".join(table), "log": tmp_path / "requests.log",
       "python": sys.executable, "tmp": tmp_path, "commands": commands}
    import os
    env = {key: value for key, value in os.environ.items() if not key.startswith("SCIPIONWEB_")}
    env.update(extraEnv or {})
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
    log = tmp_path / "requests.log"
    return result, log.read_text().split("\n") if log.exists() else []


RESOLVE = 'resolve_release; echo "RESULT ${RELEASE_SOURCE}|${BASE_URL}|${RELEASE_VERSION}|${API_FILE}|${API_SHA256}"'


def test_installer_takes_the_newest_github_release_first(tmp_path):
    served = {GITHUB_API: json.dumps([{"tag_name": "v4.0.0", "prerelease": True}]),
              GITHUB + "manifest.json": json.dumps(MANIFEST)}
    result, requests = runInstallerFunctions(tmp_path, served, RESOLVE)
    assert result.returncode == 0, result.stderr
    assert "RESULT GitHub|%s|v4.0.0|ScipionAPI-v4.0.0.zip|aaa" % GITHUB in result.stdout
    assert not any(CNB in line for line in requests)


def test_installer_falls_back_to_the_cnb_server_when_github_has_nothing(tmp_path):
    served = {GITHUB_API: "[]", CNB + "manifest.json": json.dumps(MANIFEST)}
    result, requests = runInstallerFunctions(tmp_path, served, RESOLVE)
    assert result.returncode == 0, result.stderr
    assert "RESULT the CNB download server|%s|v4.0.0|ScipionAPI-v4.0.0.zip|aaa" % CNB in result.stdout
    assert requests[0] == "GET " + GITHUB_API


def test_installer_takes_the_files_from_the_cnb_server_when_github_does_not_give_them(tmp_path):
    served = {GITHUB_API: json.dumps([{"tag_name": "v4.0.0"}]), GITHUB + "manifest.json": json.dumps(MANIFEST),
              CNB + "manifest.json": json.dumps(MANIFEST), CNB + "ScipionAPI-v4.0.0.zip": "api",
              CNB + "ScipionWeb-v4.0.0-dist.zip": "web"}
    commands = RESOLVE + '; download_release_archives "%s/api.zip" "%s/web.zip"; cat "%s/api.zip"' % (
        tmp_path, tmp_path, tmp_path)
    result, requests = runInstallerFunctions(tmp_path, served, commands)
    assert result.returncode == 0, result.stderr
    assert result.stdout.rstrip().endswith("api")
    assert "GET " + GITHUB + "ScipionAPI-v4.0.0.zip" in requests
    assert "GET " + CNB + "ScipionAPI-v4.0.0.zip" in requests
    assert requests.index("GET " + GITHUB + "ScipionAPI-v4.0.0.zip") < requests.index(
        "GET " + CNB + "ScipionAPI-v4.0.0.zip")


def test_installer_with_a_base_url_asks_only_there(tmp_path):
    mirror = "https://mirror.example.org/scipionweb/"
    served = {mirror + "manifest.json": json.dumps(MANIFEST)}
    result, requests = runInstallerFunctions(tmp_path, served, "BASE_URL_EXPLICIT=1; BASE_URL=%s; %s" % (
        mirror, RESOLVE))
    assert result.returncode == 0, result.stderr
    assert requests == ["GET " + mirror + "manifest.json", ""]


def test_installer_says_so_when_no_server_has_the_release(tmp_path):
    result, _ = runInstallerFunctions(tmp_path, {}, RESOLVE)
    assert result.returncode == 1
    assert "Could not resolve release latest from GitHub nor from" in result.stderr
