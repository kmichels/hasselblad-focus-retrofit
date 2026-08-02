"""Builds miniature 3FR-shaped TIFFs for tests. Absolute value offsets,
matching the real Hasselblad maker-note convention (probed 2026-08-02)."""
import struct
from pathlib import Path

T_BYTE, T_ASCII, T_SHORT, T_LONG, T_RATIONAL, T_UNDEF, T_DOUBLE = 1, 2, 3, 4, 5, 7, 12
SIZES = {T_BYTE: 1, T_ASCII: 1, T_SHORT: 2, T_LONG: 4, T_RATIONAL: 8, T_UNDEF: 1, T_DOUBLE: 8}


class _IFD:
    def __init__(self, e):
        self.e = e
        self.entries = []  # (tag, typ, count, payload_bytes or inline_value)

    def add(self, tag, typ, values):
        if typ == T_ASCII:
            payload = values.encode() + b"\x00"
            count = len(payload)
        elif typ == T_RATIONAL:
            payload = struct.pack(self.e + "II", *values)
            count = 1
        elif typ == T_DOUBLE:
            payload = struct.pack(self.e + "d", values)
            count = 1
        else:
            vals = values if isinstance(values, (list, tuple)) else [values]
            fmt = {T_SHORT: "H", T_LONG: "I", T_BYTE: "B", T_UNDEF: "B"}[typ]
            payload = b"".join(struct.pack(self.e + fmt, v) for v in vals)
            count = len(vals)
        self.entries.append((tag, typ, count, payload))

    def size(self):
        return 2 + 12 * len(self.entries) + 4


def _emit(ifd, base, heap_pos, out, heap):
    e = ifd.e
    out += struct.pack(e + "H", len(ifd.entries))
    for tag, typ, count, payload in sorted(ifd.entries):
        out += struct.pack(e + "HHI", tag, typ, count)
        if len(payload) <= 4:
            out += payload.ljust(4, b"\x00")
        else:
            out += struct.pack(e + "I", heap_pos)
            heap += payload
            heap_pos += len(payload)
            if heap_pos % 2:
                heap += b"\x00"
                heap_pos += 1
    out += b"\x00\x00\x00\x00"  # next IFD
    return out, heap_pos, heap


def build_3fr(path, *, byte_order="II", model="X2D II 100C", software="1.2.7.16",
              lens_model="XCD 55V", focal_length=(55, 1), maker_f=52.38143,
              maker_m=0.08961, subject_distance=None, include_maker_fields=True):
    e = "<" if byte_order == "II" else ">"
    ifd0, exif, mk = _IFD(e), _IFD(e), _IFD(e)

    mk.add(0x0005, T_LONG, 2)
    if include_maker_fields:
        mk.add(0x0081, T_DOUBLE, maker_f)
        mk.add(0x0082, T_DOUBLE, maker_m)

    # sizes are interdependent only through offsets; lay out in fixed order
    ifd0_off = 8
    # placeholder entries so sizes are known before offsets are computed
    ifd0.add(0x0110, T_ASCII, model)
    ifd0.add(0x0131, T_ASCII, software)
    ifd0.add(0x8769, T_LONG, 0)          # patched below
    exif.add(0x920A, T_RATIONAL, focal_length)
    exif.add(0xA434, T_ASCII, lens_model)
    exif.add(0x927C, T_LONG, 0)          # patched below (offset styled as LONG)
    if subject_distance is not None:
        exif.add(0x9206, T_RATIONAL, subject_distance)

    exif_off = ifd0_off + ifd0.size()
    mk_off = exif_off + exif.size()
    heap_off = mk_off + mk.size()

    # patch pointer entries now that offsets are known
    ifd0.entries = [(t, ty, c, struct.pack(e + "I", exif_off) if t == 0x8769 else p)
                    for t, ty, c, p in ifd0.entries]
    exif.entries = [(t, ty, c, struct.pack(e + "I", mk_off) if t == 0x927C else p)
                    for t, ty, c, p in exif.entries]

    out = (b"II" if e == "<" else b"MM") + struct.pack(e + "H", 42) + struct.pack(e + "I", ifd0_off)
    heap, heap_pos = b"", heap_off
    out, heap_pos, heap = _emit(ifd0, ifd0_off, heap_pos, out, heap)
    out, heap_pos, heap = _emit(exif, exif_off, heap_pos, out, heap)
    out, heap_pos, heap = _emit(mk, mk_off, heap_pos, out, heap)
    out += heap
    path = Path(path)
    path.write_bytes(out)
    return path
