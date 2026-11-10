# The demo video, rebuilt from the working product

Everything on screen is the real app recorded by Playwright, or a card rendered from `slides.html`. Nothing is mocked up. Two shots lay a strip of real footage on a plain background: the opening puts the card's words above the app's own "Without Receipts" strip from a take, and the line that ends the fix is the app's own summary line with the rest of the page covered. The red rings and two sound effects (a bell and a key tap, made from sine waves by `sfx/make_sfx.py`) are added in the edit.

```bash
uvicorn app:app --port 8090                      # the app (sandbox mode if PayPal keys are set)
python examples/mcp_client_demo.py > media/mcp_demo_output.txt   # real MCP output for the terminal scene (fresh server)
python media/record.py all                       # every take (media/takes/*.webm), card (media/build/slides/*.png) and red ring (media/build/rings)
python media/sfx/make_sfx.py                     # the two sound effects, synthesised (media/sfx/SOURCE.md); the WAV files are committed
python media/tts.py                              # narration, Edge neural voice "Andrew" (run with an interpreter that has edge-tts)
python media/qa_voice.py                         # listen back with faster-whisper: words in the script that were not heard
python media/assemble.py                         # media/build/receipts_demo.mp4 (voice and music) and receipts_demo_sfx.mp4 (the same pictures with the two sounds), captions burned in
python media/stated_numbers.py                          # every number the video and README state, from results/episodes_scored.jsonl
```

`script.json` is the cut: one scene per narration line, each with its visual (a take or a card), an optional start trim and an optional camera (a zoom onto the one line that matters; the options are listed at the top of `assemble.py`). Takes are recorded at 3840x2160, the page magnified 2x in a window twice the size, so a zoomed shot stays sharp; a finger dot is drawn where a click lands, because a headless browser has no cursor. Takes are only ever sped up to fit their line, never slowed. If a number in `stated_numbers.py` changes, the narration, the captions, `slides.html` and the README change with it.
