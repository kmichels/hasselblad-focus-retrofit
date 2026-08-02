import pytest

LADDER = [  # (m, f, camera_m) from calibration/xcd-55v.json
    (0.15308, 49.64184, 0.44), (0.13196, 50.52679, 0.51),
    (0.10531, 51.68175, 0.62), (0.08261, 52.69814, 0.77),
    (0.05659, 53.8988, 1.10), (0.04075, 54.64756, 1.48),
    (0.0265, 55.33241, 2.14), (0.02079, 55.61001, 2.60),
    (0.01803, 55.74468, 2.91),
]


def test_thin_lens_matches_known_case(tool):
    assert tool.thin_lens_m(89.48658, 0.00112) == pytest.approx(79.988, abs=0.001)


def test_calibration_recovers_ladder_points(tool):
    cal = tool.load_calibrations("calibration")["XCD 55V"]
    for m, f, camera in LADDER:
        d = cal.correct(m, tool.thin_lens_m(f, m))
        assert d == pytest.approx(camera, rel=0.001)  # exact at the knots


def test_interpolation_between_points_is_sane(tool):
    cal = tool.load_calibrations("calibration")["XCD 55V"]
    # midpoint between the 0.62 m and 0.77 m knots: result must lie between them
    m_mid = (0.10531 + 0.08261) / 2
    f_mid = (51.68175 + 52.69814) / 2
    d = cal.correct(m_mid, tool.thin_lens_m(f_mid, m_mid))
    assert 0.62 < d < 0.77


def test_clamps_beyond_calibrated_range(tool):
    cal = tool.load_calibrations("calibration")["XCD 55V"]
    # far beyond the ladder (m below smallest knot): ratio must equal the end knot's ratio
    end_ratio = 2.91 / tool.thin_lens_m(55.74468, 0.01803)
    d = cal.correct(0.001, 100.0)
    assert d == pytest.approx(100.0 * end_ratio, rel=1e-6)
