"""calibrate --measured: true distance from the mark folder name, not from SubjectDistance."""
import json

import pytest
from fixtures import build_3fr

F = 55.0
MARKS = [1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 15.0, 20.0]


def m_for(dist_m, f=F, ratio=1.0):
    # inverse of thin_lens_m: d_est = f (1 + 1/m) / 1000, with d_true = d_est * ratio
    d_est = dist_m / ratio
    return f / (1000.0 * d_est - f)


def make_measured(tmp_path, marks=MARKS, per_mark=3, lens="XCD 55V", sd=None,
                  jitter=(0.995, 1.0, 1.005), name="55V"):
    src = tmp_path / name
    src.mkdir()
    for d in marks:
        sub = src / f"{d:.3f}m"
        sub.mkdir()
        for i in range(per_mark):
            m = m_for(d) * jitter[i % len(jitter)]
            kw = {}
            if sd is not None:
                kw["subject_distance"] = sd(d)
            build_3fr(sub / f"F{i}.3FR", software="1.4.15.7", lens_model=lens,
                      maker_f=F, maker_m=m, **kw)
    return src


SENTINEL = (lambda d: (4294967295, 1))


def test_one_point_per_mark_with_measured_distance(tool, tmp_path):
    doc, warnings, _ = tool.derive_measured_calibration(make_measured(tmp_path, sd=SENTINEL))
    assert [p["camera_distance_m"] for p in doc["points"]] == MARKS[::-1]  # sorted by m ascending
    assert all(p["frames"] == 3 for p in doc["points"])
    assert doc["provenance"]["distance_source"] == "measured"
    # the middle frame of each mark is the one with jitter 1.0
    p20 = [p for p in doc["points"] if p["camera_distance_m"] == 20.0][0]
    assert p20["m"] == pytest.approx(m_for(20.0))
    assert warnings == []


def test_infinity_sentinel_frames_are_used(tool, tmp_path):
    # the camera writes Infinity past ~3 m; in measured mode that must not reject the frame
    doc, _, _ = tool.derive_measured_calibration(make_measured(tmp_path, sd=SENTINEL))
    assert len(doc["points"]) == 9


def test_folder_name_with_odd_reading_is_used_exactly(tool, tmp_path):
    marks = [1.0, 2.0, 3.0, 4.0, 9.987]
    doc, _, _ = tool.derive_measured_calibration(make_measured(tmp_path, marks=marks))
    assert 9.987 in [p["camera_distance_m"] for p in doc["points"]]


def test_unparseable_subfolder_is_an_error(tool, tmp_path):
    src = make_measured(tmp_path)
    (src / "ten metres").mkdir()
    with pytest.raises(tool.CalibrationError, match="ten metres"):
        tool.derive_measured_calibration(src)


def test_loose_3fr_at_top_level_is_an_error(tool, tmp_path):
    src = make_measured(tmp_path)
    build_3fr(src / "throwaway.3FR", software="1.4.15.7", maker_f=F, maker_m=0.05)
    with pytest.raises(tool.CalibrationError, match="throwaway"):
        tool.derive_measured_calibration(src)


def test_empty_mark_folder_is_an_error(tool, tmp_path):
    src = make_measured(tmp_path)
    (src / "12.000m").mkdir()
    with pytest.raises(tool.CalibrationError, match="12.000m"):
        tool.derive_measured_calibration(src)


def test_mixed_lenses_is_an_error(tool, tmp_path):
    src = make_measured(tmp_path)
    build_3fr(src / "1.000m" / "X.3FR", software="1.4.15.7", lens_model="XCD 90V",
              maker_f=F, maker_m=m_for(1.0))
    with pytest.raises(tool.CalibrationError, match="XCD 90V"):
        tool.derive_measured_calibration(src)


def test_too_few_marks(tool, tmp_path):
    src = make_measured(tmp_path, marks=[1.0, 2.0, 3.0, 4.0])
    with pytest.raises(tool.CalibrationError, match="at least 5"):
        tool.derive_measured_calibration(src)


