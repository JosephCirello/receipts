# The demo video, rebuilt from the working product

Everything on screen is the real app recorded by Playwright, or a card rendered from `slides.html`. Nothing is mocked up.

```bash
uvicorn app:app --port 8090                      # the app (sandbox mode if PayPal keys are set)
python examples/mcp_client_demo.py > media/mcp_demo_output.txt   # real MCP output for the terminal scene (fresh server)
python media/record.py all                       # every take (media/takes/*.webm) and card (media/build/slides/*.png)
python media/tts.py                              # narration, Edge neural voice "Andrew" (run with an interpreter that has edge-tts)
python media/qa_voice.py                         # listen back with faster-whisper: words in the script that were not heard
python media/assemble.py                         # media/build/receipts_demo.mp4, captions burned in
python media/numbers.py                          # every number the video and README state, from results/episodes_scored.jsonl
```

`script.json` is the cut: one scene per narration line, each with its visual (a take or a card), an optional start trim and an optional slow zoom. Takes are only ever sped up to fit their line, never slowed. If a number in `numbers.py` changes, the narration, the captions, `slides.html` and the README change with it.
