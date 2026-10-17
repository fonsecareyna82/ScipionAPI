import os

import pytest

from app.backend.api.services import protocol_viewer_file_token_service as tokens


def test_token_round_trip_is_bound_to_the_project():
    token = tokens.signViewerFileToken(7, 'Runs/000115_X/extra/level_classes.xmd')
    assert tokens.isViewerFileToken(token)
    assert tokens.readViewerFileToken(token, 7) == 'Runs/000115_X/extra/level_classes.xmd'
    assert tokens.readViewerFileToken(token, 8) is None


def test_token_cannot_be_forged_or_altered():
    token = tokens.signViewerFileToken(7, 'Runs/a.sqlite')
    other = tokens.signViewerFileToken(7, 'Runs/b.sqlite')
    payload, signature = token[3:].split('.')
    other_payload = other[3:].split('.')[0]
    assert tokens.readViewerFileToken('vf.%s.%s' % (other_payload, signature), 7) is None
    assert tokens.readViewerFileToken('vf.%s.%s' % (payload, 'x' * 32), 7) is None
    assert tokens.readViewerFileToken('outputParticles', 7) is None


@pytest.mark.parametrize('path', [
    '/etc/passwd', '../secret', 'Runs/../../x', 'Runs//x', './x', '', 'a\\b', 'a\x00b',
])
def test_only_project_relative_paths_are_signed(path):
    with pytest.raises(ValueError):
        tokens.signViewerFileToken(7, path)


def test_resolution_requires_an_existing_file_inside_the_project(tmp_path):
    project = tmp_path / 'project'
    (project / 'Runs').mkdir(parents=True)
    (project / 'Runs' / 'a.xmd').write_text('data_info\n')
    outside = tmp_path / 'outside.xmd'
    outside.write_text('data_x\n')
    os.symlink(str(outside), str(project / 'Runs' / 'link.xmd'))

    absolute, relative = tokens.resolveViewerFileToken(
        tokens.signViewerFileToken(3, 'Runs/a.xmd'), 3, str(project))
    assert absolute == str((project / 'Runs' / 'a.xmd').resolve())
    assert relative == 'Runs/a.xmd'
    for path in ('Runs/link.xmd', 'Runs/missing.xmd'):
        with pytest.raises(LookupError):
            tokens.resolveViewerFileToken(
                tokens.signViewerFileToken(3, path), 3, str(project))