def test_magnification_zero_at_a_mark_is_reported_not_called_foreign(tool, tmp_path):
    src = make_measured(tmp_path)
    for f in (src / "20.000m").iterdir():
        f.unlink()
    for i in range(3):
        build_3fr(src / "20.000m" / f"Z{i}.3FR", software="1.4.15.7", maker_f=F, maker_m=0.0)
    doc, warnings, _ = tool.derive_measured_calibration(src)
    assert 20.0 not in [p["camera_distance_m"] for p in doc["points"]]
    assert any("20.000m" in w and "magnification" in w for w in warnings)
    assert not any("X2D II" in w for w in warnings)


def test_non_monotonic_marks_raise_with_resolution_message(tool, tmp_path):
    # 15 m and 20 m frames share one magnification: the lens can't tell them apart
    src = make_measured(tmp_path, jitter=(1.0,), per_mark=1)
    for f in (src / "20.000m").iterdir():
        f.unlink()
    build_3fr(src / "20.000m" / "S.3FR", software="1.4.15.7", maker_f=F, maker_m=m_for(15.0))
    with pytest.raises(tool.CalibrationError, match="cannot separate"):
        tool.derive_measured_calibration(src)


def test_large_spread_within_a_mark_warns(tool, tmp_path):
    doc, warnings, _ = tool.derive_measured_calibration(
        make_measured(tmp_path, jitter=(0.8, 1.0, 1.25)))
    assert len(doc["points"]) == 9
    assert any("spread" in w for w in warnings)


def test_misfiled_frame_is_named(tool, tmp_path):
    src = make_measured(tmp_path)
    # a frame focused at 2 m sitting in the 10 m folder
    build_3fr(src / "10.000m" / "WRONG.3FR", software="1.4.15.7", maker_f=F, maker_m=m_for(2.0))
    _, warnings, _ = tool.derive_measured_calibration(src)
    assert any("WRONG.3FR" in w for w in warnings)


def test_overlap_rows_compare_camera_value(tool, tmp_path):
    # camera writes a real value up to 3 m, Infinity beyond
    def sd(d):
        return (int(d * 1000), 1000) if d <= 3 else (4294967295, 1)
    _, _, rows = tool.derive_measured_calibration(make_measured(tmp_path, sd=sd))
    by = {r["measured_m"]: r for r in rows}
    assert by[2.0]["camera_m"] == pytest.approx(2.0)
    assert by[2.0]["camera_frames"] == 3
    assert by[10.0]["camera_m"] is None


def test_latched_distance_check_does_not_fire(tool, tmp_path):
    # 3 frames per mark share one distance with a spread of focus positions; the
    # camera-mode latch guard would reject this, measured mode must not
    doc, _, _ = tool.derive_measured_calibration(
        make_measured(tmp_path, jitter=(0.93, 1.0, 1.07)))
    assert len(doc["points"]) == 9


def test_loads_as_calibration_and_corrects(tool, tmp_path):
    doc, _, _ = tool.derive_measured_calibration(make_measured(tmp_path))
    p = tmp_path / "cal.json"
    p.write_text(json.dumps(doc))
    cal = tool.Calibration.from_json(p)
    assert cal.correct(m_for(10.0), tool.thin_lens_m(F, m_for(10.0))) == pytest.approx(10.0)


def test_cli_measured_writes_suffixed_file(tool, tmp_path, capsys, monkeypatch):
    src = make_measured(tmp_path, sd=SENTINEL)
    monkeypatch.chdir(tmp_path)
    rc = tool.main(["calibrate", "--source", str(src), "--measured"])
    assert rc == 0
    doc = json.loads((tmp_path / "xcd-55v-measured.json").read_text())
    assert doc["provenance"]["distance_source"] == "measured"
    out = capsys.readouterr().out
    assert "residual" in out.lower()
    assert "overlap" in out.lower()


def test_cli_measured_refuses_to_write_into_shipped_calibration_folder(tool, tmp_path, capsys):
    src = make_measured(tmp_path)
    shipped = tool.SHIPPED_CALIBRATION_DIR / "xcd-55v.json"
    before = shipped.read_bytes()
    rc = tool.main(["calibrate", "--source", str(src), "--measured", "--out", str(shipped)])
    assert rc == 1
    assert shipped.read_bytes() == before
    assert "merge" in capsys.readouterr().err.lower()


def test_default_mode_unchanged_on_mark_folders(tool, tmp_path, capsys):
    # without --measured a mark-folder layout has no top-level frames: same error as before
    src = make_measured(tmp_path, sd=SENTINEL)
    rc = tool.main(["calibrate", "--source", str(src)])
    assert rc == 1


