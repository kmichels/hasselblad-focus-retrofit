#!/usr/bin/env python3
"""Write focus distance into Hasselblad X2D II 3FR files so Lightroom and
Capture One can apply distance-aware lens corrections to older captures.

Project: https://github.com/kmichels/hasselblad-focus-retrofit  (MIT)
"""
import argparse
import dataclasses
import datetime
import json
import logging
import os
import pathlib
import shutil
import stat
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
    focal_length: Optional[float]
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
            focal_length=value(exif[0x920A]) if 0x920A in exif else None,
            exif_ptr_pos=exif_ptr_pos, exif_ifd_off=exif_off,
            exif_entries=exif_entries, exif_next_ifd=exif_next,
        )


def write_subject_distance(path, info, dist_m):
    e = "<" if info.byte_order == "II" else ">"
    tags = [struct.unpack(e + "H", x[:2])[0] for x in info.exif_entries]
    if 0x9206 in tags:
        raise ParseError(f"{info.path.name}: SubjectDistance already present")
    if not (dist_m > 0) or round(dist_m * 1000) > 4294967295:
        # Guards the uint32 RATIONAL numerator against overflow and rejects
        # non-positive distances outright; classify()'s >1km check is only
        # an early skip on the pre-calibration estimate, not a hard bound on
        # what a calibration curve can ultimately produce here.
        raise ParseError(f"{info.path.name}: distance {dist_m!r} m is out of "
                          f"range for a SubjectDistance RATIONAL")
    num, den = round(dist_m * 1000), 1000
    with open(path, "r+b") as fh:
        fh.seek(0, 2)
        new_off = fh.tell()
        if new_off % 2:
            fh.write(b"\x00")
            new_off += 1
        n = len(info.exif_entries) + 1
        val_off = new_off + 2 + 12 * n + 4
        entry = struct.pack(e + "HHII", 0x9206, 5, 1, val_off)
        merged = sorted(info.exif_entries + [entry],
                        key=lambda x: struct.unpack(e + "H", x[:2])[0])
        fh.write(struct.pack(e + "H", n) + b"".join(merged)
                 + info.exif_next_ifd + struct.pack(e + "II", num, den))
        fh.seek(info.exif_ptr_pos)
        fh.write(struct.pack(e + "I", new_off))


def thin_lens_m(f_mm, m):
    return f_mm * (1 + 1 / m) / 1000.0


def classify(info):
    if info.subject_distance is not None:
        return "skip-present", f"SubjectDistance already {info.subject_distance:g} m"
    if info.maker_f is None or info.maker_m is None:
        return "skip-nofields", "no maker-note focus fields (firmware before 1.2.7.11?)"
    if info.maker_m <= 0:
        return "skip-infinity", "magnification 0 = focused at infinity"
    if info.maker_m > 2:
        return "skip-insane", f"magnification {info.maker_m:g} out of range"
    if thin_lens_m(info.maker_f, info.maker_m) > 1000:
        # also guards the uint32 RATIONAL numerator (d*1000) against overflow
        return "skip-infinity", "computed distance beyond 1 km = effectively infinity"
    if info.focal_length is not None and not (0.3 * info.focal_length <= info.maker_f <= 3.0 * info.focal_length):
        return "skip-insane", (f"maker focal {info.maker_f:g} mm implausible vs "
                               f"nominal {info.focal_length:g} mm")
    return "write", ""


