# Contributing

## Submitting a lens calibration

The most useful contribution is a calibration for a lens that isn't covered yet.

1. Update your camera's firmware to 1.3.16.1 or later. That firmware reports its own focus distance, which the calibration process fits against.
2. Shoot a ladder: minimum focus distance, then roughly every half metre out to about 3 metres, 6-8 frames, any subject, tripod optional, sharpness doesn't matter.
3. Put those frames in their own folder (one lens per folder) and run:

```
python3 hb-focus-retrofit.py calibrate --source /path/to/ladder --out my-lens.json
```

4. Check the printed residuals. Under 2% is good. If residuals are high, check that the ladder actually spans minimum focus to 3 m and that firmware was 1.3.16.1+ for every frame.
5. Submit it one of two ways:
   - **GitHub issue**: open a new issue titled "Calibration submission: <lens name>", attach the JSON file, and fill in the template below.
   - **Pull request**: add the file at `calibration/<lens-name>.json` and open a PR.

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
