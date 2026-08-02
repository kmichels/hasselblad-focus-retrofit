import os

import pytest
from fixtures import build_3fr


def test_reads_maker_fields_and_strings(tool, tmp_path):
    p = build_3fr(tmp_path / "t.3FR", maker_f=89.48658, maker_m=0.00112,
                  lens_model="XCD 90V", software="1.2.7.16")
    info = tool.parse_file(p)
    assert info.maker_f == 89.48658
    assert info.maker_m == 0.00112
    assert info.lens_model == "XCD 90V"
    assert info.software == "1.2.7.16"
    assert info.subject_distance is None


def test_reads_existing_subject_distance(tool, tmp_path):
    p = build_3fr(tmp_path / "t.3FR", subject_distance=(500, 1000))
    assert tool.parse_file(p).subject_distance == 0.5


def test_missing_maker_fields(tool, tmp_path):
    p = build_3fr(tmp_path / "t.3FR", include_maker_fields=False)
    info = tool.parse_file(p)
    assert info.maker_f is None and info.maker_m is None


def test_big_endian_parses(tool, tmp_path):
    p = build_3fr(tmp_path / "t.3FR", byte_order="MM")
    assert tool.parse_file(p).byte_order == "MM"


def test_not_a_tiff_raises(tool, tmp_path):
    p = tmp_path / "junk.3FR"
    p.write_bytes(b"NOPE" + b"\x00" * 100)
    with pytest.raises(tool.ParseError):
        tool.parse_file(p)


def test_truncated_offset_raises_with_offset_in_message(tool, tmp_path):
    p = build_3fr(tmp_path / "t.3FR")
    data = bytearray(p.read_bytes())
    # corrupt IFD0 pointer to point far beyond EOF
    data[4:8] = (2 ** 31).to_bytes(4, "little")
    p.write_bytes(bytes(data))
    with pytest.raises(tool.ParseError, match="0x80000000|2147483648"):
        tool.parse_file(p)


def test_real_file_matches_known_values(tool):
    sample = os.environ.get("HB_REAL_3FR")
    if not sample:
        pytest.skip("HB_REAL_3FR not set")
    info = tool.parse_file(sample)
    assert info.model == "X2D II 100C"
    assert info.maker_f and 20 < info.maker_f < 200
    assert info.maker_m is not None and 0 <= info.maker_m < 2
