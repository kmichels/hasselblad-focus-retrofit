import pytest
from fixtures import build_3fr


def make_folder(tmp_path):
    src = tmp_path / "shoot"
    src.mkdir()
    # lens_model override: the fixture default "XCD 55V" now has real calibration
    # data (Task 4), so these must use an uncalibrated lens to exercise the
    # UNCALIBRATED (raw formula) path this test is actually checking.
    build_3fr(src / "close.3FR", lens_model="XCD 38V", maker_f=52.38143, maker_m=0.08961)      # ~0.64 m raw
    build_3fr(src / "far.3FR", lens_model="XCD 38V", maker_f=89.48658, maker_m=0.00112)        # ~80 m
    build_3fr(src / "inf.3FR", maker_m=0.0)
    build_3fr(src / "tagged.3FR", subject_distance=(500, 1000))
    (src / "close.phos").write_text("<plist/>")
    return src


def test_dry_run_writes_nothing_and_reports(tool, tmp_path, capsys):
    src = make_folder(tmp_path)
    rc = tool.main(["retrofit", "--source", str(src)])
    out = capsys.readouterr().out
    assert rc == 0
    assert not (src / "retrofitted").exists()
    assert "close.3FR" in out and "UNCALIBRATED" in out
    assert "skip" in out  # tagged + infinity show reasons


def test_apply_writes_copies_and_originals_untouched(tool, tmp_path):
    src = make_folder(tmp_path)
    before = (src / "close.3FR").read_bytes()
    rc = tool.main(["retrofit", "--source", str(src), "--apply"])
    assert rc == 0
    dest = src / "retrofitted"
    assert (dest / "close.3FR").exists()
    assert (dest / "far.3FR").exists()
    assert not (dest / "inf.3FR").exists()
    assert not (dest / "tagged.3FR").exists()
    assert (src / "close.3FR").read_bytes() == before
    assert tool.parse_file(dest / "close.3FR").subject_distance == pytest.approx(0.637, abs=0.001)


def test_apply_is_idempotent(tool, tmp_path, capsys):
    src = make_folder(tmp_path)
    tool.main(["retrofit", "--source", str(src), "--apply"])
    first = (src / "retrofitted" / "close.3FR").read_bytes()
    rc = tool.main(["retrofit", "--source", str(src), "--apply"])
    assert rc == 0
    assert (src / "retrofitted" / "close.3FR").read_bytes() == first


def test_copy_sidecars_flag(tool, tmp_path):
    src = make_folder(tmp_path)
    tool.main(["retrofit", "--source", str(src), "--apply", "--copy-sidecars"])
    assert (src / "retrofitted" / "close.phos").exists()
    assert not (src / "retrofitted" / "far.phos").exists()


def test_custom_dest(tool, tmp_path):
    src = make_folder(tmp_path)
    dest = tmp_path / "elsewhere"
    tool.main(["retrofit", "--source", str(src), "--dest", str(dest), "--apply"])
    assert (dest / "close.3FR").exists()


def test_read_only_source_still_applies(tool, tmp_path):
    import os
    src = make_folder(tmp_path)
    os.chmod(src / "close.3FR", 0o444)
    rc = tool.main(["retrofit", "--source", str(src), "--apply"])
    assert rc == 0
    assert (src / "retrofitted" / "close.3FR").exists()


def test_calibrated_lens_uses_correction(tool, tmp_path, capsys):
    src = tmp_path / "shoot"
    src.mkdir()
    # ladder knot: m=0.08261 f=52.69814 -> camera 0.77 m exactly
    build_3fr(src / "knot.3FR", lens_model="XCD 55V", maker_f=52.69814, maker_m=0.08261)
    rc = tool.main(["retrofit", "--source", str(src), "--apply"])
    assert rc == 0
    assert tool.parse_file(src / "retrofitted" / "knot.3FR").subject_distance == pytest.approx(0.77, abs=0.001)
