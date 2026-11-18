"""Folder mode: the maker note always wins. Files with a SubjectDistance tag
are rewritten in place (8 bytes); files without get a copy."""
import json
import os
import re
import struct
from pathlib import Path

import pytest
from fixtures import build_3fr
from folder_helpers import INF, KNOT_F, KNOT_M, counts, logs_in, make_shoot, sd_span, want


# ------------------------------------------------------------- dispatch

def test_bare_path_runs_folder_mode(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    build_3fr(shoot / "a.3FR", subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)
    rc = tool.main([str(shoot)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "a.3FR" in out and "rewritten" in out
    assert tool.parse_file(shoot / "a.3FR").subject_distance == pytest.approx(0.77, abs=0.001)


def test_dry_run_flag_before_or_after_path(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)
    before = p.read_bytes()
    assert tool.main(["--dry-run", str(shoot)]) == 0
    assert tool.main([str(shoot), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "would rewrite" in out and "DRY RUN" in out
    assert p.read_bytes() == before
    assert logs_in(shoot) == []
    assert not (shoot / "retrofitted").exists()


def test_dry_run_would_copy_tag_absent_files(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    build_3fr(shoot / "old.3FR", maker_f=KNOT_F, maker_m=KNOT_M)
    assert tool.main([str(shoot), "--dry-run"]) == 0
    assert "would copy" in capsys.readouterr().out
    assert not (shoot / "retrofitted").exists()


def test_missing_folder_exits_2(tool, tmp_path, capsys):
    rc = tool.main([str(tmp_path / "nope")])
    assert rc == 2
    assert "not a folder" in capsys.readouterr().err


def test_subcommands_still_dispatch(tool, tmp_path, capsys):
    p = build_3fr(tmp_path / "a.3FR", subject_distance=(500, 1000))
    assert tool.main(["inspect", str(p)]) == 0
    assert "SubjectDistance in file" in capsys.readouterr().out
    shoot = make_shoot(tmp_path)
    assert tool.main(["retrofit", "--source", str(shoot)]) == 0


def test_no_args_still_prints_help_and_exits_2(tool, capsys):
    assert tool.main([]) == 2
    err = capsys.readouterr().err
    assert "undo" in err and "retrofit" in err


def test_empty_folder_is_not_an_error(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    assert tool.main([str(shoot)]) == 0
    assert "no 3FR files found" in capsys.readouterr().out


# ------------------------------------------------------------------ walk

def test_recursion_and_extension_case(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    (shoot / "day1" / "card2").mkdir(parents=True)
    kw = dict(subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)
    build_3fr(shoot / "top.3FR", **kw)
    build_3fr(shoot / "day1" / "lower.3fr", **kw)
    build_3fr(shoot / "day1" / "card2" / "Mixed.3Fr", **kw)
    (shoot / "day1" / "notes.txt").write_text("x")
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    assert counts(out)["rewritten in place"] == 3
    assert os.path.join("day1", "card2", "Mixed.3Fr") in out


def test_skips_dot_dirs_output_dir_symlinks_and_appledouble(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    kw = dict(subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)
    (shoot / ".sync" / "Archive").mkdir(parents=True)
    (shoot / "retrofitted").mkdir()
    build_3fr(shoot / ".sync" / "Archive" / "hidden.3FR", **kw)
    build_3fr(shoot / "retrofitted" / "out.3FR", **kw)
    (shoot / "._ghost.3FR").write_bytes(b"\x00\x05\x16\x07junk")
    outside = tmp_path / "outside"
    outside.mkdir()
    ext = build_3fr(outside / "ext.3FR", **kw)
    ext_before = ext.read_bytes()
    os.symlink(outside, shoot / "linkdir")           # symlinked directory
    os.symlink(ext, shoot / "linkfile.3FR")           # symlinked file
    build_3fr(shoot / "real.3FR", **kw)
    hidden_before = (shoot / ".sync" / "Archive" / "hidden.3FR").read_bytes()
    out_before = (shoot / "retrofitted" / "out.3FR").read_bytes()

    rc = tool.main([str(shoot)])
    out = capsys.readouterr().out
    assert rc == 0
    c = counts(out)
    assert c["rewritten in place"] == 1
    assert c["skipped, symlink"] == 1
    assert c["errors"] == 0
    assert ext.read_bytes() == ext_before
    assert (shoot / ".sync" / "Archive" / "hidden.3FR").read_bytes() == hidden_before
    assert (shoot / "retrofitted" / "out.3FR").read_bytes() == out_before
    assert "ghost" not in out and "hidden" not in out and "out.3FR" not in out


# ----------------------------------------------------------- skip reasons

def test_each_skip_reason_counted_and_file_untouched(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    ok = dict(subject_distance=INF)
    files = {
        "nofields.3FR": dict(include_maker_fields=False, **ok),
        "zero_m.3FR": dict(maker_m=0.0, **ok),
        "zero_f.3FR": dict(maker_f=0.0, maker_m=KNOT_M, **ok),
        "bad_f.3FR": dict(maker_f=500.0, maker_m=KNOT_M, **ok),
        "nocal.3FR": dict(lens_model="XCD 38V", maker_f=KNOT_F, maker_m=KNOT_M, **ok),
        "far.3FR": dict(maker_f=55.0, maker_m=0.001, **ok),
        "near.3FR": dict(maker_f=KNOT_F, maker_m=0.9, **ok),
    }
    before = {}
    for name, kw in files.items():
        build_3fr(shoot / name, **kw)
        before[name] = (shoot / name).read_bytes()
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    c = counts(out)
    assert c["skipped, no focus data"] == 4
    assert c["skipped, no calibration"] == 1
    assert c["skipped, outside calibrated range"] == 2
    assert c["rewritten in place"] == 0 and c["errors"] == 0
    assert "no calibration for XCD 38V" in out
    for name, b in before.items():
        assert (shoot / name).read_bytes() == b
    assert logs_in(shoot) == [] and not (shoot / "retrofitted").exists()


def test_tag_absent_files_obey_the_same_skips(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    build_3fr(shoot / "far.3FR", maker_f=55.0, maker_m=0.001)
    build_3fr(shoot / "nocal.3FR", lens_model="XCD 38V", maker_f=KNOT_F, maker_m=KNOT_M)
    assert tool.main([str(shoot)]) == 0
    c = counts(capsys.readouterr().out)
    assert c["skipped, outside calibrated range"] == 1
    assert c["skipped, no calibration"] == 1
    assert c["copied with tag added"] == 0
    assert not (shoot / "retrofitted").exists()


# -------------------------------------------------------- in-place rewrite

@pytest.mark.parametrize("stored", [
    INF,                   # Infinity at close focus
    (173, 100),            # feet: 1.73 where metres would be ~0.5
    (3000, 1000),          # stale / unrelated value
    (790, 1000),           # plausible, differs from the maker-note value
    (0, 1),                # zero numerator
    (5, 0),                # zero denominator
])
def test_in_place_rewrite_replaces_any_stored_value(tool, tmp_path, capsys, stored):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", subject_distance=stored, maker_f=KNOT_F, maker_m=KNOT_M)
    before = p.read_bytes()
    lo, hi = sd_span(tool, p)
    rc = tool.main([str(shoot)])
    capsys.readouterr()
    assert rc == 0
    num, d = want(tool, "XCD 55V", KNOT_F, KNOT_M)
    info = tool.parse_file(p)
    assert (info.sd_num, info.sd_den) == (num, 1000)
    assert info.subject_distance == pytest.approx(0.77, abs=0.001)
    after = p.read_bytes()
    assert len(after) == len(before)
    assert after[:lo] == before[:lo] and after[hi:] == before[hi:]
    assert after[lo:hi] == struct.pack("<II", num, 1000)


def test_big_endian_rewrite(tool, tmp_path):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", byte_order="MM", subject_distance=INF,
                  maker_f=KNOT_F, maker_m=KNOT_M)
    lo, hi = sd_span(tool, p)
    assert tool.main([str(shoot)]) == 0
    assert p.read_bytes()[lo:hi] == struct.pack(">II", want(tool, "XCD 55V", KNOT_F, KNOT_M)[0], 1000)


def test_mtime_is_not_touched_back(tool, tmp_path):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)
    os.utime(p, (1_000_000_000, 1_000_000_000))
    assert tool.main([str(shoot)]) == 0
    assert p.stat().st_mtime > 1_000_000_000


def test_plausible_but_different_value_is_replaced(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    build_3fr(shoot / "a.3FR", subject_distance=(790, 1000), maker_f=KNOT_F, maker_m=KNOT_M)
    assert tool.main([str(shoot)]) == 0
    assert "0.790" in capsys.readouterr().out
    assert tool.parse_file(shoot / "a.3FR").subject_distance == pytest.approx(0.77, abs=0.001)


def test_second_run_is_a_no_op(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    (shoot / "sub").mkdir()
    build_3fr(shoot / "a.3FR", subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)
    build_3fr(shoot / "sub" / "b.3FR", subject_distance=(173, 100), maker_f=KNOT_F, maker_m=KNOT_M)
    build_3fr(shoot / "sub" / "c.3FR", maker_f=KNOT_F, maker_m=KNOT_M)
    assert tool.main([str(shoot)]) == 0
    capsys.readouterr()
    snap = {p: p.read_bytes() for p in shoot.rglob("*") if p.is_file() and p.suffix != ".jsonl"}
    n_logs = len(logs_in(shoot))
    mtimes = {p: p.stat().st_mtime_ns for p in snap}
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    c = counts(out)
    assert c["rewritten in place"] == 0
    assert c["unchanged"] == 2
    assert c["output already exists"] == 1
    assert len(logs_in(shoot)) == n_logs
    assert {p: p.read_bytes() for p in snap} == snap
    assert {p: p.stat().st_mtime_ns for p in snap} == mtimes
    assert "undo log: none" in out


def test_equal_value_with_other_denominator_is_unchanged(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    num, _ = want(tool, "XCD 55V", KNOT_F, KNOT_M)       # 770 / 1000
    p = build_3fr(shoot / "a.3FR", subject_distance=(num * 2, 2000),
                  maker_f=KNOT_F, maker_m=KNOT_M)
    before = p.read_bytes()
    assert tool.main([str(shoot)]) == 0
    assert counts(capsys.readouterr().out)["unchanged"] == 1
    assert p.read_bytes() == before


# ----------------------------------------------------- verification paths

def _mutate_after_first_parse(tool, monkeypatch, target_name, mutate):
    real = tool.parse_file
    state = {"done": False}

    def parse(path):
        info = real(path)
        if Path(path).name == target_name and not state["done"]:
            state["done"] = True
            mutate(Path(path), info)
        return info

    monkeypatch.setattr(tool, "parse_file", parse)


def test_pre_write_check_catches_changed_bytes(tool, tmp_path, monkeypatch, capsys):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)
    build_3fr(shoot / "b.3FR", subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)

    def mutate(path, info):
        with open(path, "r+b") as fh:
            fh.seek(info.sd_offset)
            fh.write(b"\x01\x02\x03\x04\x05\x06\x07\x08")

    _mutate_after_first_parse(tool, monkeypatch, "a.3FR", mutate)
    rc = tool.main([str(shoot)])
    out = capsys.readouterr().out
    assert rc == 1
    assert p.read_bytes().count(b"\x01\x02\x03\x04\x05\x06\x07\x08") == 1   # our tamper, nothing of ours
    assert "changed since it was read" in out
    c = counts(out)
    assert c["errors"] == 1 and c["rewritten in place"] == 1   # b.3FR still done
    entries = [json.loads(l) for log in logs_in(shoot) for l in log.read_text().splitlines()]
    assert [Path(e["path"]).name for e in entries] == ["b.3FR"]  # no log line for the aborted file


def test_pre_write_check_catches_size_change(tool, tmp_path, monkeypatch, capsys):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)

    def mutate(path, info):
        with open(path, "ab") as fh:
            fh.write(b"\x00")

    _mutate_after_first_parse(tool, monkeypatch, "a.3FR", mutate)
    rc = tool.main([str(shoot)])
    assert rc == 1
    assert "changed since it was read" in capsys.readouterr().out
    assert logs_in(shoot) == []


def test_post_write_mismatch_aborts_and_restores(tool, tmp_path, monkeypatch, capsys):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)
    original = p.read_bytes()
    real = tool._read_at
    calls = {"n": 0}

    def flaky(fh, off, n):
        calls["n"] += 1
        data = real(fh, off, n)
        return b"\x00" * n if calls["n"] == 2 else data     # 1 = pre-check, 2 = post-write

    monkeypatch.setattr(tool, "_read_at", flaky)
    rc = tool.main([str(shoot)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "verification failed" in out and "restored" in out
    assert p.read_bytes() == original
    assert counts(out)["errors"] == 1 and counts(out)["rewritten in place"] == 0


def test_post_write_size_change_is_an_error(tool, tmp_path, monkeypatch, capsys):
    shoot = make_shoot(tmp_path)
    build_3fr(shoot / "a.3FR", subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)
    real_fstat = os.fstat
    calls = {"n": 0}

    class FakeStat:
        def __init__(self, st):
            self.st_size = st.st_size + 1

    def fstat(fd):
        calls["n"] += 1
        st = real_fstat(fd)
        return FakeStat(st) if calls["n"] == 2 else st      # 1 = pre-check, 2 = post-write

    monkeypatch.setattr(tool.os, "fstat", fstat)
    assert tool.main([str(shoot)]) == 1
    assert "size" in capsys.readouterr().out


def test_read_only_file_is_an_error_not_a_chmod(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)
    os.chmod(p, 0o444)
    if os.access(p, os.W_OK):
        pytest.skip("running as a user that bypasses file permission bits (e.g. root)")
    before = p.read_bytes()
    try:
        assert tool.main([str(shoot)]) == 1
        assert p.read_bytes() == before
        assert (p.stat().st_mode & 0o777) == 0o444
        assert logs_in(shoot) == [] or logs_in(shoot)[0].read_text() == ""
    finally:
        os.chmod(p, 0o644)


def test_corrupt_file_exits_1_and_others_still_processed(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    (shoot / "junk.3FR").write_bytes(b"NOPE" + b"\x00" * 100)
    build_3fr(shoot / "good.3FR", subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)
    rc = tool.main([str(shoot)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "junk.3FR" in out and "ERROR" in out
    assert counts(out)["errors"] == 1 and counts(out)["rewritten in place"] == 1


def test_unexpected_subject_distance_type_is_refused(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)
    data = bytearray(p.read_bytes())
    info = tool.parse_file(p)
    # find the 0x9206 directory entry and change its type from RATIONAL(5) to SHORT(3)
    pos = data.find(struct.pack("<HH", 0x9206, 5))
    assert pos > 0
    data[pos + 2:pos + 4] = struct.pack("<H", 3)
    p.write_bytes(bytes(data))
    before = p.read_bytes()
    assert tool.main([str(shoot)]) == 1
    assert "ERROR" in capsys.readouterr().out
    assert p.read_bytes() == before


# ------------------------------------------------------------- copy path

def test_tag_absent_files_are_copied_with_subfolders(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    (shoot / "day1" / "cardA").mkdir(parents=True)
    old = build_3fr(shoot / "day1" / "cardA" / "old.3FR", maker_f=KNOT_F, maker_m=KNOT_M)
    top = build_3fr(shoot / "top.3FR", maker_f=KNOT_F, maker_m=KNOT_M)
    before = {old: old.read_bytes(), top: top.read_bytes()}
    mt = {p: p.stat().st_mtime_ns for p in before}
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    assert counts(out)["copied with tag added"] == 2
    out_old = shoot / "retrofitted" / "day1" / "cardA" / "old.3FR"
    assert out_old.exists() and (shoot / "retrofitted" / "top.3FR").exists()
    assert tool.parse_file(out_old).subject_distance == pytest.approx(0.77, abs=0.001)
    for p, b in before.items():
        assert p.read_bytes() == b and p.stat().st_mtime_ns == mt[p]
    assert logs_in(shoot) == []                     # nothing was changed in place


def test_copy_never_overwrites_existing_output(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    build_3fr(shoot / "old.3FR", maker_f=KNOT_F, maker_m=KNOT_M)
    (shoot / "retrofitted").mkdir()
    existing = shoot / "retrofitted" / "old.3FR"
    existing.write_bytes(b"precious")
    assert tool.main([str(shoot)]) == 0
    assert existing.read_bytes() == b"precious"
    assert counts(capsys.readouterr().out)["output already exists"] == 1


def test_mixed_folder_summary(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    build_3fr(shoot / "inf.3FR", subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)
    build_3fr(shoot / "feet.3FR", subject_distance=(173, 100), maker_f=KNOT_F, maker_m=KNOT_M)
    build_3fr(shoot / "old.3FR", maker_f=KNOT_F, maker_m=KNOT_M)
    build_3fr(shoot / "nocal.3FR", lens_model="XCD 38V", subject_distance=INF,
              maker_f=KNOT_F, maker_m=KNOT_M)
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    c = counts(out)
    assert c["rewritten in place"] == 2
    assert c["copied with tag added"] == 1
    assert c["skipped, no calibration"] == 1
    assert c["unchanged"] == 0 and c["errors"] == 0
    assert "run_id" in out and "undo log:" in out
