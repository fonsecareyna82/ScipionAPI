"""The web reads and writes the Xmipp picker's session files as the desktop does."""
from app.backend.api.services import xmipp_picking_files as files

# As written by the Java picker (JMetaDataIO.saveData).
DESKTOP_POS = (
    "# XMIPP_STAR_1 * \n#\ndata_header\nloop_\n_pickingMicrographState\n_autopickPercent\n_cost\n"
    "          Supervised                  50                 0.0\n"
    "data_particles\nloop_\n_xcoor\n_ycoor\n"
    "                3762                1650\n"
    "                4530                1260\n"
    "data_particles_auto\nloop_\n_xcoor\n_ycoor\n_cost\n_enabled\n"
    "                 811                3391  0.9862563610076904                   1\n"
    "                 250                 300                -1.0                  -1\n"
)


def test_desktop_session_files_are_read_and_written_back_byte_for_byte(tmp_path):
    path = tmp_path / "mic.pos"
    path.write_text(DESKTOP_POS)
    picks = files.readPos(str(path))
    assert picks.state == "Supervised" and picks.autopickPercent == 50
    assert picks.manual == [(3762, 1650), (4530, 1260)]
    assert picks.automatic == [(811, 3391, 0.9862563610076904, 1), (250, 300, -1.0, -1)]
    files.writePos(str(path), picks)
    assert path.read_text() == DESKTOP_POS


def test_only_enabled_particles_above_the_threshold_count_as_picked():
    picks = files.MicrographPicks(threshold=0.5, automatic=[
        (1, 1, 0.9, 1), (2, 2, 0.4, 1), (3, 3, 0.95, -1)])
    assert picks.activeAutomatic() == [(1, 1, 0.9, 1)]


def test_a_micrograph_without_particles_has_no_session_file(tmp_path):
    path = tmp_path / "mic.pos"
    path.write_text(DESKTOP_POS)
    files.writePos(str(path), files.MicrographPicks())
    assert not path.exists()
    assert files.readPos(str(path)) == files.MicrographPicks()


def test_config_round_trip_and_defaults(tmp_path):
    path = tmp_path / "config.xmd"
    assert files.readConfig(str(path)) is None
    config = files.PickerConfig(micrograph="mic_DW", particleSize=99, mode="Supervised",
                                manualParticlesNum=26, autoParticlesNum=4949)
    files.writeConfig(str(path), config)
    assert files.readConfig(str(path)) == config
    assert "         Supervised                  26                4949\n" in path.read_text()


def test_session_file_names_follow_the_desktop_and_scipion():
    assert files.posFileName("Runs/000025_X/extra/ja_115_aligned_mic_DW.mrc") == "ja_115_aligned_mic_DW.pos"
    assert files.posFileName("3@Runs/mics.mrcs") == "mics.pos"


def test_config_needs_the_current_micrograph(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        files.writeConfig(str(tmp_path / "config.xmd"), files.PickerConfig(micrograph=""))


def test_the_picker_filters_are_read_as_imagej_commands(tmp_path):
    path = tmp_path / "config.xmd"
    config = files.PickerConfig(micrograph="a_DW")
    assert config.imageFilters() == list(files.DEFAULT_FILTERS)
    # Written as the Java picker writes its defaults.
    assert config.filters == [("Gaussian_Blur...", "sigma=2"), ("Enhance_Contrast", "saturated=0.4")]
    config.filters = [("Gaussian_Blur...", "sigma=3"), ("Invert_LUT", "NULL"), ("Bandpass_Filter...", "filter&large=40")]
    files.writeConfig(str(path), config)
    stored = files.readConfig(str(path))
    assert stored.imageFilters() == [("Gaussian Blur...", "sigma=3"), ("Invert LUT", ""),
                                     ("Bandpass Filter...", "filter_large=40")]
    # A filters block without filters means no filters, not the defaults.
    stored.filters = []
    files.writeConfig(str(path), stored)
    assert files.readConfig(str(path)).imageFilters() == []
