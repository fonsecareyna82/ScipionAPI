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
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Dict, Optional

from scipionapi_cli.envfile import exportEnvToOs, readEnvFile, writeEnvFile
from scipionapi_cli.install import _resolveScipionHome
from scipionapi_cli.shell import resolveRepoRoot


def _safeRemoveTree(path: Path) -> None:
    # safeRemoveTree
    if not path.exists():
        return
    shutil.rmtree(path, ignore_errors=True)


def _safeExtractZip(zipPath: Path, destDir: Path) -> None:
    # safeExtractZipPreventZipSlip
    destDir.mkdir(parents=True, exist_ok=True)
    destRoot = destDir.resolve()

    with zipfile.ZipFile(zipPath, "r") as zf:
        for member in zf.infolist():
            memberPath = (destDir / member.filename).resolve()
            if not str(memberPath).startswith(str(destRoot)):
                raise RuntimeError(f"Unsafe zip content detected: {member.filename}")
        zf.extractall(destDir)


def _normalizeViteDistLayout(extractedDir: Path) -> Path:
    # normalizeViteDistLayout
    # Accept either:
    # - extractedDir/index.html (dist content at root)
    # - extractedDir/dist/index.html (dist folder inside zip)
    if (extractedDir / "index.html").exists():
        return extractedDir

    distDir = extractedDir / "dist"
    if (distDir / "index.html").exists():
        return distDir

    children = [p for p in extractedDir.iterdir() if p.is_dir()]
    if len(children) == 1 and (children[0] / "index.html").exists():
        return children[0]

    raise RuntimeError(
        "Web build not detected. Expected index.html at the root, or inside dist/, "
        "or inside a single top-level folder."
    )


def _copyDirContents(srcDir: Path, dstDir: Path) -> None:
    # copyDirContents
    dstDir.mkdir(parents=True, exist_ok=True)
    for item in srcDir.iterdir():
        target = dstDir / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def _writeWebConfigJs(distDir: Path, apiBaseUrl: str) -> None:
    # writeWebConfigJs
    distDir.mkdir(parents=True, exist_ok=True)
    configPath = distDir / "config.js"
    payload = {"apiBaseUrl": apiBaseUrl.rstrip("/")}
    content = f"window.__SCIPION_WEB_CONFIG__ = {json.dumps(payload, ensure_ascii=False)};\n"
    configPath.write_text(content, encoding="utf-8")


def deployWebDist(
    scipionHome: Path,
    webDist: Path,
    apiBaseUrl: str,
) -> Path:
    # deployWebDistToScipionHome
    webRoot = scipionHome / "web"
    targetDist = webRoot / "dist"

    _safeRemoveTree(targetDist)
    targetDist.mkdir(parents=True, exist_ok=True)

    webDist = webDist.expanduser().resolve()
    if webDist.is_dir():
        # deployFromDirectory
        normalizedSrc = webDist
        if (webDist / "dist" / "index.html").exists() and not (webDist / "index.html").exists():
            normalizedSrc = webDist / "dist"
        if not (normalizedSrc / "index.html").exists():
            raise RuntimeError(f"Invalid web dist directory: {webDist} (index.html not found)")
        _copyDirContents(normalizedSrc, targetDist)

    elif webDist.is_file() and webDist.suffix.lower() == ".zip":
        # deployFromZip
        tempExtract = webRoot / ".dist_extract_tmp"
        _safeRemoveTree(tempExtract)
        tempExtract.mkdir(parents=True, exist_ok=True)

        _safeExtractZip(webDist, tempExtract)
        normalizedSrc = _normalizeViteDistLayout(tempExtract)
        _copyDirContents(normalizedSrc, targetDist)
        _safeRemoveTree(tempExtract)

    else:
        raise RuntimeError(f"Unsupported webDist input: {webDist} (expected directory or .zip file)")

    _writeWebConfigJs(targetDist, apiBaseUrl)
    return targetDist


def provisionCommand(
    adminUser: str,
    adminEmail: str,
    adminPassword: str,
    webDist: Optional[str] = None,
    apiMountPath: str = "/api",
    apiBaseUrl: Optional[str] = None,
) -> None:
    # provisionCommandOneShot
    from scipionapi_cli.install import installCommand
    from scipionapi_cli.runtime import startCommand

    repoRoot = resolveRepoRoot()

    defaultScipionHome = (repoRoot / "scipion_home").resolve()
    defaultEnvPath = defaultScipionHome / ".env"
    existing = readEnvFile(defaultEnvPath)

    scipionHome = _resolveScipionHome(repoRoot, existing)
    envPath = scipionHome / ".env"

    # runInstallFirst
    installCommand(adminUser=adminUser, adminEmail=adminEmail, adminPassword=adminPassword)

    env = readEnvFile(envPath)

    # optionalWebDeploy
    if webDist:
        # enableIntegratedModeDefaults
        resolvedApiMountPath = (apiMountPath or "/api").strip()
        resolvedApiBaseUrl = (apiBaseUrl or resolvedApiMountPath).strip() or "/api"

        distPath = deployWebDist(
            scipionHome=scipionHome,
            webDist=Path(webDist),
            apiBaseUrl=resolvedApiBaseUrl,
        )

        updates: Dict[str, str] = {
            "SERVE_WEB": "1",
            "API_MOUNT_PATH": resolvedApiMountPath,
            "WEB_DIST_PATH": str(distPath),
            "WEB_API_BASE_URL": resolvedApiBaseUrl,
        }
        writeEnvFile(envPath, updates)
        exportEnvToOs(envPath)
        env = readEnvFile(envPath)
    else:
        # keepApiOnlyModeByDefault
        if (env.get("SERVE_WEB") or "").strip() != "1":
            writeEnvFile(envPath, {"SERVE_WEB": "0"})
            exportEnvToOs(envPath)
            env = readEnvFile(envPath)

    # startServices
    startCommand()

    apiHost = env.get("API_HOST", "0.0.0.0")
    apiPort = env.get("API_PORT", "8080")
    serveWeb = (env.get("SERVE_WEB") or "").strip() == "1"
    mountPath = (env.get("API_MOUNT_PATH") or "/api").strip()

    if serveWeb:
        print(f"Provision completed. Web: http://{apiHost}:{apiPort}/")
        print(f"API: http://{apiHost}:{apiPort}{mountPath}/docs")
    else:
        print(f"Provision completed. API: http://{apiHost}:{apiPort}/docs")