def test_converter_frames_mixed_in_are_an_error(tool, tmp_path):
    # bare 135 frames sit near 130 mm; through the 1.7x converter the maker focal
    # length is ~220 mm. A ladder mixing them must not build a curve.
    src = make_measured(tmp_path)
    build_3fr(src / "4.000m" / "TC.3FR", software="1.4.15.7", maker_f=F * 1.7,
              maker_m=m_for(4.0, f=F * 1.7))
    with pytest.raises(tool.CalibrationError, match="converter"):
        tool.derive_measured_calibration(src)


def test_cli_measured_refuses_default_path_inside_shipped_folder(tool, tmp_path, capsys, monkeypatch):
    # run from inside calibration/ without --out: the default path lands there too
    src = make_measured(tmp_path)
    target = tool.SHIPPED_CALIBRATION_DIR / "xcd-55v-measured.json"
    assert not target.exists()
    monkeypatch.chdir(tool.SHIPPED_CALIBRATION_DIR)
    try:
        rc = tool.main(["calibrate", "--source", str(src), "--measured"])
        assert rc == 1
        assert not target.exists()
        assert "merge" in capsys.readouterr().err.lower()
    finally:
        if target.exists():
            target.unlink()


def test_overlap_shows_real_far_camera_values(tool, tmp_path):
    # firmware 1.4.15.7 writes real values past 3 m (and past 50 m is not special either)
    def sd(d):
        return (int(d * 1000 * 1.02), 1000) if d >= 6 else (4294967295, 1)
    _, _, rows = tool.derive_measured_calibration(make_measured(tmp_path, sd=sd))
    by = {r["measured_m"]: r for r in rows}
    assert by[8.0]["camera_m"] == pytest.approx(8.16)
    assert by[20.0]["camera_m"] == pytest.approx(20.4)
    assert by[4.0]["camera_m"] is None


def test_overlap_table_prints_percent_differences(tool, tmp_path, capsys):
    rows = [{"mark": "8.000m", "measured_m": 8.0, "camera_m": 8.4, "camera_frames": 3,
             "shipped_m": None, "shipped_status": "range"}]
    tool._print_overlap(rows)
    assert "+5.0%" in capsys.readouterr().out


def _shipped_55v(tool):
    import pathlib
    return json.loads((tool.SHIPPED_CALIBRATION_DIR / "xcd-55v.json").read_text())


def test_merge_shipped_keeps_near_points_and_adds_far_marks(tool, tmp_path):
    shipped = _shipped_55v(tool)
    far = max(p["camera_distance_m"] for p in shipped["points"])
    doc, _, _ = tool.derive_measured_calibration(make_measured(tmp_path))
    merged, added, set_aside = tool.merge_with_shipped(doc)
    assert all(d > far for d in added) and added
    assert set_aside and all(d not in added for d in set_aside)
    assert len(merged["points"]) == len(shipped["points"]) + len(added)
    assert all(q in merged["points"] for q in shipped["points"])
    ms = [q["m"] for q in merged["points"]]
    assert ms == sorted(ms)
    p = tmp_path / "m.json"
    p.write_text(json.dumps(merged))
    cal = tool.Calibration.from_json(p)
    assert cal.correct(m_for(10.0), tool.thin_lens_m(F, m_for(10.0))) == pytest.approx(10.0)


def test_merge_shipped_requires_measured_and_refuses_shipped_dir(tool, tmp_path, capsys):
    src = make_measured(tmp_path)
    assert tool.main(["calibrate", "--source", str(src), "--merge-shipped"]) == 1
    shipped = tool.SHIPPED_CALIBRATION_DIR / "xcd-55v.json"
    before = shipped.read_bytes()
    rc = tool.main(["calibrate", "--source", str(src), "--measured", "--merge-shipped",
                    "--out", str(shipped)])
    assert rc == 1 and shipped.read_bytes() == before


def test_cli_merge_shipped_writes_merged_file(tool, tmp_path, capsys, monkeypatch):
    src = make_measured(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert tool.main(["calibrate", "--source", str(src), "--measured", "--merge-shipped"]) == 0
    doc = json.loads((tmp_path / "xcd-55v-merged.json").read_text())
    assert doc["provenance"]["extended_with_measured"]
    assert "merged:" in capsys.readouterr().out