class Calibration:
    def __init__(self, lens_model, points):
        # points: list of (m, ratio) sorted by m ascending;
        # ratio = camera_distance / thin_lens_m(f, m) at that knot
        self.lens_model = lens_model
        self.points = sorted(points)

    @classmethod
    def from_json(cls, path):
        doc = json.loads(pathlib.Path(path).read_text())
        if not doc["points"]:
            raise ValueError("calibration has no points")
        pts = []
        for p in doc["points"]:
            m, f, camera = p["m"], p["f"], p["camera_distance_m"]
            if isinstance(m, bool) or not isinstance(m, (int, float)):
                raise ValueError(f"point m must be numeric, got {m!r}")
            if isinstance(f, bool) or not isinstance(f, (int, float)):
                raise ValueError(f"point f must be numeric, got {f!r}")
            if isinstance(camera, bool) or not isinstance(camera, (int, float)):
                raise ValueError(f"point camera_distance_m must be numeric, got {camera!r}")
            if m <= 0:
                raise ValueError(f"point m must be > 0, got {m!r}")
            if f <= 0:
                raise ValueError(f"point f must be > 0, got {f!r}")
            if camera <= 0:
                raise ValueError(f"point camera_distance_m must be > 0, got {camera!r}")
            pts.append((m, camera / thin_lens_m(f, m)))
        pts.sort()
        for (m0, _), (m1, _) in zip(pts, pts[1:]):
            if m0 == m1:
                raise ValueError(f"duplicate m value {m0!r} in calibration points")
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
            except (KeyError, ValueError, TypeError, ZeroDivisionError, json.JSONDecodeError) as exc:
                logger.warning("ignoring bad calibration file %s: %s", p, exc)
    return out


def cmd_retrofit(args):
    source = pathlib.Path(args.source).expanduser().resolve()
    if not source.is_dir():
        print(f"error: source folder not found: {source}", file=sys.stderr)
        return 1
    dest = pathlib.Path(args.dest).expanduser().resolve() if args.dest else source / "retrofitted"

    if args.calibration:
        try:
            cal = Calibration.from_json(args.calibration)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        cals = {cal.lens_model: cal}
    else:
        cals = load_calibrations(pathlib.Path(__file__).resolve().parent / "calibration")

    files = sorted(p for p in source.iterdir()
                   if p.is_file() and p.suffix.lower() == ".3fr"
                   and p.parent != dest)
    if not files:
        example = _find_3fr_in_subfolder(source)
        if example:
            print(f"no 3FR files found directly in {source}, but "
                  f"{example.parent.name}/ has some (e.g. {example.name}). "
                  f"This tool does not scan subfolders: point --source at "
                  f"{example.parent} instead.")
        else:
            print(f"no 3FR files found in {source}")
        return 0

    counts, failures = {}, 0
    rows = []
    for p in files:
        try:
            info = parse_file(p)
            action, detail = classify(info)
        except (ParseError, OSError) as exc:
            rows.append((p.name, f"FAILED: {exc}"))
            failures += 1
            continue
        phos = _find_sidecar(p)
        if action != "write":
            counts[action] = counts.get(action, 0) + 1
            rows.append((p.name, f"{action}: {detail}"))
            continue
        d_est = thin_lens_m(info.maker_f, info.maker_m)
        cal = cals.get(info.lens_model or "")
        d = cal.correct(info.maker_m, d_est) if cal else d_est
        label = f"calibrated ({cal.lens_model})" if cal else "UNCALIBRATED (raw formula)"
        sidetxt = " +.phos" if phos else ""
        if not args.apply:
            rows.append((p.name, f"would write {d:.3f} m  {label}{sidetxt}"))
            counts["would-write"] = counts.get("would-write", 0) + 1
            continue
        try:
            sidecar_warning = _apply_one(p, info, d, dest, phos if args.copy_sidecars else None)
            msg = f"wrote {d:.3f} m  {label}{sidetxt}"
            if sidecar_warning:
                msg += f"  (warning: {sidecar_warning})"
            rows.append((p.name, msg))
            counts["written"] = counts.get("written", 0) + 1
        except SkipExisting:
            rows.append((p.name, "skip: already in destination"))
            counts["skip-existing"] = counts.get("skip-existing", 0) + 1
        except (OSError, ParseError) as exc:
            rows.append((p.name, f"FAILED: {exc}"))
            failures += 1

    width = max(len(n) for n, _ in rows)
    for name, msg in rows:
        print(f"{name:<{width}}  {msg}")
    mode = "APPLIED" if args.apply else "DRY RUN (use --apply to write copies)"
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"\n{mode}: {summary}" + (f", failures={failures}" if failures else ""))
    return 1 if failures else 0


