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


def test_NvidiaGpuDetectedWithoutSmiFailsDriver(monkeypatch):
    monkeypatch.setattr(doctor, "_hasNvidiaDisplayDevice", lambda: True)
    monkeypatch.setattr(doctor.shutil, "which", lambda command: None)

    rows = doctor._checkNvidiaRuntime()

    gpuRow = next(row for row in rows if row[0] == "NVIDIA GPU")
    driverRow = next(row for row in rows if row[0] == "NVIDIA driver")

    assert gpuRow[1] == "OK"
    assert driverRow[1] == "FAIL"
    assert "nvidia-smi" in driverRow[2]


def test_NoNvidiaGpuWithoutSmiWarns(monkeypatch):
    monkeypatch.setattr(doctor, "_hasNvidiaDisplayDevice", lambda: False)
    monkeypatch.setattr(doctor.shutil, "which", lambda command: None)

    rows = doctor._checkNvidiaRuntime()

    gpuRow = next(row for row in rows if row[0] == "NVIDIA GPU")
    driverRow = next(row for row in rows if row[0] == "NVIDIA driver")

    assert gpuRow[1] == "WARN"
    assert driverRow[1] == "WARN"


def test_NvidiaRuntimeReportsGpuDriverAndCuda(monkeypatch):
    class Result:
        def __init__(self, stdout="", stderr="", returncode=0):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    def fakeRunCmd(args, **kwargs):
        if any(str(arg).startswith("--query-gpu=") for arg in args):
            return Result(
                stdout="0, NVIDIA RTX 4090, 24564, 580.82.09\n",
            )

        return Result(
            stdout="NVIDIA-SMI 580.82.09    Driver Version: 580.82.09    CUDA Version: 13.0\n",
        )

    monkeypatch.setattr(doctor, "_hasNvidiaDisplayDevice", lambda: True)
    monkeypatch.setattr(doctor.shutil, "which", lambda command: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(doctor, "runCmd", fakeRunCmd)

    rows = doctor._checkNvidiaRuntime()

    gpuRow = next(row for row in rows if row[0] == "NVIDIA GPU")
    driverRow = next(row for row in rows if row[0] == "NVIDIA driver")
    cudaRow = next(row for row in rows if row[0] == "CUDA driver capability")

    assert gpuRow[1] == "OK"
    assert "NVIDIA RTX 4090" in gpuRow[2]

    assert driverRow[1] == "OK"
    assert "580.82.09" in driverRow[2]

    assert cudaRow[1] == "OK"
    assert "CUDA 13.0" in cudaRow[2]


def test_CudaToolkitWarnsWhenNvccMissing(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda command: None)

    row = doctor._checkCudaToolkit()

    assert row[1] == "WARN"
    assert "nvcc not found" in row[2]


def test_CudaToolkitReportsVersion(monkeypatch):
    class Result:
        stdout = "Cuda compilation tools, release 12.4, V12.4.131"
        stderr = ""
        returncode = 0

    monkeypatch.setattr(doctor.shutil, "which", lambda command: "/usr/local/cuda/bin/nvcc")
    monkeypatch.setattr(doctor, "runCmd", lambda *args, **kwargs: Result())

    row = doctor._checkCudaToolkit()

    assert row[1] == "OK"
    assert "CUDA 12.4" in row[2]


def test_CudaVisibilityWarnsWhenDisabled(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "-1")

    row = doctor._checkCudaVisibility()

    assert row[1] == "WARN"
    assert "explicitly hidden" in row[2]


def test_CudaVisibilityReportsSelectedDevices(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,2")

    row = doctor._checkCudaVisibility()

    assert row[1] == "OK"
    assert "0,2" in row[2]


