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

import subprocess
import sys
import signal


def startBackend():
    return subprocess.Popen([sys.executable, "-m", "uvicorn", "app.backend.main:app", "--host", "0.0.0.0", "--port", "8080"])


def startUI():
    subprocess.run(["python", "-m", "app.ui.main"])


def main():
    backend_process = startBackend()
    print("Backend started, PID:", backend_process.pid)

    try:
        startUI()
    except KeyboardInterrupt:
        print("Shutting down...")

    finally:
        backend_process.send_signal(signal.SIGINT)
        backend_process.wait()
        print("Backend stopped.")


if __name__ in {"__main__", "__mp_main__"}:
    main()

