import json

import pytest
from fixtures import build_3fr

LADDER = [
    (0.15308, 49.64184, 0.44), (0.13196, 50.52679, 0.51),
    (0.10531, 51.68175, 0.62), (0.08261, 52.69814, 0.77),
    (0.05659, 53.8988, 1.10), (0.04075, 54.64756, 1.48),
    (0.0265, 55.33241, 2.14), (0.02079, 55.61001, 2.60),
    (0.01803, 55.74468, 2.91),
]


def make_ladder(tmp_path, points=LADDER):
    src = tmp_path / "ladder"
    src.mkdir()
    for i, (m, f, dist) in enumerate(points):
        build_3fr(src / f"L{i:02d}.3FR", software="1.3.16.1", maker_f=f, maker_m=m,
                  subject_distance=(int(dist * 1000), 1000))
    return src


def test_derives_full_ladder(tool, tmp_path):
    doc, warnings = tool.derive_calibration(make_ladder(tmp_path))
    assert doc["lens_model"] == "XCD 55V"
    assert len(doc["points"]) == 9
    assert warnings == []


def test_rejects_sentinel_and_untagged_frames(tool, tmp_path):
    src = make_ladder(tmp_path)
    build_3fr(src / "sentinel.3FR", software="1.3.16.1", subject_distance=(4294967295, 1))
    build_3fr(src / "old.3FR", software="1.2.7.16")
    doc, _ = tool.derive_calibration(src)
    assert len(doc["points"]) == 9


def test_mixed_lens_folder_warns(tool, tmp_path):
    src = make_ladder(tmp_path)
    for i, (m, f, dist) in enumerate(LADDER[:6]):
        build_3fr(src / f"other{i}.3FR", software="1.3.16.1", lens_model="XCD 90V",
                  maker_f=f, maker_m=m, subject_distance=(int(dist * 1000), 1000))
    doc, warnings = tool.derive_calibration(src)
    assert doc["lens_model"] == "XCD 55V"  # sorted order: L*.3FR parse first
    assert any("XCD 90V" in w for w in warnings)


def test_too_few_frames_raises(tool, tmp_path):
    src = make_ladder(tmp_path, LADDER[:4])
    with pytest.raises(tool.CalibrationError):
        tool.derive_calibration(src)


def test_too_few_frames_for_first_lens_raises(tool, tmp_path):
    # First-sorted lens (by filename) has only 3 usable frames; a second lens
    # later in sort order has 5. Total usable frames across both is 8 (>= 5),
    # but the per-lens count for the lens actually being calibrated is 3 and
    # must still raise, not silently build a 3-point calibration.
    src = tmp_path / "ladder"
    src.mkdir()
    for i, (m, f, dist) in enumerate(LADDER[:3]):
        build_3fr(src / f"A{i:02d}.3FR", software="1.3.16.1", lens_model="XCD 38V",
                  maker_f=f, maker_m=m, subject_distance=(int(dist * 1000), 1000))
    for i, (m, f, dist) in enumerate(LADDER[3:8]):
        build_3fr(src / f"Z{i:02d}.3FR", software="1.3.16.1", lens_model="XCD 90V",
                  maker_f=f, maker_m=m, subject_distance=(int(dist * 1000), 1000))
    with pytest.raises(tool.CalibrationError):
        tool.derive_calibration(src)


def test_warns_on_short_ladder(tool, tmp_path):
    # only the far half: min distance 1.10 m (> 0.7), span 2.91/1.10 < 3x
    doc, warnings = tool.derive_calibration(make_ladder(tmp_path, LADDER[4:]))
    assert len(warnings) == 2


def test_cli_writes_json(tool, tmp_path, capsys, monkeypatch):
    src = make_ladder(tmp_path)
    monkeypatch.chdir(tmp_path)
    rc = tool.main(["calibrate", "--source", str(src)])
    assert rc == 0
    doc = json.loads((tmp_path / "xcd-55v.json").read_text())
    assert doc["provenance"]["frames"] == 9
    assert "residual" in capsys.readouterr().out.lower()


def test_cli_sanitizes_traversal_lens_name(tool, tmp_path, monkeypatch):
    src = tmp_path / "ladder"
    src.mkdir()
    evil_lens = "..\\..\\XCD 55V/../evil"
    for i, (m, f, dist) in enumerate(LADDER):
        build_3fr(src / f"L{i:02d}.3FR", software="1.3.16.1", maker_f=f, maker_m=m,
                  subject_distance=(int(dist * 1000), 1000), lens_model=evil_lens)
    monkeypatch.chdir(tmp_path)
    rc = tool.main(["calibrate", "--source", str(src)])
    assert rc == 0

    written = [p for p in tmp_path.iterdir() if p.is_file() and p.suffix == ".json"]
    assert len(written) == 1
    out_path = written[0]
    assert "\\" not in out_path.name
    assert "/" not in out_path.name
    assert ".." not in out_path.name
    # nothing was written outside tmp_path
    assert out_path.parent == tmp_path


def test_cli_refuses_to_overwrite_default_output(tool, tmp_path, monkeypatch):
    src = make_ladder(tmp_path)
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "xcd-55v.json"
    target.write_text("PRE-EXISTING CONTENT\n")
    rc = tool.main(["calibrate", "--source", str(src)])
    assert rc == 1
    assert target.read_text() == "PRE-EXISTING CONTENT\n"
