# Submission media

Three binaries ship here. **Two of them — `cover.png` and `slides.pdf` — are
generated from plain-text HTML in `src/`**, so they can be reproduced byte-for-byte
by anyone with Chrome; nothing about them was hand-edited in a binary editor.
The third, `demo.mp4`, is a recording, and that difference is the whole subject of
the *Honest limits* section below.

| File | Format | Check it yourself |
|---|---|---|
| `cover.png` | PNG · 1920×1080 (exactly 16:9) | `python3 -c "import struct,io;d=io.open('cover.png','rb').read();print(struct.unpack('>II',d[16:24]))"` |
| `slides.pdf` | PDF · 11 pages · MediaBox 1440×810 pt (16:9) | `python3 -c "import io,re;d=io.open('slides.pdf','rb').read();print(len(re.findall(rb'/Type\s*/Page[^s]',d)))"` |
| `demo.mp4` | MP4 (`major_brand=isom`) · 256.83 s · 1920×1080 · h264 + aac 24 kHz mono | `ffprobe -v error -show_entries format=duration:stream=codec_name,width,height -of default=nw=1 demo.mp4` |
| `demo.srt` | SubRip · 78 cues | `grep -c '^[0-9]\+$' demo.srt` |

## Rebuilding them

```sh
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless --disable-gpu --hide-scrollbars --window-size=1920,1080 \
  --screenshot="$PWD/cover.png" "file://$PWD/src/cover.html"
"$CHROME" --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="$PWD/slides.pdf" "file://$PWD/src/slides.html"
```

Note that the two Chrome paths are **not** interchangeable: `--print-to-pdf` and
`--screenshot` render some CSS differently, which is why `src/cover.html` avoids
`-webkit-background-clip`.

## Why there is a `verify.sh`

A reviewer looking at a PNG and a PDF has no way to tell what is in them without
opening them, and no way to tell whether they still correspond to the source in
this repository. Text-scanning tools cannot help: PNG is raster — there is no text
in it at all — and PDF text sits inside `FlateDecode` streams, so a byte-level scan
reads nothing. **Whatever you can verify about the rest of this repository by
reading it, you cannot verify about these two files by reading them.**

`verify.sh` closes that gap by re-rendering `src/*.html` and comparing against what
is on disk: PNG byte-for-byte, PDF after normalising `/CreationDate` and `/ModDate`
(measured: those 8 bytes are the *only* difference between two renders of the same
source).

**It has teeth — mutation-tested:**

| Mutation | Result |
|---|---|
| change one visible word in `src/cover.html` | 🔴 FAIL |
| change one visible number in `src/slides.html` | 🔴 FAIL |
| append one byte to `cover.png` | 🔴 FAIL |
| append one byte to `slides.pdf` | 🔴 FAIL |
| revert everything | ✅ PASS |

⚠ **One arm carried no information, and saying so is the point.** Appending an HTML
comment to the source still PASSes — correctly, since the render is unchanged and
the equality still holds. An arm that *should* be green proves nothing about a check
that is supposed to go red; it is not evidence and is not counted as such.

## Honest limits

1. `verify.sh` proves **artifact = render(this source)**. It does not prove the
   source is *correct* — only that the binary you are looking at is the one this
   text produces.
2. **It covers exactly two named files: `cover.png` and `slides.pdf`.** `demo.mp4`
   is a screen/page recording, so there is no source it can be re-rendered from and
   `verify.sh` does not touch it. Concretely, about the video you can check the
   container, duration, resolution and codecs with the `ffprobe` line above — and
   nothing else mechanically. **What is in the picture can only be established by
   watching it.** We watched it; you should not take that as a check you performed.
3. **`demo.srt` narrows that gap on one axis only — audio, not picture.** It is not a
   transcript produced after the fact: it is the text that was fed to the
   text-to-speech engine, so the narration track is that text by construction. As a
   cross-check we ran speech recognition back over that narration and measured a
   **2.94% word error rate**. Be precise about what that number covers: it was
   measured on the narration render (a 257.69 s MP3) *before* the cut was assembled
   and the audio re-encoded to AAC, so it is evidence about the voice track, not
   about the 256.83 s file you have. It is also a number we measured, not one you can
   read off this repository — redoing it means running an ASR pass yourself. Neither
   the SRT nor the WER says anything about what is on screen at any given second.
4. The underlying difficulty is not fixed, only routed around. Reading text out of
   a PDF is possible (decompress the streams first); reading it out of a raster PNG
   needs OCR and is not practical. Neither is done here.
