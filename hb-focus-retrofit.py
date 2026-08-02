#!/usr/bin/env python3
"""Write focus distance into Hasselblad X2D II 3FR files so Lightroom and
Capture One can apply distance-aware lens corrections to older captures.

Project: https://github.com/kmichels/hasselblad-focus-retrofit  (MIT)
"""

import argparse
import sys

VERSION = "0.1.0"


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
