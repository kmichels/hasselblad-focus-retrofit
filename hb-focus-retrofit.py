#!/usr/bin/env python3
"""Write the correct focus distance into Hasselblad X2D II 3FR files so
Lightroom and Capture One can apply distance-aware lens corrections.

    python3 hb-focus-retrofit.py <folder>

computes the distance from each file's maker note and the lens calibration and
makes EXIF SubjectDistance match. Files that already carry the tag are edited
in place (8 bytes) with an undo log; files without the tag (before firmware
1.3.16.1) get a copy under <folder>/retrofitted/. `undo <logfile>` reverses
the in-place edits.

Project: https://github.com/kmichels/hasselblad-focus-retrofit  (MIT)
"""
import argparse
import collections
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
import uuid
from typing import List, Optional

logger = logging.getLogger("hb-focus-retrofit")

VERSION = "0.2.0"


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
    # SubjectDistance (0x9206) as stored: where its 8 RATIONAL bytes live, the
    # raw bytes, and the file size at parse time. None when the tag is absent
    # (or not a RATIONAL x1, in which case sd_problem says why).
    sd_offset: Optional[int] = None
    sd_raw: Optional[bytes] = None
    sd_num: Optional[int] = None
    sd_den: Optional[int] = None
    sd_problem: Optional[str] = None
    size: int = 0


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

        sd_offset = sd_raw = sd_num = sd_den = sd_problem = None
        if 0x9206 in exif:
            _tag, sd_typ, sd_cnt = struct.unpack(e + "HHI", exif[0x9206][:8])
            if sd_typ == 5 and sd_cnt == 1:
                sd_offset = struct.unpack(e + "I", exif[0x9206][8:12])[0]
                sd_raw = read_at(sd_offset, 8)
                sd_num, sd_den = struct.unpack(e + "II", sd_raw)
            else:
                sd_problem = (f"SubjectDistance has unexpected type {sd_typ} count "
                              f"{sd_cnt} (expected RATIONAL x1)")

        return FileInfo(
            path=path, byte_order=head[:2].decode(),
            sd_offset=sd_offset, sd_raw=sd_raw, sd_num=sd_num, sd_den=sd_den,
            sd_problem=sd_problem, size=size,
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

    @property
    def m_min(self):
        return self.points[0][0]

    @property
    def m_max(self):
        return self.points[-1][0]

    def in_range(self, m):
        return self.m_min <= m <= self.m_max

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


# SubjectDistance numerator 0xFFFFFFFF is the camera's "no distance recorded"
# marker (EXIF infinity sentinel). Denominators of 1 and 1000 both leave the
# value far above any real ladder distance, so anything at or beyond
# 0xFFFFFFFF/1000 meters is the sentinel, not a measurement.
_SD_SENTINEL_M = 0xFFFFFFFF / 1000


def _reject_hints(rejects):
    hints = []
    if rejects["sentinel"]:
        hints.append(
            f"{rejects['sentinel']} frame(s) carry the camera's 'no distance recorded' "
            "marker (SubjectDistance = 4294967295), so there is nothing to calibrate "
            "against. The camera only latches a distance on some autofocus "
            "acquisitions and resets to this marker on every lens change, so frames "
            "shot right after mounting a lens, or focused by racking the focus ring, "
            "never record one. Reshoot so every frame gets a fresh AF lock "
            "(physically move the camera or the target between shots), and verify on "
            "the card before committing to a full ladder: after 2-3 test frames, run "
            "exiftool -s3 -SubjectDistance *.3FR and confirm real distances appear.")
    if rejects["no_distance"]:
        hints.append(
            f"{rejects['no_distance']} frame(s) have no SubjectDistance tag at all, "
            "which usually means camera firmware older than 1.3.16.1. Update the "
            "firmware and reshoot.")
    if rejects["implausible"]:
        hints.append(
            f"{rejects['implausible']} frame(s) report a distance of 50 m or more; "
            "shoot the ladder between the lens's minimum focus distance and roughly "
            "3 m.")
    if rejects["no_maker"]:
        hints.append(
            f"{rejects['no_maker']} frame(s) lack the maker-note focus fields the "
            "tool calibrates against (not from an X2D II?).")
    if rejects["unreadable"]:
        hints.append(f"{rejects['unreadable']} file(s) could not be parsed as 3FR.")
    return "".join("\n  " + h for h in hints)


def _dedupe_points(points):
    """Collapse byte-identical (m, f, distance) points into one.

    The camera can stamp two frames with the exact same latched AF
    acquisition; emitting both produces a duplicate m value that
    Calibration.from_json rejects at load (this silently uncalibrated the
    XCD 90V). Same m with a *different* recorded distance is a conflict the
    contributor has to resolve, not a choice the tool can make.
    """
    out, warnings, dropped = [], [], 0
    for pt in points:  # already sorted by m
        if out and pt["m"] == out[-1]["m"]:
            if (pt["f"] == out[-1]["f"]
                    and pt["camera_distance_m"] == out[-1]["camera_distance_m"]):
                dropped += 1
                continue
            raise CalibrationError(
                f"conflicting frames at focus position m={pt['m']!r}: "
                f"(f={out[-1]['f']!r} mm, {out[-1]['camera_distance_m']!r} m) vs "
                f"(f={pt['f']!r} mm, {pt['camera_distance_m']!r} m). "
                "Remove one of the frames and rerun.")
        out.append(pt)
    if dropped:
        warnings.append(
            f"dropped {dropped} frame(s) byte-identical to another rung "
            "(same focus position and distance); calibration is unaffected")
    return out, warnings


# A recorded distance repeated across frames is legitimate when the focus
# positions nearly agree (rounded rungs on shipped ladders spread under ~5%),
# and a stale latch when they don't. 10% leaves margin on both sides of the
# observed cases (legit <=4.8%, latched ~250%).
_LATCH_SPREAD = 1.10


def _check_latched_distances(points):
    by_dist = {}
    for p in points:
        by_dist.setdefault(p["camera_distance_m"], []).append(p)
    for dist, grp in sorted(by_dist.items()):
        ests = [thin_lens_m(p["f"], p["m"]) for p in grp]
        # min(ests) > 0 is belt-and-braces: frames with non-positive f or m
        # are rejected before points are built, so ests are positive here.
        if len(grp) > 1 and min(ests) > 0 and max(ests) / min(ests) > _LATCH_SPREAD:
            raise CalibrationError(
                f"{len(grp)} frames all report exactly {dist:g} m while their focus "
                f"positions imply {min(ests):.2f}-{max(ests):.2f} m. The camera "
                "latches a distance on some AF acquisitions and re-stamps the stale "
                "value on later frames, so these are not real measurements and "
                "would poison the calibration. Reshoot so every frame gets a fresh "
                "AF lock (physically move the camera or target between shots), and "
                "verify on the card first: after 2-3 test frames, run "
                "exiftool -s3 -SubjectDistance *.3FR and confirm a different real "
                "distance on each frame before shooting the full ladder.")


def derive_calibration(folder):
    folder = pathlib.Path(folder)
    frames = []
    rejects = {"sentinel": 0, "no_distance": 0, "implausible": 0,
               "no_maker": 0, "unreadable": 0}
    for p in sorted(folder.iterdir()):
        if p.suffix.lower() != ".3fr":
            continue
        try:
            info = parse_file(p)
        except ParseError:
            rejects["unreadable"] += 1
            continue
        sd = info.subject_distance
        if not (info.maker_f and info.maker_m and info.maker_m > 0):
            rejects["no_maker"] += 1
        elif sd is None or sd == 0:
            rejects["no_distance"] += 1
        elif sd >= _SD_SENTINEL_M:
            rejects["sentinel"] += 1
        elif not (0 < sd < 50):
            rejects["implausible"] += 1
        else:
            frames.append(info)
    if len(frames) < 5:
        raise CalibrationError(
            f"only {len(frames)} usable frames in {folder} (need at least 5: "
            "new-firmware shots with real focus distances)"
            + _reject_hints(rejects))
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
    points, dedupe_warnings = _dedupe_points(points)
    warnings.extend(dedupe_warnings)
    if len(points) < 5:
        raise CalibrationError(
            f"only {len(points)} distinct points for {lens} in {folder} after "
            "collapsing identical frames (need at least 5)")
    _check_latched_distances(points)
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


# ---------------------------------------------------------------------------
# Folder mode: the maker note always wins.
#
# Files that already carry SubjectDistance are edited in place (the 8-byte
# RATIONAL only, undo log written first). Files without the tag get a copy,
# because adding the tag restructures the file.
# ---------------------------------------------------------------------------

OUTPUT_DIR = "retrofitted"
SENTINEL_NUM = 0xFFFFFFFF
UNDO_PREFIX = "hb-focus-retrofit-undo-"


class VerifyError(Exception):
    """A safety check failed around an in-place write."""


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def _read_at(fh, off, n):
    fh.seek(off)
    data = fh.read(n)
    if len(data) != n:
        raise VerifyError(f"short read of {n} bytes at {off:#x}")
    return data


def _numerator(name, dist_m):
    """uint32 RATIONAL numerator (denominator 1000) for dist_m, or ParseError."""
    num = round(dist_m * 1000) if dist_m > 0 else 0
    if num < 1 or num > 0xFFFFFFFF:
        raise ParseError(f"{name}: distance {dist_m!r} m is out of range for a "
                         f"SubjectDistance RATIONAL")
    return num


class UndoLog:
    """Append-only JSON-lines undo log. The file is created on the first
    append, so a run that changes nothing leaves no log behind."""

    def __init__(self, folder, run_id):
        self.folder = pathlib.Path(folder)
        self.run_id = run_id
        stamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
        self._target = self.folder / f"{UNDO_PREFIX}{stamp}-{run_id}.jsonl"
        self.path = None
        self._fh = None

    def append(self, entry):
        if self._fh is None:
            fd = os.open(self._target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o644)
            self._fh = os.fdopen(fd, "a", encoding="utf-8")
            self.path = self._target
            _fsync_dir(self.folder)
        self._fh.write(json.dumps(entry, sort_keys=True) + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def close(self):
        if self._fh is not None:
            self._fh.close()
            self._fh = None


def _fsync_dir(folder):
    try:
        fd = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        logger.debug("could not fsync directory %s", folder)
    finally:
        os.close(fd)


def write_subject_distance_inplace(path, info, dist_m, undo_log):
    """Overwrite the existing 8-byte SubjectDistance RATIONAL with
    round(d*1000)/1000. Order: verify the bytes are still what the parser saw,
    make the undo line durable, write, fsync, verify, restore on failure."""
    name = info.path.name
    if info.sd_offset is None:
        raise ParseError(f"{name}: no SubjectDistance to overwrite")
    num = _numerator(name, dist_m)
    e = "<" if info.byte_order == "II" else ">"
    new = struct.pack(e + "II", num, 1000)
    old, off = info.sd_raw, info.sd_offset
    with open(path, "r+b") as fh:
        size = os.fstat(fh.fileno()).st_size
        if size != info.size or _read_at(fh, off, 8) != old:
            raise VerifyError(f"{name}: file changed since it was read; nothing written")
        undo_log.append({
            "run_id": undo_log.run_id,
            "timestamp": _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "path": str(pathlib.Path(path).resolve()),
            "size": size, "offset": off,
            "old_hex": old.hex(), "new_hex": new.hex(),
            "old_value": (info.sd_num / info.sd_den) if info.sd_den else None,
            "new_value": num / 1000,
            "lens": info.lens_model,
        })
        fh.seek(off)
        fh.write(new)
        fh.flush()
        os.fsync(fh.fileno())
        got = _read_at(fh, off, 8)
        size_after = os.fstat(fh.fileno()).st_size
        if got != new or size_after != size:
            logger.error("verification failed for %s: offset=%d wrote=%s read=%s "
                         "size=%d->%d", path, off, new.hex(), got.hex(), size, size_after)
            restored = _restore_bytes(fh, off, old)
            raise VerifyError(
                f"{name}: verification failed after write (read back {got.hex()}, "
                f"size {size} -> {size_after}); old bytes "
                + ("restored" if restored else "COULD NOT BE RESTORED, see the undo log"))
    check = parse_file(path)
    if (check.sd_num, check.sd_den) != (num, 1000):
        raise VerifyError(f"{name}: re-parse after write read back "
                          f"{check.sd_num}/{check.sd_den}, expected {num}/1000; see the undo log")


def _restore_bytes(fh, off, old):
    try:
        fh.seek(off)
        fh.write(old)
        fh.flush()
        os.fsync(fh.fileno())
        return _read_at(fh, off, 8) == old
    except (OSError, VerifyError):
        logger.exception("could not restore old bytes at offset %d", off)
        return False


def maker_note_distance(info, cals):
    """(status, detail, distance_m). status is 'ok' or a skip key:
    'no-focus', 'no-cal', 'range'. Same calibration lookup and formula as the
    retrofit path, but never extrapolates: outside the calibrated magnification
    range the file is skipped, not clamped."""
    f, m = info.maker_f, info.maker_m
    if f is None or m is None:
        return "no-focus", "no maker-note focus fields", None
    if f <= 0 or m <= 0:
        return "no-focus", f"maker-note focus fields are zero (f={f:g}, m={m:g})", None
    if info.focal_length is not None and not (0.3 * info.focal_length <= f <= 3.0 * info.focal_length):
        return "no-focus", (f"maker focal {f:g} mm implausible vs nominal "
                            f"{info.focal_length:g} mm"), None
    cal = cals.get(info.lens_model or "")
    if cal is None:
        return "no-cal", f"no calibration for {info.lens_model}", None
    if not cal.in_range(m):
        return "range", (f"magnification {m:g} outside calibrated range "
                         f"{cal.m_min:g}-{cal.m_max:g}"), None
    return "ok", "", cal.correct(m, thin_lens_m(f, m))


def _stored_text(info):
    if info.sd_num == SENTINEL_NUM:
        return "Infinity"
    if not info.sd_den:
        return f"{info.sd_num}/{info.sd_den}"
    return f"{info.sd_num / info.sd_den:.3f}"


def _same_value(info, num):
    return bool(info.sd_den) and info.sd_num * 1000 == num * info.sd_den


def find_3fr(folder):
    """Yield (path, is_symlink) for every .3FR under folder, depth first,
    sorted. Skips dot-directories, the tool's own output directory at the top
    level, symlinked directories, and dot-files (macOS AppleDouble `._x`)."""
    for root, dirs, files in os.walk(folder, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".")
                         and not (pathlib.Path(root) == folder and d == OUTPUT_DIR))
        for name in sorted(files):
            if name.startswith(".") or not name.lower().endswith(".3fr"):
                continue
            p = pathlib.Path(root) / name
            yield p, p.is_symlink()


SUMMARY_ROWS = [
    ("rewritten", "rewritten in place", "would rewrite in place"),
    ("unchanged", "unchanged", "unchanged"),
    ("copied", "copied with tag added", "would copy with tag added"),
    ("exists", "output already exists", "output already exists"),
    ("no-focus", "skipped, no focus data", "skipped, no focus data"),
    ("no-cal", "skipped, no calibration", "skipped, no calibration"),
    ("range", "skipped, outside calibrated range", "skipped, outside calibrated range"),
    ("symlink", "skipped, symlink", "skipped, symlink"),
    ("error", "errors", "errors"),
]


def process_folder(folder, cals, dry_run, run_id, undo_log, emit=print):
    """Run the whole job. Returns a Counter keyed by the SUMMARY_ROWS keys."""
    tally = collections.Counter()
    found = 0
    for p, is_link in find_3fr(folder):
        found += 1
        rel = os.path.relpath(p, folder)
        if is_link:
            tally["symlink"] += 1
            emit(f"{rel}  skipped: symlink (not followed)")
            continue
        try:
            info = parse_file(p)
            if info.sd_problem:
                raise ParseError(f"{rel}: {info.sd_problem}; refusing to touch it")
            status, detail, d = maker_note_distance(info, cals)
            if status != "ok":
                tally[status] += 1
                emit(f"{rel}  skipped: {detail}")
                continue
            lens = info.lens_model
            if info.sd_offset is not None:
                num = _numerator(rel, d)
                if _same_value(info, num):
                    tally["unchanged"] += 1
                    emit(f"{rel}  unchanged ({d:.3f} m, {lens})")
                    continue
                if dry_run:
                    tally["rewritten"] += 1
                    emit(f"{rel}  would rewrite stored {_stored_text(info)} -> {d:.3f} m  ({lens})")
                    continue
                write_subject_distance_inplace(p, info, d, undo_log)
                tally["rewritten"] += 1
                emit(f"{rel}  rewritten: stored {_stored_text(info)} -> {d:.3f} m  ({lens})")
            else:
                _numerator(rel, d)
                dest = folder / OUTPUT_DIR / pathlib.Path(rel).parent
                if (dest / p.name).exists():
                    tally["exists"] += 1
                    emit(f"{rel}  output already exists in {OUTPUT_DIR}/, left alone")
                elif dry_run:
                    tally["copied"] += 1
                    emit(f"{rel}  would copy with tag added: {d:.3f} m  ({lens})")
                else:
                    try:
                        _apply_one(p, info, d, dest, None)
                    except SkipExisting:
                        tally["exists"] += 1
                        emit(f"{rel}  output already exists in {OUTPUT_DIR}/, left alone")
                        continue
                    tally["copied"] += 1
                    emit(f"{rel}  copied with tag added: {d:.3f} m  ({lens}) -> {OUTPUT_DIR}/")
        except PermissionError as exc:
            logger.exception("run %s: not writable: %s", run_id, p)
            tally["error"] += 1
            emit(f"{rel}  ERROR: permission denied ({exc.strerror}); file is read-only "
                 f"or not accessible, nothing changed")
        except (ParseError, VerifyError, OSError) as exc:
            logger.exception("run %s: failed on %s", run_id, p)
            tally["error"] += 1
            emit(f"{rel}  ERROR: {exc}")
    tally["_found"] = found
    return tally


def cmd_run(args):
    run_id = str(uuid.uuid4())
    # Per-file problems are already printed as ERROR lines; the logger carries
    # the tracebacks and state, shown only with -v.
    logging.basicConfig(level=logging.INFO if args.verbose else logging.CRITICAL,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    folder = pathlib.Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        print(f"error: not a folder: {args.folder} (if you meant a command, "
              f"the commands are retrofit, calibrate, inspect, undo)", file=sys.stderr)
        return 2
    cals = load_calibrations(pathlib.Path(__file__).resolve().parent / "calibration")
    if not cals:
        print("warning: no lens calibrations loaded; keep the calibration folder next "
              "to this script, or every file will be skipped", file=sys.stderr)
    logger.info("run %s: folder=%s dry_run=%s", run_id, folder, args.dry_run)
    undo_log = UndoLog(folder, run_id)
    try:
        tally = process_folder(folder, cals, args.dry_run, run_id, undo_log,
                               emit=lambda line: print(line, flush=True))
    finally:
        undo_log.close()
    found = tally.pop("_found", 0)
    if not found:
        print(f"no 3FR files found under {folder}")
        return 0
    idx = 2 if args.dry_run else 1
    print()
    print("DRY RUN: nothing was written" if args.dry_run else "Summary")
    print(f"  {'files found:':<36}{found}")
    for key, *labels in SUMMARY_ROWS:
        print(f"  {labels[idx - 1] + ':':<36}{tally.get(key, 0)}")
    if undo_log.path:
        print(f"undo log: {undo_log.path}")
        print(f"to reverse the in-place changes: python3 hb-focus-retrofit.py undo "
              f"\"{undo_log.path}\"")
    else:
        print("undo log: none (nothing was changed in place)")
    print(f"run_id: {run_id}")
    logger.info("run %s done: %s", run_id, dict(tally))
    return 1 if tally.get("error") else 0


def _undo_one(entry):
    """Returns (outcome, message); outcome in restored|already|skipped."""
    path = pathlib.Path(entry["path"])
    old, new = bytes.fromhex(entry["old_hex"]), bytes.fromhex(entry["new_hex"])
    off, size = entry["offset"], entry["size"]
    if len(old) != 8 or len(new) != 8 or not isinstance(off, int) or off < 0 \
            or not isinstance(size, int) or off + 8 > size:
        raise ValueError("log entry has implausible offset, size or byte values")
    if not path.is_file():
        return "skipped", f"{path}: file is missing"
    with open(path, "r+b") as fh:
        now_size = os.fstat(fh.fileno()).st_size
        if now_size != size:
            return "skipped", f"{path}: size is {now_size}, log says {size}; not touched"
        cur = _read_at(fh, off, 8)
        if cur == old:
            return "already", f"{path}: already restored"
        if cur != new:
            return "skipped", (f"{path}: current bytes {cur.hex()} are neither the logged new "
                               f"bytes nor the old bytes; changed since, not touched")
        fh.seek(off)
        fh.write(old)
        fh.flush()
        os.fsync(fh.fileno())
        if _read_at(fh, off, 8) != old or os.fstat(fh.fileno()).st_size != size:
            raise VerifyError(f"{path}: restore did not verify")
    return "restored", f"{path}: restored"


def cmd_undo(args):
    run_id = str(uuid.uuid4())
    logging.basicConfig(level=logging.CRITICAL,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = pathlib.Path(args.logfile).expanduser()
    try:
        lines = log.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        print(f"error: cannot read undo log: {exc}", file=sys.stderr)
        return 2
    logger.info("undo run %s: log=%s entries=%d", run_id, log, len(lines))
    tally = collections.Counter()
    numbered = [(i, ln) for i, ln in enumerate(lines, 1) if ln.strip()]
    for lineno, line in reversed(numbered):
        try:
            outcome, msg = _undo_one(json.loads(line))
        except (ValueError, KeyError, TypeError, OSError, VerifyError) as exc:
            logger.exception("undo run %s: bad entry at line %d: %r", run_id, lineno, line[:200])
            tally["error"] += 1
            print(f"line {lineno}: ERROR: {exc}")
            continue
        tally[outcome] += 1
        if outcome == "skipped":
            logger.warning("undo run %s: skipped line %d: %s", run_id, lineno, msg)
        print(f"line {lineno}: {msg}")
    print()
    print("Undo summary")
    for key, label in (("restored", "restored"), ("already", "already restored"),
                       ("skipped", "skipped"), ("error", "errors")):
        print(f"  {label + ':':<36}{tally.get(key, 0)}")
    print(f"run_id: {run_id}")
    return 1 if (tally.get("skipped") or tally.get("error")) else 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="hb-focus-retrofit.py",
        usage="hb-focus-retrofit.py FOLDER [--dry-run]\n"
              "       hb-focus-retrofit.py {retrofit,calibrate,inspect,undo} ...",
        description="Point it at a folder of X2D II 3FR files: SubjectDistance is made to match "
                    "the maker note and the lens calibration. Files that already have the tag are "
                    "edited in place (8 bytes, with an undo log); older files get a copy under "
                    "FOLDER/retrofitted. 'undo LOGFILE' reverses the in-place edits.",
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

    u = sub.add_parser("undo", help="reverse the in-place edits recorded in an undo log")
    u.add_argument("logfile", help="hb-focus-retrofit-undo-*.jsonl written by a folder run")
    u.set_defaults(func=cmd_undo)
    return p


SUBCOMMANDS = ("retrofit", "calibrate", "inspect", "undo")


def build_folder_parser():
    p = argparse.ArgumentParser(
        prog="hb-focus-retrofit.py",
        description="Make SubjectDistance in every 3FR under FOLDER match the maker note.")
    p.add_argument("--version", action="version", version=VERSION)
    p.add_argument("folder", help="folder to process (recursive)")
    p.add_argument("--dry-run", action="store_true",
                   help="report what would happen; write nothing, create no log")
    p.add_argument("-v", "--verbose", action="store_true", help="log progress to stderr")
    p.set_defaults(func=cmd_run)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in SUBCOMMANDS and argv[0] not in ("-h", "--help", "--version"):
        # `hb-focus-retrofit.py <folder>`: the one-command form
        return cmd_run(build_folder_parser().parse_args(argv))
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help(sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
