from importlib.metadata import version

from voicerig import __version__
from voicerig.app.main import app, health


def test_version_is_single_sourced():
    assert version("voicerig") == __version__
    assert app.version == __version__
    assert health()["version"] == __version__
