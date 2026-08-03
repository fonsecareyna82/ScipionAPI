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
# * All comments concerning this program package may be sent to the
# * e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, Optional


class JsonSubprocessRunner:
    """Execute Python code in a clean process and return its JSON payload."""

    def run(
            self,
            code: str,
            operationName: str,
            extraEnv: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        startMarker = "__SCIPION_JSON_START__"
        endMarker = "__SCIPION_JSON_END__"

        code = textwrap.dedent(code).strip()

        wrappedCode = "\n".join(
            [
                "import json",
                "import sys",
                "",
                code,
                "",
                "try:",
                "    _scipionPayload",
                "except NameError:",
                '    raise RuntimeError("Subprocess code did not define _scipionPayload")',
                "",
                f'sys.stdout.write("{startMarker}\\n")',
                "sys.stdout.write(json.dumps(_scipionPayload))",
                f'sys.stdout.write("\\n{endMarker}\\n")',
                "sys.stdout.flush()",
            ]
        )

        projectRoot = Path(__file__).resolve().parents[4]

        env = os.environ.copy()
        existingPythonPath = env.get("PYTHONPATH", "")

        env["PYTHONPATH"] = (
            str(projectRoot)
            + (
                os.pathsep + existingPythonPath
                if existingPythonPath
                else ""
            )
        )

        for key, value in (extraEnv or {}).items():
            if value is not None:
                env[str(key)] = str(value)

        result = subprocess.run(
            [sys.executable, "-c", wrappedCode],
            cwd=str(projectRoot),
            env=env,
            capture_output=True,
            text=True,
        )

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        if result.returncode != 0:
            raise RuntimeError(
                f"{operationName} failed in subprocess.\n"
                f"Return code: {result.returncode}\n"
                f"STDOUT:\n{stdout}\n\n"
                f"STDERR:\n{stderr}"
            )

        startIndex = stdout.find(startMarker)
        endIndex = stdout.find(endMarker)

        if startIndex == -1 or endIndex == -1:
            raise RuntimeError(
                f"{operationName} did not return a valid JSON payload block.\n"
                f"STDOUT:\n{stdout}\n\n"
                f"STDERR:\n{stderr}"
            )

        payload = stdout[startIndex + len(startMarker):endIndex].strip()

        if not payload:
            raise RuntimeError(
                f"{operationName} returned an empty JSON payload.\n"
                f"STDOUT:\n{stdout}\n\n"
                f"STDERR:\n{stderr}"
            )

        try:
            return json.loads(payload)

        except json.JSONDecodeError as ex:
            raise RuntimeError(
                f"{operationName} returned invalid JSON.\n"
                f"Payload:\n{payload}\n\n"
                f"STDOUT:\n{stdout}\n\n"
                f"STDERR:\n{stderr}"
            ) from ex