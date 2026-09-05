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
import json
from urllib.error import URLError

import scipionapi_cli.doctor as doctor


def test_RevisionMissingMeansZero(tmp_path):
    row = doctor._checkRevisionFile(tmp_path, ".environment_revision", "Environment revision")

    assert row[1] == "OK"
    assert row[2].startswith("0 · not initialized")


def test_RevisionIsRead(tmp_path):
    (tmp_path / ".environment_revision").write_text("12", encoding="utf-8")

    row = doctor._checkRevisionFile(tmp_path, ".environment_revision", "Environment revision")

    assert row[1] == "OK"
    assert row[2].startswith("12 ·")


def test_InvalidRevisionFails(tmp_path):
    (tmp_path / ".environment_revision").write_text("invalid", encoding="utf-8")

    row = doctor._checkRevisionFile(tmp_path, ".environment_revision", "Environment revision")

    assert row[1] == "FAIL"


def test_RuntimeOverridesAreValidated(tmp_path):
    configDir = tmp_path / "config"
    configDir.mkdir()
    path = configDir / "scipionweb_environment.json"
    path.write_text(json.dumps({"SCIPION_JAVA_HOME": "/tmp/java", "CUSTOM_VAR": "value"}), encoding="utf-8")

    row = doctor._checkRuntimeOverrides(tmp_path)

    assert row[1] == "OK"
    assert row[2].startswith("2 configured")


def test_InvalidRuntimeOverridesFail(tmp_path):
    configDir = tmp_path / "config"
    configDir.mkdir()
    (configDir / "scipionweb_environment.json").write_text("{invalid", encoding="utf-8")

    row = doctor._checkRuntimeOverrides(tmp_path)

    assert row[1] == "FAIL"


def test_ApiHealthWarnsWhenUnavailable(monkeypatch):
    def unavailable(*args, **kwargs):
        raise URLError("connection refused")

    monkeypatch.setattr(doctor, "urlopen", unavailable)

    row = doctor._checkApiHealth({"API_HOST": "0.0.0.0", "API_PORT": "8080"})

    assert row[1] == "WARN"


def test_ApiHealthAcceptsScipionApi(monkeypatch):
    class Response:
        status = 200

        def getcode(self):
            return 200

        def read(self):
            return b'{"status":"ok","mode":"api-only"}'

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    monkeypatch.setattr(doctor, "urlopen", lambda *args, **kwargs: Response())

    row = doctor._checkApiHealth({"API_HOST": "0.0.0.0", "API_PORT": "8080"})

    assert row[1] == "OK"
    assert "mode=api-only" in row[2]


def test_WritableDirectoryIsOk(tmp_path):
    row = doctor._checkDirectoryWritable(tmp_path, "Projects directory")

    assert row[1] == "OK"
    assert "Writable" in row[2]


def test_NonWritableDirectoryFails(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.os, "access", lambda path, mode: False)

    row = doctor._checkDirectoryWritable(tmp_path, "Projects directory")

    assert row[1] == "FAIL"
    assert "Not writable" in row[2]


def test_RuntimeDirectoryCanBeCreated(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.os, "access", lambda path, mode: True)

    row = doctor._checkRuntimeDirectory(tmp_path)

    assert row[1] == "OK"
    assert "Can be created" in row[2]


def test_DiskSpaceWarnsWhenLow(tmp_path, monkeypatch):
    class Usage:
        total = 100 * doctor._GIB
        used = 91 * doctor._GIB
        free = 9 * doctor._GIB

    monkeypatch.setattr(doctor.shutil, "disk_usage", lambda path: Usage())

    row = doctor._checkDiskSpace(tmp_path, "Disk space")

    assert row[1] == "WARN"
    assert "9.0 GiB free" in row[2]


def test_DiskSpaceFailsWhenCritical(tmp_path, monkeypatch):
    class Usage:
        total = 100 * doctor._GIB
        used = 99 * doctor._GIB
        free = 1 * doctor._GIB

    monkeypatch.setattr(doctor.shutil, "disk_usage", lambda path: Usage())

    row = doctor._checkDiskSpace(tmp_path, "Disk space")

    assert row[1] == "FAIL"
    assert "1.0 GiB free" in row[2]


