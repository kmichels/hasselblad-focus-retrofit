# Privacy

Short version: the tool collects nothing and sends nothing. The only information this project ever receives is what you deliberately choose to send, and files you send for analysis are deleted once they have been looked at.

## The tool itself sends nothing

`hb-focus-retrofit.py` has no networking code. It cannot phone home, check for updates, report usage, or transmit your files, because it contains nothing capable of making a network connection.

You do not have to take that on faith. Open the file in any text editor and search it for `urllib`, `socket`, `requests`, and `http`. The only match is the project's own GitHub address in a comment at the top. There is no analytics, no telemetry, and no license check.

Everything the tool does happens on your own computer, against files already on your own disk.

## What this project receives

Only what you send it. There are exactly two ways that happens, and both are things you start.

### Calibration files you submit

A calibration file is a small JSON document. Here is everything one contains:

- the lens name as your camera recorded it, for example `XCD 90V`
- a list of numbers: magnification, focal length, and focus distance for each frame in your ladder
- the camera body and firmware version your ladder was shot on
- how many frames it was built from, and the date
- a contributor name, only if you passed `--contributor` when you generated it

The measurements are optical numbers. They say nothing about you, where you were, or what you photographed.

The one field that is personal is the contributor name, and only because you chose to type it in. It exists so you can be credited. If you submit a calibration, that name is published in this repository. If you would rather stay anonymous, leave `--contributor` off and the field stays empty, which affects nothing about how the calibration works.

### Files you email

If you email a calibration or a question, that email arrives with your email address on it, the same as any email. It is used to reply to you and nothing else. It is never added to a mailing list, never sold, and never passed to anyone.

## RAW files sent for analysis

Sometimes working out why the tool skipped a file, or why a lens behaves oddly, means looking at an actual RAW file. If you send one:

- **It is deleted once the analysis is done.** At the outside, no submitted file is kept longer than 30 days, whether the analysis finished or not.
- **It is never shared with anyone,** never published, and never posted in an issue or a blog post.
- **It is analyzed locally and mechanically,** on a personal computer, using scripts that read metadata. It is not uploaded to a cloud service, not fed to any third party, and not used to train anything.

Be aware of what a RAW file carries, because it is more than the picture. Hasselblad 3FR files include your camera's serial number, and if you shoot with location tagging enabled they can include GPS coordinates of where the frame was taken. That is exactly why submitted files are deleted rather than kept, and why they are never shared.

If you would rather not send a whole RAW, the `inspect` command prints the specific fields that matter, and pasting that text is usually enough:

```
python3 hb-focus-retrofit.py inspect YOURFILE.3FR
```

Its output contains the camera model, firmware version, lens name, and the optical numbers. No serial number and no location.

## What this project never does

- No analytics, telemetry, or usage tracking, in the tool or anywhere else.
- No cookies, because there is no website here, only this repository.
- No selling, renting, or sharing of anything anyone sends.
- No third-party processors. Nothing submitted is passed to an outside service.

## Removing something you sent

If you submitted a calibration and want your name taken off it, or want the whole thing removed, email **hasselblad@agentmail.to** and it will be removed from the repository. No reason needed.

## Questions

Email **hasselblad@agentmail.to**.

This policy covers this tool and the calibration submissions around it. It was last updated on August 2, 2026.
