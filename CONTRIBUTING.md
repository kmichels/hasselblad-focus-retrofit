# Contributing

## Submitting a lens calibration

The most useful contribution is a calibration for a lens that isn't covered yet.

1. Update your camera's firmware to 1.3.16.1 or later. That firmware reports its own focus distance, which the calibration process fits against.
2. Shoot a ladder: about 10 frames spread between minimum focus distance and roughly 3 meters, shot wide open. The steps do not have to be evenly spaced. Any subject, tripod optional, sharpness doesn't matter. Note that the distance the calibration fits against is the camera's own value, which I only verified against a laser out to 1.5 m (see the README's "Current limitations"), so the far rungs of a ladder inherit its shortfall. Never mix bare-lens and converter or extension-tube frames in the same ladder folder: `derive_calibration` groups frames only by the lens name in the file, so a bare lens and that same lens with a converter attached (which report the same name but have different effective focal lengths) will get silently fit into one bad curve instead of two correct ones. Shoot and submit them as separate lens folders.
3. Don't submit calibrations for the XCD 20-35E or XCD 35-100E zooms right now. The calibration model is one curve per lens keyed on magnification, which assumes a fixed focal length. A ladder shot at one focal length on a zoom would produce a curve that's correct at that setting and wrong everywhere else on the zoom range, which the tool has no way to detect or warn about once it's in `calibration/`. Same root cause as the converter case above: the calibration key is the lens name only, and it doesn't capture what changed the optics. Zoom support needs a calibration surface across focal length, not a single curve, and that's not built yet.
4. Put those frames in their own folder (one lens per folder) and run:

```
python3 hb-focus-retrofit.py calibrate --source /path/to/ladder --out my-lens.json --contributor "Your Name"
```

`--contributor` records your name or handle in the calibration file so you get credit for it. If you leave it off, the tool will remind you to re-run with it before you submit.

The tool prints the absolute path of the file it wrote, e.g. `wrote /Users/you/Desktop/my-lens.json (7 points, lens XCD 90V)`. That is the file you attach or paste in step 6.

5. Check the printed residuals. Under 2% is good. If residuals are high, check that the ladder actually spans minimum focus to 3 m and that firmware was 1.3.16.1+ for every frame.
6. Submit it one of three ways, easiest first:
   - **Email** (no GitHub account needed): send the JSON file to **hasselblad@agentmail.to** with subject "Calibration submission: <lens name>". Attach the file (it's plain JSON, email attachments handle that fine) and include the same template fields below in the body.
   - **GitHub issue**: open a new issue titled "Calibration submission: <lens name>", paste the JSON file's contents into the issue body inside a fenced code block, and fill in the template below. GitHub may reject a raw `.json` attachment, but pasting always works. If you'd rather attach a file, zip it first.
   - **Pull request**: add the file at `calibration/<lens-name>.json` and open a PR. Requires a GitHub account.

### Calibration submission template

Paste this into the issue body and fill in each field:

```
Lens: (e.g. XCD 90V)
Camera body: (e.g. X2D II 100C)
Firmware version used for the ladder: (e.g. 1.3.16.1)
Number of frames: (e.g. 7)
Residuals reported by `calibrate`: (paste the output)
Any notes on shooting conditions:
```

Fill in every field. Calibrations without a firmware version or residual numbers can't be trusted and will be sent back for more data.

## Local developer validation

Run the test suite:

```
pytest
```

Some tests need a real 3FR file to validate against actual maker-note data rather than synthetic fixtures. Point `HB_REAL_3FR` at one before running:

```
HB_REAL_3FR=/path/to/sample.3FR pytest
```

To cross-check what the tool reads against what's actually in the file, compare `inspect` output to a direct exiftool read of the same maker-note tags:

```
exiftool -j -U -Unknown_0x0081 -Unknown_0x0082 -SubjectDistance file.3FR
python3 hb-focus-retrofit.py inspect file.3FR
```

The magnification-related values should match between the two.

## Code style

- Standard library only. No third-party dependencies.
- Single file (`hb-focus-retrofit.py`). Keep it that way rather than splitting into a package, it's meant to be readable end to end by anyone auditing it.
- Every change needs a test. If you're fixing a bug, add a test that fails before your fix and passes after.
- Run `pytest` before opening a PR. CI runs on Python 3.9 and 3.12, so avoid syntax or stdlib features newer than 3.9.
