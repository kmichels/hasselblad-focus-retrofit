import shutil
import struct

import pytest
from fixtures import build_3fr


def test_roundtrip_write_then_read(tool, tmp_path):
    src = build_3fr(tmp_path / "orig.3FR")
    copy = tmp_path / "copy.3FR"
    shutil.copy2(src, copy)
    info = tool.parse_file(copy)
    tool.write_subject_distance(copy, info, 0.637)
    assert tool.parse_file(copy).subject_distance == pytest.approx(0.637)


def test_only_pointer_changes_within_original_extent(tool, tmp_path):
    src = build_3fr(tmp_path / "orig.3FR")
    copy = tmp_path / "copy.3FR"
    shutil.copy2(src, copy)
    before = src.read_bytes()
    info = tool.parse_file(copy)
    tool.write_subject_distance(copy, info, 2.5)
    after = copy.read_bytes()
    assert len(after) > len(before)
    diffs = [i for i in range(len(before)) if before[i] != after[i]]
    # The pointer value is small in this synthetic fixture (file well under
    # 256 bytes), so only its low byte actually flips; upper bytes stay
    # 0x00 on both sides. The real invariant is "no byte outside the
    # pointer field changed", not "all 4 bytes changed" - assert a subset,
    # not exact equality, and require the change to be non-empty.
    assert diffs
    assert set(diffs) <= {info.exif_ptr_pos + k for k in range(4)}


def test_entries_stay_sorted_and_next_ifd_preserved(tool, tmp_path):
    src = build_3fr(tmp_path / "orig.3FR")
    copy = tmp_path / "copy.3FR"
    shutil.copy2(src, copy)
    info = tool.parse_file(copy)
    tool.write_subject_distance(copy, info, 1.0)
    info2 = tool.parse_file(copy)
    tags = [struct.unpack("<H", x[:2])[0] for x in info2.exif_entries]
    assert tags == sorted(tags)
    assert info2.exif_next_ifd == info.exif_next_ifd


def test_refuses_double_write(tool, tmp_path):
    src = build_3fr(tmp_path / "orig.3FR", subject_distance=(500, 1000))
    copy = tmp_path / "copy.3FR"
    shutil.copy2(src, copy)
    info = tool.parse_file(copy)
    with pytest.raises(tool.ParseError):
        tool.write_subject_distance(copy, info, 1.0)


def test_rejects_overflowing_distance(tool, tmp_path):
    # A pathological calibration ratio can produce a distance whose
    # round(dist_m * 1000) numerator would not fit a uint32 RATIONAL.
    src = build_3fr(tmp_path / "orig.3FR")
    copy = tmp_path / "copy.3FR"
    shutil.copy2(src, copy)
    info = tool.parse_file(copy)
    with pytest.raises(tool.ParseError):
        tool.write_subject_distance(copy, info, 4294968.0)  # *1000 > uint32 max


def test_rejects_nonpositive_distance(tool, tmp_path):
    src = build_3fr(tmp_path / "orig.3FR")
    copy = tmp_path / "copy.3FR"
    shutil.copy2(src, copy)
    info = tool.parse_file(copy)
    with pytest.raises(tool.ParseError):
        tool.write_subject_distance(copy, info, -1.0)
    with pytest.raises(tool.ParseError):
        tool.write_subject_distance(copy, info, 0.0)


def test_big_endian_write(tool, tmp_path):
    src = build_3fr(tmp_path / "orig.3FR", byte_order="MM")
    copy = tmp_path / "copy.3FR"
    shutil.copy2(src, copy)
    info = tool.parse_file(copy)
    tool.write_subject_distance(copy, info, 0.9)
    assert tool.parse_file(copy).subject_distance == pytest.approx(0.9)
