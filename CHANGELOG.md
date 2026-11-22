# Changelog

## Unreleased

- Folder mode: a frame focused beyond the far end of its lens's calibration (maker-note magnification positive but smaller than the calibrated range) now gets an ESTIMATE written instead of being skipped: thin-lens distance times the calibration ratio at the far end of the range, held constant. In place, 8 bytes, with the undo log, whatever value was stored. The report line says "estimated, beyond calibration" and the summary counts these frames separately from calibrated rewrites ("estimated in place, beyond calibration", "estimated and copied with tag added, beyond calibration"). A stored value already equal to the estimate is counted as unchanged.
- The estimate is not checked against any measured distance. README "Estimates beyond the calibrated range" gives each lens's far end, the ratio held and the bounds on what a wrong far distance can cost; the XCD 25V ratio (about 0.24) is the least certain.
- Unchanged: the near side (magnification larger than the calibrated range) is still skipped, now labelled "skipped, closer than calibrated range"; lenses without a calibration and converter frames are still skipped; exact infinity keeps its behaviour. A thin-lens distance beyond 1 km is skipped on its own line ("skipped, computed distance beyond 1 km") rather than written.
- The undo log records `"new_kind": "estimate"` for these entries. `inspect` shows the estimate and the far end of the calibration.

- `calibrate --measured` builds a calibration from a ladder with measured distances, so it can reach past the 3 m or so where the camera stops writing its own value. Put each mark's frames in a subfolder named by the measured distance (for example `9.987m/`); the folder name is taken as the true distance and SubjectDistance is ignored, Infinity included. Each mark becomes one point.
- It refuses a folder it cannot read unambiguously: a subfolder not named as a distance (`<reading>m`), loose frames at the top level, an empty mark, more than one lens, converter frames mixed in (a maker focal-length spread above 25 percent), or two marks the magnification cannot tell apart. It warns on a frame that looks misfiled and on a mark whose frames disagree by more than 10 percent.
- It prints an overlap table: per mark, the measured distance next to the camera's own value and the shipped calibration's prediction. That table is the check that both measure from the same reference point.
- The camera's own value in the overlap table is shown wherever one exists, however far; only the "no distance recorded" marker is dropped. Both the camera and shipped columns now show the percentage off the measured distance.
- `--merge-shipped` (with `--measured`) writes `<lens>-merged.json`: every shipped point for the lens plus the measured marks beyond the shipped range. Marks inside it only feed the overlap check.
- Output goes to `<lens>-measured.json`, and it will not write into `calibration/`, because a measured ladder that starts at 1 m would drop the shipped near range. Merging the two is a separate step.

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
