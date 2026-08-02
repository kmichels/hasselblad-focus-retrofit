# Evidence

This tool makes claims that are easy to state and easy to get wrong: that it reads real focus-distance data out of RAW files, that it writes it back correctly, that Lightroom and Capture One actually use it, and that Phocus is unaffected. This page lays out how each claim was checked, and when, so you don't have to take it on faith.

## Maker-note fields exist and behave as described

Verified 2026-07-02. The X2D II writes focus-related data into two maker-note fields (`0x0081`, `0x0082`) on firmware 1.2.7.11 through the last pre-1.3.16.1 release, plus a standard EXIF `SubjectDistance` tag from 1.3.16.1 onward. This was confirmed behaviorally, not just by field presence: values were cross-checked against physical focus distance across a range of subject distances and lenses, and tracked correctly as focus changed.

## Lightroom Classic and Capture One actually use SubjectDistance

Verified 2026-07-26 against Lightroom Classic 15.4.1 and Capture One 16.8.4. This wasn't just "the field is present in metadata," it was confirmed that both applications *read and use* the value for distance-dependent lens correction:

- **Render-diff evidence**: the same RAW file processed once with SubjectDistance present and once without produced visibly different lens-correction geometry in both applications, isolating the field as the cause.
- **Geometry evidence**: the corrected geometry with SubjectDistance present matched what physical optics predicts for that focus distance; the version without it defaulted to far-field correction regardless of actual focus distance.

## Retrofit write is byte-surgical

Verified 2026-08-01. The write does not rewrite the file. It appends a small data block and repoints four bytes in the existing EXIF structure to reference it, leaving the rest of the file bit-for-bit identical. Confirmed by:

- Diffing the original and retrofitted files: only the appended block and the four repointed bytes differed.
- Running exiftool against the retrofitted file and confirming it reports the correct SubjectDistance value with no other field changes or corruption warnings.

## Phocus is unaffected

Verified 2026-08-01 via a crossover test: the same file was opened in Phocus 4.2.1 before and after retrofitting. The rendered output was bit-exact in both cases. Phocus does not read the SubjectDistance field this tool writes, it calculates focus-dependent corrections through its own internal path, so adding the field has no effect on how Phocus renders the image.

## Visible difference on a real-world old-firmware frame

Verified 2026-08-02. Beyond the render-diff test above (which isolates the field in a controlled comparison), a genuine close-focus frame shot on pre-1.3.16.1 firmware was retrofitted and re-imported into Lightroom Classic. The lens-correction geometry visibly changed for the better compared to the same frame without the retrofit, confirming the effect holds on a real shot, not only a synthetic test case.

## 55V calibration ladder

Measured 2026-08-02. A 9-frame distance ladder was shot with the XCD 55V lens on firmware 1.3.16.1 or later (which reports its own focus distance), comparing the raw thin-lens formula this tool starts from against the camera's own reported value at each distance:

| Distance | Raw formula error vs. camera value |
|---|---|
| 0.44 m | -15% |
| 0.62 m | -12.5% |
| 1.10 m | -8.5% |
| 1.48 m | -5.7% |
| 2.14 m | +0.2% |
| 2.91 m | +8.2% |

This is the basis for the shipped XCD 55V calibration, and for the UNCALIBRATED warning shown for lenses without a calibration file, since the table above shows the raw formula alone can be off by double-digit percentages at close range.

## Camera coverage

Verified only on the Hasselblad X2D II (100C sensor). The tool gates on the presence of the expected maker-note data rather than checking the camera model string, so other Hasselblad bodies with similar maker-note structures may work, but this has not been tested or confirmed on any body other than the X2D II.

---

<!-- blog post URL when live -->