def _find_3fr_in_subfolder(source):
    """Non-recursive scan stays non-recursive; this only looks one level
    down to name a helpful example when the top-level folder is empty."""
    for d in sorted(p for p in source.iterdir() if p.is_dir()):
        try:
            hit = next((f for f in d.iterdir()
                        if f.is_file() and f.suffix.lower() == ".3fr"), None)
        except OSError:
            continue
        if hit:
            return hit
    return None


class SkipExisting(Exception):
    pass


def _find_sidecar(p):
    # Real Phocus sidecars are named "<full filename>.phos", e.g.
    # B0031108.3FR.phos, not the with_suffix() replacement "B0031108.phos".
    for ext in (".phos", ".PHOS"):
        cand = p.with_name(p.name + ext)
        if cand.exists():
            return cand
    return None


def _apply_one(p, info, dist_m, dest, sidecar):
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / p.name
    if target.exists():
        raise SkipExisting
    size = p.stat().st_size
    if shutil.disk_usage(dest).free < size + 65536:
        raise OSError(f"not enough free space in {dest} for {p.name}")
    shutil.copy2(p, target)
    # copy2 preserves permissions; a read-only original (locked card import)
    # would make the copy unwritable for the r+b edit
    os.chmod(target, os.stat(target).st_mode | stat.S_IWUSR)
    try:
        write_subject_distance(target, parse_file(target), dist_m)
        got = parse_file(target).subject_distance
        if got is None or abs(got - dist_m) > 0.001:
            raise ParseError(f"verification failed (read back {got})")
    except Exception:
        target.unlink(missing_ok=True)
        raise
    if sidecar:
        try:
            shutil.copy2(sidecar, dest / sidecar.name)
        except OSError as exc:
            # The retrofit itself already succeeded and was verified above;
            # a sidecar copy failure is a lesser problem and must not mark
            # the file as failed or discard the good copy.
            return f"could not copy sidecar {sidecar.name}: {exc}"
    return None


class CalibrationError(Exception):
    pass


def derive_calibration(folder):
    folder = pathlib.Path(folder)
    frames = []
    for p in sorted(folder.iterdir()):
        if p.suffix.lower() != ".3fr":
            continue
        try:
            info = parse_file(p)
        except ParseError:
            continue
        sd = info.subject_distance
        if (info.maker_f and info.maker_m and info.maker_m > 0
                and sd is not None and 0 < sd < 50):
            frames.append(info)
    if len(frames) < 5:
        raise CalibrationError(
            f"only {len(frames)} usable frames in {folder} (need at least 5: "
            "new-firmware shots with real focus distances)")
    lens = frames[0].lens_model or "unknown-lens"
    others = sorted({f.lens_model for f in frames} - {frames[0].lens_model})
    frames = [f for f in frames if f.lens_model == frames[0].lens_model]
    if len(frames) < 5:
        raise CalibrationError(
            f"only {len(frames)} usable frames for {lens} in {folder} (need at least 5: "
            "new-firmware shots with real focus distances)")
    warnings = []
    if others:
        warnings.append(
            f"folder also contains frames from {', '.join(str(o) for o in others)}; "
            f"only {lens} was calibrated. Run calibrate once per lens folder.")
    points = sorted(
        ({"m": f.maker_m, "f": f.maker_f, "camera_distance_m": f.subject_distance}
         for f in frames), key=lambda p: p["m"])
    dists = [p["camera_distance_m"] for p in points]
    if min(dists) > 0.7:
        warnings.append("ladder does not reach below 0.7 m; near-field correction will be extrapolation-clamped")
    if max(dists) / min(dists) < 3:
        warnings.append("ladder spans less than 3x in distance; curve may be unreliable")
    doc = {"lens_model": lens, "points": points,
           "provenance": {"body": frames[0].model, "firmware": frames[0].software,
                          "frames": len(points), "contributor": "", "date": ""}}
    return doc, warnings


def _loo_residuals(doc):
    pts = doc["points"]
    out = []
    for i, p in enumerate(pts):
        rest = pts[:i] + pts[i + 1:]
        cal = Calibration(doc["lens_model"],
                          [(q["m"], q["camera_distance_m"] / thin_lens_m(q["f"], q["m"]))
                           for q in rest])
        pred = cal.correct(p["m"], thin_lens_m(p["f"], p["m"]))
        out.append((p["camera_distance_m"], abs(pred - p["camera_distance_m"]) / p["camera_distance_m"]))
    return out


