# Changelog

## Unreleased

- Folder mode: a frame at the infinity stop (maker-note magnification exactly 0 with a non-zero focal value) now gets SubjectDistance written as the EXIF infinity (0xFFFFFFFF/1), in place, whatever the file held. Before, such frames were skipped as "no focus data" and kept a stale value. No lens calibration is needed for this.
- A maker note with all focus fields zero is still skipped as "no focus data", with the same message as before.
- Infinity frames in files without a SubjectDistance tag are skipped and counted on their own line ("skipped, infinity, no tag to correct"); no copy is made.
- The undo log records `"new_value": null` and `"new_kind": "infinity"` for these entries. Undo uses the hex bytes and is unchanged.

## 0.2.0

- New one-command form: `python3 hb-focus-retrofit.py <folder>` processes every `.3FR` under the folder, including subfolders, with no options to learn. `--dry-run` reports what would happen and writes nothing.
- The maker note now decides SubjectDistance. For every file where a distance can be computed (maker-note focus fields present, lens calibrated, magnification inside the calibrated range), that value is written whatever the file already held: feet, the Infinity placeholder, a stale value, or a plausible one.
- Files that already have the tag are edited in place, 8 bytes only. Before writing, the bytes and file size are re-checked; after writing, they are flushed, read back and checked again. The file's modification time is not preserved.
- Every in-place change is recorded in `hb-focus-retrofit-undo-<UTC time>-<run id>.jsonl` in the folder you passed, and the line is flushed to disk before the file is touched.
- New `undo <logfile>` command restores the old bytes, only where the file still holds the logged new bytes and has the logged size. It is safe to run twice.
- Files with no tag (before firmware 1.3.16.1) still get a copy, now under `<folder>/retrofitted/` keeping the subfolder layout. Existing copies are never overwritten.
- Skipped files are reported with their reason and counted separately: no focus data, no calibration for the lens, focal length outside the calibration by more than 10 percent (converter), outside the calibrated range (including far focus), symlink.
- The `retrofit`, `calibrate` and `inspect` commands behave as before.

## 0.1.0

- Initial release: `retrofit` (copies only), `calibrate`, `inspect`, calibrations for the XCD 25V, 55V, 90V, 120 and 135.
