from relml import __version__
from relml.config import load_settings
from pathlib import Path

def test_version():
    assert isinstance(__version__, str) and len(__version__) > 0

def test_settings_loads():
    s = load_settings()
    assert "data" in s.paths["data_dir"]
    assert s.env is not None

def test_required_paths_exist_or_mountpoint():
    # We don't require the dirs to exist until runtime, but ensure the root project file exists.
    assert Path("config/settings.yaml").exists()
