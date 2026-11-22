"""Frames focused beyond the calibrated range get an ESTIMATE written: the
thin-lens distance times the calibration ratio at the far end of the range,
held constant. The near side, uncalibrated lenses, converter frames and
infinity keep their behaviour."""
import hashlib
import json
import struct

import pytest
from fixtures import build_3fr
from folder_helpers import INF, KNOT_F, KNOT_M, counts, logs_in, make_shoot, sd_span

LABEL = "estimated in place, beyond calibration"
LABEL_COPY = "estimated and copied with tag added, beyond calibration"


def far_ratio(tool, lens):
    cal = tool.load_calibrations(tool.SHIPPED_CALIBRATION_DIR)[lens]
    return cal.points[0][1]


def estimate(tool, lens, f, m):
    return round(tool.thin_lens_m(f, m) * far_ratio(tool, lens) * 1000)


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


# 55V far end is m=0.01803; these are all beyond it
FAR = dict(maker_f=55.0, maker_m=0.004)


@pytest.mark.parametrize("stored", [
    INF, (173, 100), (7170, 1000), (3000, 1000), (0, 1), (5, 0),
])
def test_estimate_written_in_place_whatever_is_stored(tool, tmp_path, capsys, stored):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", subject_distance=stored, **FAR)
    before = p.read_bytes()
    lo, hi = sd_span(tool, p)
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    c = counts(out)
    num = estimate(tool, "XCD 55V", 55.0, 0.004)
    after = p.read_bytes()
    assert after[lo:hi] == struct.pack("<II", num, 1000)
    assert after[:lo] == before[:lo] and after[hi:] == before[hi:]
    assert c[LABEL] == 1 and c["rewritten in place"] == 0 and c["errors"] == 0
    assert "estimated, beyond calibration" in out.splitlines()[0]


def test_ratio_held_constant_beyond_the_far_end(tool, tmp_path):
    shoot = make_shoot(tmp_path)
    ms = (0.017, 0.004, 0.0009)
    for i, m in enumerate(ms):
        build_3fr(shoot / f"{i}.3FR", subject_distance=INF, maker_f=55.0, maker_m=m)
    assert tool.main([str(shoot)]) == 0
    r = far_ratio(tool, "XCD 55V")
    for i, m in enumerate(ms):
        d = tool.parse_file(shoot / f"{i}.3FR").subject_distance
        assert d == pytest.approx(tool.thin_lens_m(55.0, m) * r, abs=0.001)


