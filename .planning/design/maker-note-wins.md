# Design: maker note always wins (run once, no switches)

## Goal

`python3 hb-focus-retrofit.py <folder>` does the whole job for a folder of X2D II 3FR files with no flags to learn. For every file where a distance can be computed from the maker note and the lens calibration, that computed value ends up in EXIF SubjectDistance (tag 0x9206), whatever the camera stored (feet, the Infinity value, a stale value, or a plausible one).

Why: the camera's SubjectDistance is unreliable. It is written in feet when the camera's unit is feet (the field is defined in metres), it is sometimes the Infinity value (ff ff ff ff 01 00 00 00) at close focus, and sometimes stale. Lightroom Classic and Capture One use it for lens corrections. The maker note (0x0081 effective focal length, 0x0082 magnification) is not affected by any of that.

Decisions fixed by the owner:

1. One public tool.
2. Pointing it at a folder does everything. Nothing may require a flag.
3. The maker note always wins when a distance can be computed.
4. Files that already carry the tag are edited in place (the 8-byte value only), with an undo log.
5. Files with no tag (before firmware 1.3.16.1) still get a copy, because adding the tag restructures the file. Originals of those are never opened for writing.

## Behaviour per file state

Order of checks for each `.3FR` found. The first matching row wins.

| State | Action | Counted as |
|---|---|---|
| Not parseable, or SubjectDistance tag is not RATIONAL x1 | nothing written, error line | errors |
| Maker-note f or m missing, zero, negative, or f implausible against the nominal focal length | skip, untouched | no focus data |
| Lens name has no calibration | skip, untouched | no calibration |
| m outside the calibration's measured m range (includes far focus, never extrapolated) | skip, untouched | outside calibrated range |
| Tag present, stored value equals the computed value | untouched | unchanged |
| Tag present, stored value differs | 8 bytes rewritten in place, undo log entry | rewritten in place |
| Tag absent | copy under `<folder>/retrofitted/<relative subpath>` with the tag inserted; an existing output file is never overwritten | copied with tag added (or output exists) |
| Symlinked file | skip, untouched | symlink |

Computed value: `Calibration.correct(m, thin_lens_m(f, m))`, the same call the existing `retrofit` path makes. Within the calibrated range this equals the existing clamped interpolation. Outside the range the existing path clamps; the new run skips instead ("never extrapolate", and the owner wants out-of-range frames reported, not written).

Encoding written: RATIONAL numerator `round(d * 1000)`, denominator 1000, in the file's own byte order. This is what both `write_subject_distance` (insert path) and the private script's in-place rewrite already do, so inserted and rewritten values look the same on disk. "Equals the computed value" is compared as a value (cross-multiplied), so a stored 1054/2000 counts as equal to 527/1000 and is left alone.

