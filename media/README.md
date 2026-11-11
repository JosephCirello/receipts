# The demo video, rebuilt from the working product

Everything on screen is the real app recorded by Playwright, or a card rendered from `slides.html`. Nothing is mocked up. Two shots lay a strip of real footage on a plain background: the opening puts the card's words above the app's own "Without Receipts" strip from a take, and the shot that ends the fix is the app's own two-sentence summary of the day, recorded in a narrow window (where the app puts the two sentences on two lines) with the rest of the page covered. The red rings and two sound effects (a bell and a key tap, made from sine waves by `sfx/make_sfx.py`) are added in the edit.

The video carries no captions in its picture. The narration goes with it as a captions file, word for word, for the viewer to switch on (YouTube's CC button): upload `media/build/receipts_demo.srt` with the video.

```bash
uvicorn app:app --port 8090                      # the app (sandbox mode if PayPal keys are set)
python examples/mcp_client_demo.py > media/mcp_demo_output.txt   # real MCP output for the terminal scene (fresh server)
python media/record.py all                       # every take (media/takes/*.webm), card (media/build/slides/*.png) and red ring (media/build/rings)
python media/sfx/make_sfx.py                     # the two sound effects, synthesised (media/sfx/SOURCE.md); the WAV files are committed
python media/tts.py                              # narration, Edge neural voice "Andrew" (run with an interpreter that has edge-tts)
python media/qa_voice.py                         # listen back with faster-whisper: words in the script that were not heard
python media/assemble.py                         # media/build/receipts_demo.mp4 (voice and music) and receipts_demo_sfx.mp4 (the same pictures with the two sounds); no captions in the picture
python media/captions.py                         # media/build/receipts_demo.srt and .vtt: the narration, word for word, timed to the cut (assemble.py runs this too)
python media/stated_numbers.py                          # every number the video and README state, from results/episodes_scored.jsonl
```

`script.json` is the cut: one scene per narration line, each with its visual (a take or a card), an optional start trim and an optional camera (a zoom onto the one line that matters; the options are listed at the top of `assemble.py`). Takes are recorded at 3840x2160, the page magnified 2x in a window twice the size, so a zoomed shot stays sharp; a finger dot is drawn where a click lands, because a headless browser has no cursor. Takes are only ever sped up to fit their line, never slowed.

The stopped-refund scene is a take of a real narrow window (`claims_narrow`, 724 page pixels wide on a screen with 3 device pixels to a page pixel; nothing is magnified and nothing is added to the page), because at that width the app wraps both of its reasons onto two whole lines each. The scene ends before the day's next line arrives.

Words hold still. A card is shown exactly as it was rendered and does not move, and a camera on a take is placed to a fraction of a pixel (ffmpeg's `perspective` filter) and then brought down to size once. Through Draft 22 the cards had a slow push-in and the camera was `zoompan`, which puts its frame on whole pixels: on a large screen the words on every card crept and snapped back most of a pixel two or three times a second, and each camera move landed with a shake of a pixel or two. A phone screen hides it. `python media/steady.py <video> <from> <to> <x:y:w:h>` measures it (needs numpy): a still shot reads 0.00, a camera move reads steps that shrink evenly to zero.

The last step of the mix is one plain gain on the whole sound track (`MASTER_GAIN_DB` in `assemble.py`, +4.5 dB), with no compressor or limiter, to bring the video up to about -16 LUFS with its true peak under -1 dBTP; `assemble.py` reads both back off each finished file and prints them.

`"burn_captions": false` in `script.json` keeps captions out of the picture; each scene's short `"caption"` is drawn in only if that is set to true. The captions file is written by `captions.py` from each line's `"say"`: at most two lines of 42 characters to a cue, each up for 1 to 6 seconds, timed from where the words are spoken in the cut. The numbers the voice spells out are written the way the cards write them ("thirty-eight times" becomes "38 times"; the full list is `NUMBERS` in `captions.py`), no other word is changed, and the script stops if the captions and the narration ever differ.

If a number in `stated_numbers.py` changes, the narration, `NUMBERS` in `captions.py`, `slides.html` and the README change with it.