def test_value_already_equal_is_unchanged_no_write(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    num = estimate(tool, "XCD 55V", 55.0, 0.004)
    p = build_3fr(shoot / "a.3FR", subject_distance=(num, 1000), **FAR)
    before = p.read_bytes()
    assert tool.main([str(shoot)]) == 0
    c = counts(capsys.readouterr().out)
    assert c["unchanged"] == 1 and c[LABEL] == 0 and c["rewritten in place"] == 0
    assert p.read_bytes() == before and logs_in(shoot) == []


def test_near_side_still_skipped(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", subject_distance=INF, maker_f=KNOT_F, maker_m=0.9)
    before = p.read_bytes()
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    c = counts(out)
    assert c["skipped, closer than calibrated range"] == 1 and c[LABEL] == 0
    assert p.read_bytes() == before and logs_in(shoot) == []


def test_uncalibrated_lens_and_converter_frames_stay_skipped(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    a = build_3fr(shoot / "nocal.3FR", subject_distance=INF, lens_model="XCD 38V", **FAR)
    b = build_3fr(shoot / "conv.3FR", subject_distance=INF, maker_f=120.0, maker_m=0.004)
    before = (a.read_bytes(), b.read_bytes())
    assert tool.main([str(shoot)]) == 0
    c = counts(capsys.readouterr().out)
    assert c["skipped, no calibration"] == 1
    assert c["skipped, focal length outside calibration (converter?)"] == 1
    assert c[LABEL] == 0
    assert (a.read_bytes(), b.read_bytes()) == before and logs_in(shoot) == []


def test_exact_infinity_unchanged_behaviour(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", subject_distance=(7170, 1000), maker_f=55.0, maker_m=0.0)
    assert tool.main([str(shoot)]) == 0
    c = counts(capsys.readouterr().out)
    assert c["rewritten in place"] == 1 and c[LABEL] == 0
    assert (tool.parse_file(p).sd_num, tool.parse_file(p).sd_den) == (0xFFFFFFFF, 1)


def test_beyond_a_kilometre_is_skipped_not_an_error(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", subject_distance=INF, maker_f=55.0, maker_m=1e-9)
    before = p.read_bytes()
    assert tool.main([str(shoot)]) == 0
    c = counts(capsys.readouterr().out)
    assert c["skipped, computed distance beyond 1 km"] == 1 and c["errors"] == 0
    assert p.read_bytes() == before


def test_dry_run_writes_nothing(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", subject_distance=INF, **FAR)
    before = p.read_bytes()
    assert tool.main(["--dry-run", str(shoot)]) == 0
    out = capsys.readouterr().out
    assert p.read_bytes() == before and logs_in(shoot) == []
    assert counts(out)["would estimate in place, beyond calibration"] == 1
    assert "estimated, beyond calibration" in out


def test_tag_absent_file_gets_estimated_copy(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", **FAR)
    before = p.read_bytes()
    assert tool.main([str(shoot)]) == 0
    out = capsys.readouterr().out
    c = counts(out)
    assert c[LABEL_COPY] == 1 and c["copied with tag added"] == 0
    assert p.read_bytes() == before
    got = tool.parse_file(shoot / "retrofitted" / "a.3FR")
    assert (got.sd_num, got.sd_den) == (estimate(tool, "XCD 55V", 55.0, 0.004), 1000)
    assert "estimated, beyond calibration" in out


def test_undo_round_trips_an_estimated_frame_byte_identically(tool, tmp_path, capsys):
    shoot = make_shoot(tmp_path)
    p = build_3fr(shoot / "a.3FR", subject_distance=(7170, 1000), **FAR)
    q = build_3fr(shoot / "b.3FR", subject_distance=INF, maker_f=KNOT_F, maker_m=KNOT_M)
    h0 = (sha(p), sha(q))
    assert tool.main([str(shoot)]) == 0
    capsys.readouterr()
    assert (sha(p), sha(q)) != h0
    (log,) = logs_in(shoot)
    entries = [json.loads(ln) for ln in log.read_text().splitlines()]
    est = [e for e in entries if e["new_kind"] == "estimate"]
    assert len(est) == 1 and est[0]["old_hex"] == struct.pack("<II", 7170, 1000).hex()
    assert est[0]["new_value"] == pytest.approx(estimate(tool, "XCD 55V", 55.0, 0.004) / 1000)
    assert tool.main(["undo", str(log)]) == 0
    capsys.readouterr()
    assert (sha(p), sha(q)) == h0


def test_inspect_says_estimate_and_gives_the_far_end(tool, tmp_path, capsys):
    p = build_3fr(tmp_path / "t.3FR", **FAR)
    assert tool.main(["inspect", str(p)]) == 0
    out = capsys.readouterr().out
    assert "estimate" in out and "no measured distance has checked" in out
    assert "far end of the calibration" in out and "0.01803" in out
    assert "would be written as an estimate" in out
    ratio = far_ratio(tool, "XCD 55V")
    assert f"{tool.thin_lens_m(55.0, 0.004) * ratio:.2f}" in out


def test_inspect_in_range_has_no_estimate_wording(tool, tmp_path, capsys):
    p = build_3fr(tmp_path / "t.3FR", maker_f=KNOT_F, maker_m=KNOT_M)
    assert tool.main(["inspect", str(p)]) == 0
    assert "beyond calibration" not in capsys.readouterr().out
