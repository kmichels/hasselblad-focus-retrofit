from fixtures import build_3fr


def _info(tool, tmp_path, **kw):
    return tool.parse_file(build_3fr(tmp_path / "t.3FR", **kw))


def test_write_for_normal_old_file(tool, tmp_path):
    action, _ = tool.classify(_info(tool, tmp_path))
    assert action == "write"


def test_skip_when_tag_present(tool, tmp_path):
    action, _ = tool.classify(_info(tool, tmp_path, subject_distance=(500, 1000)))
    assert action == "skip-present"


def test_skip_when_tag_present_even_sentinel_zero(tool, tmp_path):
    action, _ = tool.classify(_info(tool, tmp_path, subject_distance=(0, 1000)))
    assert action == "skip-present"


def test_skip_without_maker_fields(tool, tmp_path):
    action, _ = tool.classify(_info(tool, tmp_path, include_maker_fields=False))
    assert action == "skip-nofields"


def test_skip_infinity(tool, tmp_path):
    action, _ = tool.classify(_info(tool, tmp_path, maker_m=0.0))
    assert action == "skip-infinity"


def test_skip_insane_focal(tool, tmp_path):
    # nominal 55 mm but maker_f claims 500 mm
    action, detail = tool.classify(_info(tool, tmp_path, maker_f=500.0))
    assert action == "skip-insane"
    assert "500" in detail


def test_skip_insane_magnification(tool, tmp_path):
    action, _ = tool.classify(_info(tool, tmp_path, maker_m=5.0))
    assert action == "skip-insane"


def test_skip_effectively_infinite_distance(tool, tmp_path):
    # m tiny but positive: computed distance would overflow the uint32
    # RATIONAL numerator (review finding). Must be treated as infinity.
    action, _ = tool.classify(_info(tool, tmp_path, maker_m=1e-9))
    assert action == "skip-infinity"
