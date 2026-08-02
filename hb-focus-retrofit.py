#!/usr/bin/env python3
"""Write focus distance into Hasselblad X2D II 3FR files so Lightroom and
Capture One can apply distance-aware lens corrections to older captures.

Project: https://github.com/kmichels/hasselblad-focus-retrofit  (MIT)
"""
import argparse
import dataclasses
import json
import logging
import pathlib
import struct
import sys
from typing import List, Optional

logger = logging.getLogger("hb-focus-retrofit")

VERSION = "0.1.0"


class ParseError(Exception):
    pass


@dataclasses.dataclass
class FileInfo:
    path: pathlib.Path
    byte_order: str
    model: Optional[str]
    software: Optional[str]
    lens_model: Optional[str]
    maker_f: Optional[float]
    maker_m: Optional[float]
    subject_distance: Optional[float]
    exif_ptr_pos: int
    exif_ifd_off: int
    exif_entries: List[bytes]
    exif_next_ifd: bytes


TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8, 11: 4, 12: 8}


def parse_file(path):
    path = pathlib.Path(path)
    size = path.stat().st_size
    with open(path, "rb") as fh:
        def read_at(off, n):
            if off < 0 or off + n > size:
                raise ParseError(f"{path.name}: read past EOF at {off:#x}")
            fh.seek(off)
            b = fh.read(n)
            if len(b) != n:
                raise ParseError(f"{path.name}: short read at {off:#x}")
            return b

        head = read_at(0, 8)
        if head[:2] == b"II":
            e = "<"
        elif head[:2] == b"MM":
            e = ">"
        else:
            raise ParseError(f"{path.name}: not a TIFF (header {head[:2]!r})")
        if struct.unpack(e + "H", head[2:4])[0] != 42:
            raise ParseError(f"{path.name}: bad TIFF magic")
        ifd0_off = struct.unpack(e + "I", head[4:8])[0]

        def read_ifd(off):
            n = struct.unpack(e + "H", read_at(off, 2))[0]
            raw = read_at(off + 2, 12 * n + 4)
            entries = [raw[i * 12:(i + 1) * 12] for i in range(n)]
            return entries, raw[12 * n:12 * n + 4]

        def entry_map(entries):
            return {struct.unpack(e + "H", x[:2])[0]: x for x in entries}

        def value(entry_bytes):
            tag, typ, cnt = struct.unpack(e + "HHI", entry_bytes[:8])
            unit = TYPE_SIZES.get(typ)
            if unit is None:
                return None
            total = unit * cnt
            if total <= 4:
                payload = entry_bytes[8:8 + total]
            else:
                off = struct.unpack(e + "I", entry_bytes[8:12])[0]
                payload = read_at(off, total)
            if typ == 2:
                return payload.split(b"\x00")[0].decode("ascii", "replace")
            if typ == 5:
                num, den = struct.unpack(e + "II", payload[:8])
                return num / den if den else None
            if typ == 12:
                return struct.unpack(e + "d", payload[:8])[0]
            if typ in (3, 4):
                fmt = "H" if typ == 3 else "I"
                vals = struct.unpack(e + fmt * cnt, payload)
                return vals[0] if cnt == 1 else list(vals)
            return payload

        ifd0_entries, _ = read_ifd(ifd0_off)
        ifd0 = entry_map(ifd0_entries)
        if 0x8769 not in ifd0:
            raise ParseError(f"{path.name}: no EXIF IFD pointer")
        # position of the 0x8769 value field within the file
        idx = ifd0_entries.index(ifd0[0x8769])
        exif_ptr_pos = ifd0_off + 2 + 12 * idx + 8
        exif_off = struct.unpack(e + "I", ifd0[0x8769][8:12])[0]

        exif_entries, exif_next = read_ifd(exif_off)
        exif = entry_map(exif_entries)

        maker_f = maker_m = None
        if 0x927C in exif:
            mk_off = struct.unpack(e + "I", exif[0x927C][8:12])[0]
            try:
                mk_entries, _ = read_ifd(mk_off)
                mk = entry_map(mk_entries)
                if 0x0081 in mk:
                    maker_f = value(mk[0x0081])
                if 0x0082 in mk:
                    maker_m = value(mk[0x0082])
            except ParseError:
                pass  # unreadable maker note = fields absent, not fatal

        return FileInfo(
            path=path, byte_order=head[:2].decode(),
            model=value(ifd0[0x0110]) if 0x0110 in ifd0 else None,
            software=value(ifd0[0x0131]) if 0x0131 in ifd0 else None,
            lens_model=value(exif[0xA434]) if 0xA434 in exif else None,
            maker_f=maker_f, maker_m=maker_m,
            subject_distance=value(exif[0x9206]) if 0x9206 in exif else None,
            exif_ptr_pos=exif_ptr_pos, exif_ifd_off=exif_off,
            exif_entries=exif_entries, exif_next_ifd=exif_next,
        )


