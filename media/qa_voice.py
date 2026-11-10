"""Listen back: transcribe each narration clip and show it beside the script, to catch mispronunciations.
Run with the voice venv:  C:\\Users\\joeci\\Desktop\\voice_check\\venv\\Scripts\\python.exe media/qa_voice.py [scene_id ...]"""
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

from faster_whisper import WhisperModel

HERE = Path(__file__).resolve().parent
plan = json.loads((HERE / "script.json").read_text(encoding="utf-8"))
m = WhisperModel("medium.en", device="cpu", compute_type="int8")


def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower().replace("-", " "))


only = set(sys.argv[1:])
for s in plan["scenes"]:
    if only and s["id"] not in only:
        continue
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(HERE / "build" / "vo" / f"{s['id']}.mp3"), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True).stdout
    segs, _ = m.transcribe(np.frombuffer(raw, dtype=np.float32), language="en")
    heard = " ".join(x.text.strip() for x in segs)
    a, b = norm(s["say"]).split(), norm(heard).split()
    miss = [w for w in a if w not in b]
    print(f"[{s['id']}] heard: {heard}")
    if miss:
        print(f"   words in the script not heard: {miss}")
