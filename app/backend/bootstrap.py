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
import os
from pathlib import Path

from dotenv import load_dotenv


def _resolveDefaultScipionHome() -> Path:
    # resolveDefaultScipionHomeFromRepoRoot
    # bootstrap.py lives at: <repoRoot>/app/backend/bootstrap.py
    repoRoot = Path(__file__).resolve().parents[2]
    return (repoRoot / "scipion_home").resolve()


def bootstrapEnv() -> None:
    # bootstrapEnvFromScipionHome
    scipionHomeRaw = (os.getenv("SCIPION_HOME") or "").strip()
    scipionHome = Path(scipionHomeRaw).expanduser().resolve() if scipionHomeRaw else _resolveDefaultScipionHome()

    envPath = scipionHome / ".env"
    if not envPath.exists():
        # optionalStrictMode
        if (os.getenv("SCIPIONAPI_BOOTSTRAP_STRICT") or "").strip() == "1":
            raise RuntimeError(f"Missing .env at: {envPath}. Run `./scripts/scipionapi install` (or `provision`).")
        return

    # doNotOverrideExistingEnv
    load_dotenv(dotenv_path=str(envPath), override=False)