def thin_lens_m(f_mm, m):
    return f_mm * (1 + 1 / m) / 1000.0


class Calibration:
    def __init__(self, lens_model, points):
        # points: list of (m, ratio) sorted by m ascending;
        # ratio = camera_distance / thin_lens_m(f, m) at that knot
        self.lens_model = lens_model
        self.points = sorted(points)

    @classmethod
    def from_json(cls, path):
        doc = json.loads(pathlib.Path(path).read_text())
        pts = [(p["m"], p["camera_distance_m"] / thin_lens_m(p["f"], p["m"]))
               for p in doc["points"]]
        return cls(doc["lens_model"], pts)

    def ratio(self, m):
        pts = self.points
        if m <= pts[0][0]:
            return pts[0][1]
        if m >= pts[-1][0]:
            return pts[-1][1]
        for (m0, r0), (m1, r1) in zip(pts, pts[1:]):
            if m0 <= m <= m1:
                t = (m - m0) / (m1 - m0)
                return r0 + t * (r1 - r0)
        return pts[-1][1]

    def correct(self, m, d_est):
        return d_est * self.ratio(m)


def load_calibrations(dir_path):
    out = {}
    d = pathlib.Path(dir_path)
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            try:
                cal = Calibration.from_json(p)
                out[cal.lens_model] = cal
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("ignoring bad calibration file %s: %s", p, exc)
    return out


def cmd_retrofit(args):
    raise NotImplementedError


def cmd_calibrate(args):
    raise NotImplementedError


def cmd_inspect(args):
    raise NotImplementedError


def build_parser():
    p = argparse.ArgumentParser(
        prog="hb-focus-retrofit.py",
        description="Add focus distance to Hasselblad 3FR files (writes copies; originals are never touched).",
    )
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="command")

    r = sub.add_parser("retrofit", help="compute and write SubjectDistance into copies")
    r.add_argument("--source", default=".", help="folder with 3FR files (default: current folder)")
    r.add_argument("--dest", default=None, help="output folder (default: <source>/retrofitted)")
    r.add_argument("--apply", action="store_true", help="actually write copies (default: report only)")
    r.add_argument("--copy-sidecars", action="store_true", help="copy matching .phos files too")
    r.add_argument("--calibration", default=None, help="calibration JSON file to use")
    r.add_argument("--verbose", action="store_true")
    r.set_defaults(func=cmd_retrofit)

    c = sub.add_parser("calibrate", help="derive a lens calibration from new-firmware ladder shots")
    c.add_argument("--source", required=True, help="folder with ladder shots")
    c.add_argument("--out", default=None, help="output JSON path (default: <lens>.json in current folder)")
    c.set_defaults(func=cmd_calibrate)

    i = sub.add_parser("inspect", help="show what the tool sees in a file (never writes)")
    i.add_argument("files", nargs="+")
    i.set_defaults(func=cmd_inspect)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help(sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
