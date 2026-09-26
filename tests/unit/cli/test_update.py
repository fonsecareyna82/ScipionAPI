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
# ******************************************************************************

import scipionapi_cli.update as updateModule


def test_InstallUpdatedApiRefreshesScipionCoreFromPyproject(
    monkeypatch,
    tmp_path,
):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "\n".join([
            "[project]",
            "name = \"scipionapi\"",
            "dependencies = [",
            "  \"scipion-pyworkflow @ git+https://example.org/scipion-pyworkflow.git@devel\",",
            "  \"scipion-em @ git+https://example.org/scipion-em.git@devel\",",
            "  \"scipion-app @ git+https://example.org/scipion-app.git@devel\",",
            "  \"fastapi==0.116.1\",",
            "]",
            "",
        ]),
        encoding="utf-8",
    )

    pipCalls = []

    monkeypatch.setattr(
        updateModule,
        "_runPipInstall",
        lambda repoRoot, args: pipCalls.append(
            (repoRoot, list(args))
        ),
    )
    monkeypatch.setattr(
        updateModule,
        "_printStep",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        updateModule,
        "_printInfo",
        lambda *args, **kwargs: None,
    )

    updateModule._installUpdatedApi(tmp_path)

    assert pipCalls == [
        (
            tmp_path,
            [
                "--upgrade",
                "--force-reinstall",
                "--no-deps",
                "scipion-pyworkflow @ git+https://example.org/scipion-pyworkflow.git@devel",
                "scipion-em @ git+https://example.org/scipion-em.git@devel",
                "scipion-app @ git+https://example.org/scipion-app.git@devel",
            ],
        ),
        (
            tmp_path,
            ["-e", str(tmp_path)],
        ),
    ]
