import struct

from fixtures import build_3fr


def test_fixture_is_parseable_tiff(tmp_path):
    p = build_3fr(tmp_path / "t.3FR")
    data = p.read_bytes()
    assert data[:2] == b"II"
    assert struct.unpack("<H", data[2:4])[0] == 42


def test_fixture_carries_maker_doubles(tmp_path):
    p = build_3fr(tmp_path / "t.3FR", maker_f=89.48658, maker_m=0.00112)
    data = p.read_bytes()
    # hand-walk: IFD0 -> 0x8769 -> EXIF IFD -> 0x927c -> maker IFD -> 0x0081/0x0082
    e = "<"
    ifd0 = struct.unpack(e + "I", data[4:8])[0]

    def entry(off, want):
        n = struct.unpack(e + "H", data[off:off + 2])[0]
        for i in range(n):
            ent = off + 2 + 12 * i
            tag, typ, cnt = struct.unpack(e + "HHI", data[ent:ent + 8])
            if tag == want:
                return typ, cnt, struct.unpack(e + "I", data[ent + 8:ent + 12])[0]
        raise AssertionError(hex(want))

    _, _, exif = entry(ifd0, 0x8769)
    _, _, mk = entry(exif, 0x927C)
    typ, cnt, off81 = entry(mk, 0x0081)
    assert typ == 12 and cnt == 1
    assert struct.unpack(e + "d", data[off81:off81 + 8])[0] == 89.48658


def test_fixture_big_endian(tmp_path):
    p = build_3fr(tmp_path / "t.3FR", byte_order="MM")
    assert p.read_bytes()[:2] == b"MM"


def test_fixture_optional_subject_distance(tmp_path):
    with_sd = build_3fr(tmp_path / "a.3FR", subject_distance=(500, 1000)).read_bytes()
    without = build_3fr(tmp_path / "b.3FR").read_bytes()
    assert struct.pack("<HH", 0x9206, 5) in with_sd
    assert struct.pack("<HH", 0x9206, 5) not in without
