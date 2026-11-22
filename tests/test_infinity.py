"""Frames focused at infinity: the maker note says magnification 0 with a
non-zero focal value, and the stored SubjectDistance is rewritten as the EXIF
standard's infinity (numerator 0xFFFFFFFF). A maker note whose focus fields
are all zero is a different thing (the camera lost them) and stays skipped."""
import json
import struct

import pytest
from fixtures import build_3fr
from folder_helpers import INF, KNOT_F, KNOT_M, counts, logs_in, make_shoot, sd_span

INF_F = 56.634          # XCD 55V focal value at the infinity stop
STALE = (840, 1000)     # a leftover close-focus value


def _infinity_file(shoot, name="a.3FR", **kw):
    args = dict(subject_distance=STALE, maker_f=INF_F, maker_m=0.0)
    args.update(kw)
    return build_3fr(shoot / name, **args)


def test_infinity_frame_with_stale_distance_is_rewritten_to_infinity(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = _infinity_file(shoot)
    before = p.read_bytes()
    lo, hi = sd_span(tool, p)
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    info = tool.parse_file(p)
    assert (info.sd_num, info.sd_den) == (0xFFFFFFFF, 1)
    after = p.read_bytes()
    assert len(after) == len(before)
    assert after[:lo] == before[:lo] and after[hi:] == before[hi:]
    assert after[lo:hi] == struct.pack("<II", 0xFFFFFFFF, 1)
    assert "stored 0.840 -> Infinity" in out
    assert counts(out)["rewritten in place"] == 1


def test_infinity_big_endian(tool, tmp_path):
    shoot = make_shoot(tmp_path)
    p = _infinity_file(shoot, byte_order="MM")
    lo, hi = sd_span(tool, p)
    assert tool.main([str(shoot)]) == 0
    assert p.read_bytes()[lo:hi] == struct.pack(">II", 0xFFFFFFFF, 1)


def test_already_infinity_is_unchanged_and_second_run_is_a_noop(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = _infinity_file(shoot, subject_distance=INF)
    before = p.read_bytes()
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    assert counts(out)["unchanged"] == 1 and "Infinity" in out
    assert p.read_bytes() == before and logs_in(shoot) == []
    # a stale file: first run rewrites, second run changes nothing and logs nothing
    q = _infinity_file(shoot, "b.3FR")
    tool.main([str(shoot)])
    capsys.readouterr()
    after_first = q.read_bytes()
    n_logs = len(logs_in(shoot))
    assert tool.main([str(shoot)]) == 0
    c = counts(capsys.readouterr().out)
    assert c["rewritten in place"] == 0 and c["unchanged"] == 2
    assert q.read_bytes() == after_first and len(logs_in(shoot)) == n_logs


def test_infinity_with_other_denominator_is_normalised(tool, tmp_path):
    shoot = make_shoot(tmp_path)
    p = _infinity_file(shoot, subject_distance=(0xFFFFFFFF, 1000))
    assert tool.main([str(shoot)]) == 0
    assert (tool.parse_file(p).sd_num, tool.parse_file(p).sd_den) == (0xFFFFFFFF, 1)


def test_infinity_log_entry_is_valid_json_and_undo_is_byte_identical(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = _infinity_file(shoot)
    before = p.read_bytes()
    tool.main([str(shoot)])
    capsys.readouterr()
    (log,) = logs_in(shoot)
    text = log.read_text()
    assert "Infinity" not in text and "NaN" not in text      # strict JSON
    entry = json.loads(text.splitlines()[0], parse_constant=lambda c: pytest.fail(c))
    assert entry["new_hex"] == struct.pack("<II", 0xFFFFFFFF, 1).hex()
    assert entry["old_hex"] == struct.pack("<II", *STALE).hex()
    assert tool.main(["undo", str(log)]) == 0
    assert p.read_bytes() == before
    assert tool.main(["undo", str(log)]) == 0       # idempotent
    assert p.read_bytes() == before


def test_dry_run_reports_infinity_and_writes_nothing(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = _infinity_file(shoot)
    before = p.read_bytes()
    assert tool.main([str(shoot), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "would rewrite stored 0.840 -> Infinity" in out
    assert p.read_bytes() == before and logs_in(shoot) == []


def test_infinity_applies_to_a_lens_without_calibration(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = _infinity_file(shoot, lens_model="XCD 38V", maker_f=37.5, focal_length=(38, 1))
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    assert counts(out)["rewritten in place"] == 1
    assert tool.parse_file(p).sd_num == 0xFFFFFFFF


def test_all_zero_maker_note_stays_skipped_with_its_message(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = _infinity_file(shoot, maker_f=0.0, maker_m=0.0)
    before = p.read_bytes()
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    assert "skipped: maker-note focus fields are zero (f=0, m=0)" in out
    assert counts(out)["skipped, no focus data"] == 1
    assert p.read_bytes() == before and logs_in(shoot) == []


def test_infinity_with_implausible_focal_value_is_skipped(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = _infinity_file(shoot, maker_f=500.0)
    before = p.read_bytes()
    assert tool.main([str(shoot)]) == 0
    assert counts(capsys.readouterr().out)["skipped, no focus data"] == 1
    assert p.read_bytes() == before


def test_infinity_frame_without_a_tag_is_left_alone(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = _infinity_file(shoot, subject_distance=None)
    before = p.read_bytes()
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    assert counts(out)["skipped, infinity, no tag to correct"] == 1
    assert "focused at infinity" in out
    assert p.read_bytes() == before and not (shoot / "retrofitted").exists()


def test_mixed_folder_close_and_infinity(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    close = build_3fr(shoot / "close.3FR", subject_distance=STALE,
                      maker_f=KNOT_F, maker_m=KNOT_M)
    inf = _infinity_file(shoot)
    assert tool.main([str(shoot)]) == 0
    c = counts(capsys.readouterr().out)
    assert c["rewritten in place"] == 2
    assert tool.parse_file(close).subject_distance == pytest.approx(0.77, abs=0.001)
    assert tool.parse_file(inf).sd_num == 0xFFFFFFFF
