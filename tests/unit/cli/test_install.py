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
import scipionapi_cli.install as installModule


def test_ResolveApiPortUsesRequestedPort():
    assert installModule._resolveApiPort(
        {"API_PORT": "41000"},
        requestedApiPort=42000,
    ) == "42000"


def test_ResolveApiPortPreservesExistingPort():
    assert installModule._resolveApiPort(
        {"API_PORT": "41000"},
    ) == "41000"


def test_ResolveApiPortSelectsFreePort(monkeypatch):
    monkeypatch.setattr(
        installModule,
        "getFreePort",
        lambda: 45000,
    )

    assert installModule._resolveApiPort({}) == "45000"


def test_FindFreePortSkipsExcludedPort(monkeypatch):
    ports = iter([
        45000,
        45001,
    ])

    monkeypatch.setattr(
        installModule,
        "getFreePort",
        lambda: next(ports),
    )

    assert installModule._findFreePort(
        excludedPorts=["45000"],
    ) == "45001"


def test_EnsureScipionJavaHomeAddsManagedJava(monkeypatch, tmp_path):
    javaHome = tmp_path / "env"
    javaBin = javaHome / "bin" / "java"
    javaBin.parent.mkdir(parents=True)
    javaBin.write_text("", encoding="utf-8")
    javaBin.chmod(0o755)

    configPath = tmp_path / "scipion.conf"
    configPath.write_text(
        "[PYWORKFLOW]\nSCIPION_DOMAIN = pwem\n",
        encoding="utf-8",
    )

    changed = installModule._ensureScipionJavaHome(
        configPath,
        javaHome,
    )

    assert changed is True
    assert (
        f"SCIPION_JAVA_HOME = {javaHome}"
        in configPath.read_text(encoding="utf-8")
    )


def test_EnsureScipionJavaHomeRepairsInvalidPath(tmp_path):
    javaHome = tmp_path / "scipion4Web"
    javaBin = javaHome / "bin" / "java"
    javaBin.parent.mkdir(parents=True)
    javaBin.write_text("", encoding="utf-8")
    javaBin.chmod(0o755)

    configPath = tmp_path / "scipion.conf"
    configPath.write_text(
        "[PYWORKFLOW]\n"
        "SCIPION_JAVA_HOME = /old/scipion3Web\n",
        encoding="utf-8",
    )

    changed = installModule._ensureScipionJavaHome(
        configPath,
        javaHome,
    )

    assert changed is True

    content = configPath.read_text(encoding="utf-8")

    assert "/old/scipion3Web" not in content
    assert f"SCIPION_JAVA_HOME = {javaHome}" in content


def test_EnsureScipionJavaHomePreservesValidCustomPath(tmp_path):
    customHome = tmp_path / "custom-java"
    customBin = customHome / "bin" / "java"
    customBin.parent.mkdir(parents=True)
    customBin.write_text("", encoding="utf-8")
    customBin.chmod(0o755)

    managedHome = tmp_path / "scipion4Web"
    managedBin = managedHome / "bin" / "java"
    managedBin.parent.mkdir(parents=True)
    managedBin.write_text("", encoding="utf-8")
    managedBin.chmod(0o755)

    configPath = tmp_path / "scipion.conf"
    configPath.write_text(
        "[PYWORKFLOW]\n"
        f"SCIPION_JAVA_HOME = {customHome}\n",
        encoding="utf-8",
    )

    changed = installModule._ensureScipionJavaHome(
        configPath,
        managedHome,
    )

    assert changed is False
    assert (
        f"SCIPION_JAVA_HOME = {customHome}"
        in configPath.read_text(encoding="utf-8")
    )