Folder walk: recursive, `.3fr` matched case-insensitively. Skipped: dot-directories, the top-level `retrofitted` directory (the tool's own output), symlinked directories (not followed), and files whose name starts with `._` (macOS AppleDouble sidecars written by SMB and exFAT cards; they are not photos).

## Safety checks for an in-place rewrite

1. Parse the file, record size, SubjectDistance offset and the 8 raw bytes.
2. Open `r+b`. Check `fstat` size equals the recorded size and the 8 bytes at the offset equal what the parser saw. Any difference aborts that file.
3. Append the undo log line and fsync the log. Only then touch the file.
4. Seek, write 8 bytes, flush, fsync.
5. Re-read the 8 bytes, require the new bytes; require size unchanged. On a mismatch the tool tries to put the old bytes back, then reports an error for that file.
6. Re-parse and require the readback value to equal the written value.

The tool never changes mtime. A rewritten file looks changed to backup tools and its checksum changes. That is intended and documented.

Offset sanity: the offset comes from the file, so it must satisfy `0 <= offset` and `offset + 8 <= size`. `parse_file` already raises on reads past EOF.

## Undo log

One file per run that changes something, created lazily on the first in-place change (a dry run, an all-unchanged run or a copy-only run creates none), in the folder passed on the command line:

`hb-focus-retrofit-undo-<YYYYMMDDTHHMMSSZ>-<run_id>.jsonl` (UTC timestamp, run_id is the run's full UUID).

One JSON object per line, appended and fsynced before the corresponding file is modified:

```
{"run_id": "...", "timestamp": "2026-11-18T12:00:00Z", "path": "/abs/path/B0001.3FR",
 "size": 212049920, "offset": 12345, "old_hex": "ffffffff01000000", "new_hex": "11060000e8030000",
 "old_value": 4294967295.0, "new_value": 1.553, "lens": "XCD 55V"}
```

`old_value` and `new_value` are the stored values as floats (`num/den`). `old_value` is `null` when the old denominator is zero.

Because the line is durable before the write, a crash between the log write and the file write leaves a log entry whose new bytes never landed. `undo` handles that: it only restores when the current bytes equal `new_hex`.

## `undo <logfile>`

For each entry (processed last to first):

- file missing, size differs from the logged size, or current 8 bytes equal neither old nor new: skip, report the reason;
- current bytes equal `new_hex`: write `old_hex`, flush, fsync, re-read, verify;
- current bytes already equal `old_hex` (and size matches): report "already restored", no write. This makes undo idempotent.

Exit 0 when every entry is restored or already restored, 1 when any entry was skipped or errored. Undo does not restore mtime and writes no log of its own.

## CLI

- `hb-focus-retrofit.py <folder>`: the new main path. Optional `--dry-run`: same classification and output, writes nothing, creates no log, no copies.
- `hb-focus-retrofit.py undo <logfile>`
- `retrofit`, `calibrate`, `inspect`: unchanged.
- Dispatch: if the first argument is not a known subcommand, `-h`, `--help` or `--version`, the arguments are parsed as the folder form. A folder named like a subcommand needs `./` in front.

Exit code: 0 when no file errored, 1 when any did. Skips are not errors. A folder that does not exist exits 2 with a message.

## Deliberately not done

- No flag is required for anything. There is no `--apply`, no `--include`, no `--assume-feet`.
- No unit detection. The maker note decides, so the stored unit does not matter.
- No sidecar (`.phos`) copying for in-place files (the file name does not change). Copies of tag-absent files do not copy sidecars either in the new form.
- No file locking and no handling of hard links (an in-place edit changes every link to the inode).
- No extrapolation outside the calibrated magnification range.
- No converter or extension-tube detection. The lens name does not change with a converter, so the bare-lens calibration is applied to those frames (see the existing README warning). With in-place rewriting this now replaces a camera value that may have been closer to the truth. Called out in the README and PR for the owner's decision.
- No mtime preservation or reset.
- No network access, no new dependencies, Python 3.9 compatible.

## Logging

`logger = logging.getLogger("hb-focus-retrofit")` (the module's existing logger). Each run gets `run_id = uuid.uuid4()`. INFO: run start (folder, dry-run, run_id), one line per file outcome, run summary. WARNING: skipped entries in `undo`, rollback attempts. `logger.exception` in every `except` block that handles a failure, with the state that caused it (path, offset, stored bytes, computed value). Logging to stderr is off unless `-v/--verbose` is given for the folder form, so normal output stays the per-file lines and the summary on stdout.

## Test plan

New file `tests/test_maker_note_wins.py` using the synthetic fixtures (extended with an option for a raw SubjectDistance numerator/denominator, including the Infinity bytes, and a second lens):

- dispatch: bare path runs the new flow; `--dry-run` first or last; subcommand names still dispatch; a missing folder exits 2; `main([])` still prints help and exits 2.
- walk: recursion into nested folders, case-insensitive extension, dot-directory skipped, `retrofitted` skipped, symlink skipped, `._` file ignored.
- skip reasons, each counted separately: no focus data (missing, zero), no calibration, outside range (far focus and near).
- in-place rewrite for feet, Infinity, stale and plausible-but-different stored values; written value equals the calibrated value; byte order MM too.
- all bytes outside the 8-byte field identical and size unchanged (full-file diff on a fixture).
- second run reports everything unchanged and writes nothing, creates no new log.
- verification failures: pre-write mismatch (file changed between parse and write) and post-write mismatch (fsync/readback monkeypatched) both abort that file with an error and exit code 1; post-write failure restores the old bytes.
- undo log: content of every field; written and fsynced before the file write (ordering asserted with a patched write hook); no log on dry run or when nothing changed.
- `undo`: restores exactly (byte-identical to the original); skips on mismatching current bytes; skips on size mismatch; idempotent on a second run; reports a missing file.
- tag-absent path: copy under `retrofitted/` with subfolder mirroring, original byte-identical, never overwrites an existing output, second run reports output exists.
- exit codes: 0 clean, 1 with an unreadable or corrupt file.
- existing tests: every existing test stays unchanged and passing.
