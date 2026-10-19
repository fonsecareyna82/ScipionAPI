"""The Java session of Xmipp's picker, with Xmipp's own bindings (skipped without them).

Templates and centering as the desktop picker does them: particles of a
synthetic micrograph, whose centres are known, are picked a few pixels off and
centered back.
"""
import numpy as np
import pytest


@pytest.fixture
def javaSession(tmp_path):
    pytest.importorskip("xmipp3")
    from pwem import emlib
    from app.backend.runtime.xmipp_classifier_session import ClassifierError, ClassifierSession

    rng = np.random.default_rng(3)
    data = rng.normal(0.0, 0.4, (400, 400)).astype(np.float32)
    yy, xx = np.indices(data.shape)
    centres = [(x, y) for x in range(50, 360, 75) for y in range(50, 360, 75)]
    for x, y in centres:
        # A dark disk with a bright rim, as a particle seen in a micrograph.
        r = np.hypot(xx - x, yy - y)
        data -= np.exp(-(r / 9.0) ** 2) * 3.0
        data += np.exp(-((r - 14.0) / 3.0) ** 2) * 1.0
    micrograph = tmp_path / "mic.mrc"
    image = emlib.Image()
    image.setData(data)
    image.write(str(micrograph))
    try:
        session = ClassifierSession(str(tmp_path), 48, [str(micrograph)], str(tmp_path))
    except (ClassifierError, OSError) as error:
        pytest.skip("Xmipp's Java bindings are not available: %s" % error)
    yield session, str(micrograph), centres, tmp_path
    session.close()


def test_particles_picked_off_their_centre_are_centered_on_the_templates(javaSession):
    session, micrograph, centres, folder = javaSession
    session.setFilters([("Gaussian Blur...", "sigma=1")])
    templates = str(folder / "templates.stk")
    used = session.rebuildTemplates(48, 1, templates, [(micrograph, x, y) for x, y in centres[:10]])
    assert used == 10
    assert (folder / "templates.stk").exists()
    before = after = 0.0
    for (x, y), (dx, dy) in zip(centres[10:], [(5, -4), (-6, 3), (4, 5), (-3, -6), (6, 2)] * 3):
        cx, cy = session.center(48, 1, templates, micrograph, x + dx, y + dy)
        before += np.hypot(dx, dy)
        after += np.hypot(cx - x, cy - y)
    assert after < 0.3 * before
    # A particle joins the templates; a box out of the micrograph is ignored.
    assert session.addToTemplates(48, 1, templates, micrograph, *centres[0]) == 1
    assert session.center(48, 1, templates, micrograph, 3, 3) == (3, 3)
