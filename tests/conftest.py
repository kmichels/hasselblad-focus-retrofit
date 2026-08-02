import importlib.util
from pathlib import Path

import pytest

TOOL_PATH = Path(__file__).resolve().parent.parent / "hb-focus-retrofit.py"


@pytest.fixture(scope="session")
def tool():
    spec = importlib.util.spec_from_file_location("hb_focus_retrofit", TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
