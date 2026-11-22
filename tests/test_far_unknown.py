"""A lens whose calibration carries `reliable_to_m` (the XCD 25V, 2.0 m): a
frame whose result would be at or beyond that distance, or beyond the far end
of the calibration, is left unchanged and counted as "far focus, distance
unknown". Nothing is written for it, not an estimate and not infinity. Frames
nearer than the cut, infinity frames and other lenses behave as before."""
import hashlib
import json

import pytest
from fixtures import build_3fr
from folder_helpers import INF, counts, logs_in, make_shoot

F25 = 25.72
LABEL = "far focus, distance unknown (XCD 25V beyond 2.0 m)"
LINE_END = "frames left unchanged"
STALE = ("far focus, distance unknown, stored distance well below the cut "
         "(XCD 25V beyond 2.0 m)")


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def far_line(out, label=LABEL):
    """The count N from '<label>: N frames left unchanged', or 0 if absent."""
    for ln in out.splitlines():
        s = ln.strip()
        if s.startswith(label + ":") and s.endswith(LINE_END):
            return int(s[len(label) + 1:].split()[0])
    return 0


def cal25(tool):
    return tool.load_calibrations(tool.SHIPPED_CALIBRATION_DIR)["XCD 25V"]


def test_shipped_25v_carries_the_cut_and_other_lenses_do_not(tool):
    cals = tool.load_calibrations(tool.SHIPPED_CALIBRATION_DIR)
    assert cals["XCD 25V"].reliable_to_m == 2.0
    for lens, cal in cals.items():
        if lens != "XCD 25V":
            assert cal.reliable_to_m is None


def test_reliable_to_m_must_be_a_positive_number(tool, tmp_path):
    doc = json.loads((tool.SHIPPED_CALIBRATION_DIR / "xcd-25v.json").read_text())
    for bad in (0, -1, "2", True):
        doc["reliable_to_m"] = bad
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(doc))
        with pytest.raises(ValueError):
            tool.Calibration.from_json(p)