def _slugify_lens(lens_model):
    """Turn an untrusted EXIF lens name into a safe bare filename stem.

    Lowercases, keeps only [a-z0-9._-], maps everything else to "-",
    collapses runs of "-", strips leading/trailing "-"/".", and finally
    takes just the last path component so no separator or ".." can survive.
    """
    slug = lens_model.lower()
    slug = "".join(c if c in "abcdefghijklmnopqrstuvwxyz0123456789._-" else "-" for c in slug)
    # Collapse any run of "-"/"." (which includes ".." traversal sequences)
    # down to a single "-" so no separator-like run can survive.
    collapsed = []
    prev_was_sep = False
    for c in slug:
        is_sep = c in "-."
        if is_sep and prev_was_sep:
            continue
        collapsed.append("-" if is_sep else c)
        prev_was_sep = is_sep
    slug = "".join(collapsed).strip("-.")
    slug = pathlib.PurePath(slug).name
    return slug or "unknown-lens"


def cmd_calibrate(args):
    try:
        doc, warnings = derive_calibration(pathlib.Path(args.source).expanduser())
    except (CalibrationError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    doc["provenance"]["date"] = datetime.date.today().isoformat()
    doc["provenance"]["contributor"] = args.contributor or ""
    if args.out:
        out = pathlib.Path(args.out)
    else:
        out = pathlib.Path(_slugify_lens(doc["lens_model"]) + ".json")
        if out.exists():
            print(f"error: {out} already exists; pass --out to choose a "
                  f"different path", file=sys.stderr)
            return 1
    out.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"wrote {out.resolve()} ({doc['provenance']['frames']} points, lens {doc['lens_model']})")
    if not args.contributor:
        print('note: no contributor name recorded. Re-run with --contributor "Your Name" '
              "if you plan to submit this, so you get credit.")
    for w in warnings:
        print(f"warning: {w}")
    print("\nleave-one-out residuals (each point predicted by the others):")
    bad = False
    for dist, res in _loo_residuals(doc):
        flag = "  <-- above 2%, check this frame" if res > 0.02 else ""
        print(f"  {dist:6.2f} m: {100 * res:5.2f}%{flag}")
        bad = bad or res > 0.02
    if bad:
        print("some residuals above 2%: consider reshooting those rungs before submitting")
    return 0


def cmd_inspect(args):
    cals = load_calibrations(pathlib.Path(__file__).resolve().parent / "calibration")
    failures = 0
    for name in args.files:
        p = pathlib.Path(name)
        print(f"== {p.name}")
        try:
            info = parse_file(p)
        except (ParseError, OSError) as exc:
            print(f"  unreadable: {exc}")
            failures += 1
            continue
        action, detail = classify(info)
        print(f"  camera:    {info.model}   firmware: {info.software}")
        print(f"  lens:      {info.lens_model}   nominal focal: {info.focal_length}")
        print(f"  maker note: f={info.maker_f}  m={info.maker_m}")
        print(f"  SubjectDistance in file: "
              f"{'none' if info.subject_distance is None else f'{info.subject_distance:g} m'}")
        if info.maker_f and info.maker_m and info.maker_m > 0:
            d_est = thin_lens_m(info.maker_f, info.maker_m)
            cal = cals.get(info.lens_model or "")
            print(f"  thin-lens estimate: {d_est:.2f} m")
            if cal:
                print(f"  calibrated ({cal.lens_model}): {cal.correct(info.maker_m, d_est):.2f} m")
            else:
                print("  calibrated: UNCALIBRATED (no data for this lens)")
        print(f"  verdict: {action}" + (f" ({detail})" if detail else ""))
    return 1 if failures else 0


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
    c.add_argument("--source", required=True, help="folder with ladder shots (one lens per folder)")
    c.add_argument("--out", default=None, help="output JSON path (default: <lens>.json in current folder)")
    c.add_argument("--contributor", default=None,
                    help="your name or handle, recorded in the calibration file so you get credit")
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
