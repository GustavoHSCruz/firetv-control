"""Start the panel against the explicit fake ADB, for browser integration tests."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from firetv_control.backend import FireTV
from firetv_control.web import serve

serve(FireTV(adb=str(Path(__file__).with_name('fake_adb.py').resolve())), port=0, open_browser=False)
