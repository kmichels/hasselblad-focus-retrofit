"""Shared helpers for the folder-mode tests."""
import re
from pathlib import Path

INF = (0xFFFFFFFF, 1)           # the camera's "Infinity" SubjectDistance
KNOT_F, KNOT_M = 52.69814, 0.08261   # XCD 55V ladder knot, calibrated 0.77 m


def want(tool, lens, f, m):
    """The (numerator, distance) the tool should write for these maker values."""
    cals = tool.load_calibrations(Path(tool.__file__).resolve().parent / "calibration")
    d = cals[lens].correct(m, tool.thin_lens_m(f, m))
    return round(d * 1000), d


def counts(out):
    """Parse the '  label:   N' summary lines into a dict."""
    return {m.group(1).strip(): int(m.group(2))
            for m in re.finditer(r"^ {2}(.+?):\s+(\d+)\s*$", out, re.M)}


def logs_in(folder):
    return sorted(Path(folder).glob("hb-focus-retrofit-undo-*.jsonl"))


def sd_span(tool, path):
    info = tool.parse_file(path)
    return info.sd_offset, info.sd_offset + 8


def make_shoot(tmp_path, name="shoot"):
    shoot = tmp_path / name
    shoot.mkdir()
    return shoot
