"""Undo log content and ordering, and the `undo` subcommand."""
import json
import os
import re
import struct
from pathlib import Path

import pytest
from fixtures import build_3fr
from folder_helpers import INF, KNOT_F, KNOT_M, counts, logs_in, make_shoot, sd_span, want


# --------------------------------------------------------------- undo log

def test_log_has_every_field(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    (shoot / "sub").mkdir()
    p = build_3fr(shoot / "sub" / "a.3FR", subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)
    off = tool.parse_file(p).sd_offset
    size = p.stat().st_size
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    (log,) = logs_in(shoot)
    assert re.fullmatch(
        r"hb-focus-retrofit-undo-\d{8}T\d{6}Z-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl",
        log.name)
    assert str(log) in out or log.name in out
    (line,) = log.read_text().splitlines()
    e = json.loads(line)
    num, d = want(tool, "XCD 55V", KNOT_F, KNOT_M)
    assert e["path"] == str(p.resolve()) and os.path.isabs(e["path"])
    assert e["size"] == size and e["offset"] == off
    assert e["old_hex"] == "ffffffff01000000"
    assert e["new_hex"] == struct.pack("<II", num, 1000).hex()
    assert e["old_value"] == 4294967295.0
    assert e["new_value"] == pytest.approx(num / 1000)
    assert e["lens"] == "XCD 55V"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", e["timestamp"])
    assert e["run_id"] in log.name


def test_log_line_is_durable_before_the_file_is_modified(tool, tmp_path, monkeypatch):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)
    original = p.read_bytes()
    seen = {}
    real_append = tool.UndoLog.append

    def spy(self, entry):
        seen["file_before_append"] = p.read_bytes()
        real_append(self, entry)
        seen["file_after_append"] = p.read_bytes()
        seen["log_text"] = Path(self.path).read_text()

    monkeypatch.setattr(tool.UndoLog, "append", spy)
    synced = []
    real_fsync = os.fsync
    monkeypatch.setattr(tool.os, "fsync", lambda fd: (synced.append(fd), real_fsync(fd))[1])
    assert tool.main([str(shoot)]) == 0
    assert seen["file_before_append"] == original
    assert seen["file_after_append"] == original            # still unmodified once the line is on disk
    assert json.loads(seen["log_text"])["old_hex"] == "ffffffff01000000"
    assert len(synced) >= 3                                 # log line, file write, and more
    assert p.read_bytes() != original


def test_no_log_when_nothing_changed_or_dry_run(tool, tmp_path):
    shoot = make_shoot(tmp_path)
    num, _ = want(tool, "XCD 55V", KNOT_F, KNOT_M)
    build_3fr(shoot / "a.3FR", subject_distance=(num, 1000), maker_f=KNOT_F, maker_m=KNOT_M)
    build_3fr(shoot / "b.3FR", subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)
    tool.main([str(shoot), "--dry-run"])
    assert logs_in(shoot) == []
    (shoot / "b.3FR").unlink()
    tool.main([str(shoot)])
    assert logs_in(shoot) == []


# ------------------------------------------------------------------ undo

def _two_changed(tool, tmp_path):
    shoot = make_shoot(tmp_path)
    (shoot / "sub").mkdir()
    a = build_3fr(shoot / "a.3FR", subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)
    b = build_3fr(shoot / "sub" / "b.3FR", subject_distance=(173, 100),
                  maker_f=KNOT_F, maker_m=KNOT_M, byte_order="MM")
    orig = {a: a.read_bytes(), b: b.read_bytes()}
    assert tool.main([str(shoot)]) == 0
    (log,) = logs_in(shoot)
    assert a.read_bytes() != orig[a] and b.read_bytes() != orig[b]
    return shoot, log, orig


def test_undo_restores_byte_identical(tool, tmp_path, capsys):
    shoot, log, orig = _two_changed(tool, tmp_path)
    capsys.readouterr()
    rc = tool.main(["undo", str(log)])
    out = capsys.readouterr().out
    assert rc == 0
    assert counts(out)["restored"] == 2
    for p, b in orig.items():
        assert p.read_bytes() == b


def test_undo_is_idempotent(tool, tmp_path, capsys):
    shoot, log, orig = _two_changed(tool, tmp_path)
    tool.main(["undo", str(log)])
    capsys.readouterr()
    rc = tool.main(["undo", str(log)])
    out = capsys.readouterr().out
    assert rc == 0
    assert counts(out)["already restored"] == 2 and counts(out)["restored"] == 0
    for p, b in orig.items():
        assert p.read_bytes() == b


def test_undo_skips_when_current_bytes_differ(tool, tmp_path, capsys):
    shoot, log, orig = _two_changed(tool, tmp_path)
    a = shoot / "a.3FR"
    off = tool.parse_file(a).sd_offset
    with open(a, "r+b") as fh:                      # someone changed it again afterwards
        fh.seek(off)
        fh.write(struct.pack("<II", 4242, 1000))
    edited = a.read_bytes()
    capsys.readouterr()
    rc = tool.main(["undo", str(log)])
    out = capsys.readouterr().out
    assert rc == 1
    assert counts(out)["skipped"] == 1 and counts(out)["restored"] == 1
    assert a.read_bytes() == edited                  # untouched
    assert (shoot / "sub" / "b.3FR").read_bytes() == orig[shoot / "sub" / "b.3FR"]


def test_undo_skips_when_size_differs(tool, tmp_path, capsys):
    shoot, log, orig = _two_changed(tool, tmp_path)
    a = shoot / "a.3FR"
    with open(a, "ab") as fh:
        fh.write(b"\x00")
    grown = a.read_bytes()
    rc = tool.main(["undo", str(log)])
    out = capsys.readouterr().out
    assert rc == 1 and "size" in out
    assert a.read_bytes() == grown


def test_undo_reports_missing_file_and_bad_lines(tool, tmp_path, capsys):
    shoot, log, orig = _two_changed(tool, tmp_path)
    (shoot / "a.3FR").unlink()
    with open(log, "a") as fh:
        fh.write("not json\n")
    capsys.readouterr()
    rc = tool.main(["undo", str(log)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "missing" in out
    assert counts(out)["restored"] == 1
    assert (shoot / "sub" / "b.3FR").read_bytes() == orig[shoot / "sub" / "b.3FR"]


def test_undo_missing_log_exits_2(tool, tmp_path, capsys):
    assert tool.main(["undo", str(tmp_path / "nope.jsonl")]) == 2
    assert "error" in capsys.readouterr().err.lower()


def test_undo_writes_no_log_of_its_own(tool, tmp_path):
    shoot, log, _ = _two_changed(tool, tmp_path)
    tool.main(["undo", str(log)])
    assert logs_in(shoot) == [log]