def test_calibrated_result_beyond_the_cut_is_left_alone(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    cal = cal25(tool)
    m = 0.00328                      # inside the calibration, result above the cut
    assert cal.in_range(m) and cal.correct(m, tool.thin_lens_m(F25, m)) >= 2.0
    p = build_3fr(shoot / "a.3FR", subject_distance=(2060, 1000),
                  lens_model="XCD 25V", maker_f=F25, maker_m=m)
    before = p.read_bytes()
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    assert far_line(out) == 1
    assert "a.3FR  left unchanged: far focus, distance unknown" in out
    c = counts(out)
    assert c["rewritten in place"] == 0 and c["unchanged"] == 0 and c["errors"] == 0
    assert p.read_bytes() == before and logs_in(shoot) == []


def test_frame_beyond_the_calibration_is_not_estimated(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    m = 0.00265
    assert m < cal25(tool).m_min
    p = build_3fr(shoot / "a.3FR", subject_distance=INF,
                  lens_model="XCD 25V", maker_f=F25, maker_m=m)
    before = p.read_bytes()
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    c = counts(out)
    assert far_line(out) == 1
    assert c["estimated in place, beyond calibration"] == 0
    assert "estimated, beyond calibration" not in out
    assert p.read_bytes() == before and logs_in(shoot) == []


def test_tag_absent_far_frame_gets_no_copy(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", lens_model="XCD 25V", maker_f=F25, maker_m=0.00328)
    before = p.read_bytes()
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    assert far_line(out) == 1
    assert p.read_bytes() == before and not (shoot / "retrofitted").exists()


def test_near_25v_frame_is_still_written(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    m = 0.02301                      # a wall about 1.2 m away
    p = build_3fr(shoot / "a.3FR", subject_distance=INF,
                  lens_model="XCD 25V", maker_f=F25, maker_m=m)
    want = cal25(tool).correct(m, tool.thin_lens_m(F25, m))
    assert want < 2.0
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    assert far_line(out) == 0 and counts(out)["rewritten in place"] == 1
    got = tool.parse_file(p)
    assert (got.sd_num, got.sd_den) == (round(want * 1000), 1000)


def test_frame_just_under_the_cut_is_written(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    cal = cal25(tool)
    m = 0.0045
    assert cal.correct(m, tool.thin_lens_m(F25, m)) < 2.0
    p = build_3fr(shoot / "a.3FR", subject_distance=INF,
                  lens_model="XCD 25V", maker_f=F25, maker_m=m)
    assert tool.main([str(shoot)]) == 0
    assert far_line(capsys.readouterr().out) == 0
    assert tool.parse_file(p).sd_num != tool.SENTINEL_NUM


def test_result_exactly_at_the_cut_is_skipped(tool):
    cal = tool.Calibration("XCD 25V", [(0.003, 1.0), (0.02, 1.0)], (25.0, 26.0), 2.0,
                           reliable_to_m=2.0)
    info = type("I", (), dict(maker_f=25.72, maker_m=0.01, focal_length=None,
                              lens_model="XCD 25V"))()
    # make the calibrated result land exactly on the cut
    d = tool.thin_lens_m(25.72, 0.01)
    cal.points = [(0.003, 2.0 / d), (0.02, 2.0 / d)]
    status, detail, dist = tool.maker_note_distance(info, {"XCD 25V": cal})
    assert status == "far-unknown" and dist is None and "2.0" in detail


def test_infinity_frame_keeps_its_behaviour(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", subject_distance=(2100, 1000),
                  lens_model="XCD 25V", maker_f=F25, maker_m=0.0)
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    assert far_line(out) == 0 and counts(out)["rewritten in place"] == 1
    got = tool.parse_file(p)
    assert (got.sd_num, got.sd_den) == (tool.SENTINEL_NUM, 1)


def test_other_lens_beyond_its_calibration_is_still_estimated(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", subject_distance=INF, maker_f=55.0, maker_m=0.004)
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    c = counts(out)
    assert far_line(out) == 0 and c["estimated in place, beyond calibration"] == 1
    assert tool.parse_file(p).sd_num != tool.SENTINEL_NUM


def test_dry_run_reports_the_same_label_and_touches_nothing(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", subject_distance=(2060, 1000),
                  lens_model="XCD 25V", maker_f=F25, maker_m=0.00328)
    before = p.read_bytes()
    assert tool.main(["--dry-run", str(shoot)]) == 0
    out = capsys.readouterr().out
    assert far_line(out) == 1 and "left unchanged: far focus, distance unknown" in out
    assert p.read_bytes() == before and logs_in(shoot) == []


def test_stale_near_value_is_flagged_on_its_own_line(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    stale = build_3fr(shoot / "stale.3FR", subject_distance=(370, 1000),
                      lens_model="XCD 25V", maker_f=F25, maker_m=0.00328)
    plain = build_3fr(shoot / "plain.3FR", subject_distance=(2060, 1000),
                      lens_model="XCD 25V", maker_f=F25, maker_m=0.00328)
    h = (sha(stale), sha(plain))
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    assert far_line(out) == 1 and far_line(out, STALE) == 1
    line = [ln for ln in out.splitlines() if ln.startswith("stale.3FR")][0]
    assert "stored 0.370 m" in line and "left unchanged" in line
    assert (sha(stale), sha(plain)) == h and logs_in(shoot) == []


def test_summary_counts_add_up(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    build_3fr(shoot / "far1.3FR", subject_distance=(2060, 1000),
              lens_model="XCD 25V", maker_f=F25, maker_m=0.00328)
    build_3fr(shoot / "far2.3FR", subject_distance=INF,
              lens_model="XCD 25V", maker_f=F25, maker_m=0.00265)
    build_3fr(shoot / "stale.3FR", subject_distance=(370, 1000),
              lens_model="XCD 25V", maker_f=F25, maker_m=0.00265)
    build_3fr(shoot / "near.3FR", subject_distance=INF,
              lens_model="XCD 25V", maker_f=F25, maker_m=0.02301)
    build_3fr(shoot / "inf.3FR", subject_distance=(2100, 1000),
              lens_model="XCD 25V", maker_f=F25, maker_m=0.0)
    build_3fr(shoot / "other.3FR", subject_distance=INF, maker_f=55.0, maker_m=0.004)
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    c = counts(out)
    found = c["files found"]
    far, stale = far_line(out), far_line(out, STALE)
    assert (far, stale) == (2, 1)
    rows = sum(v for k, v in c.items()
               if k not in ("files found", "errors") and not k.startswith("undo"))
    assert found == 6 and rows + far + stale == found


def test_undo_unaffected_by_skipped_far_frames(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    far = build_3fr(shoot / "far.3FR", subject_distance=(2060, 1000),
                    lens_model="XCD 25V", maker_f=F25, maker_m=0.00328)
    near = build_3fr(shoot / "near.3FR", subject_distance=INF,
                     lens_model="XCD 25V", maker_f=F25, maker_m=0.02301)
    h0 = (sha(far), sha(near))
    assert tool.main([str(shoot)]) == 0
    capsys.readouterr()
    (log,) = logs_in(shoot)
    assert len(log.read_text().splitlines()) == 1
    assert sha(far) == h0[0] and sha(near) != h0[1]
    assert tool.main(["undo", str(log)]) == 0
    assert (sha(far), sha(near)) == h0


def test_inspect_reports_far_focus_unknown(tool, tmp_path, capsys):
    p = build_3fr(tmp_path / "t.3FR", lens_model="XCD 25V", maker_f=F25, maker_m=0.00328)
    assert tool.main(["inspect", str(p)]) == 0
    out = capsys.readouterr().out
    assert "far focus, distance unknown" in out and "left unchanged" in out
    assert "would be written as an estimate" not in out


def test_retrofit_command_does_not_copy_far_frames(tool, tmp_path, capsys):
    src = make_shoot(tmp_path, "src")
    build_3fr(src / "far.3FR", lens_model="XCD 25V", maker_f=F25, maker_m=0.00328)
    build_3fr(src / "near.3FR", lens_model="XCD 25V", maker_f=F25, maker_m=0.02301)
    assert tool.main(["retrofit", "--source", str(src), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "far.3FR" in out and "not written: far focus, distance unknown" in out
    assert not (src / "retrofitted" / "far.3FR").exists()
    assert (src / "retrofitted" / "near.3FR").exists()


def test_inspect_keeps_the_classify_verdict_detail(tool, tmp_path, capsys):
    p = build_3fr(tmp_path / "t.3FR", lens_model="XCD 25V", maker_f=F25, maker_m=0.00328)
    assert tool.main(["inspect", str(p)]) == 0
    assert "verdict: write" in capsys.readouterr().out
