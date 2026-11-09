"""Narration: one clip per scene, Microsoft Edge neural voice "Andrew" (edge-tts), with word timings.

Run with the interpreter that has edge-tts installed:
  C:\\Users\\joeci\\Desktop\\voice_check\\venv\\Scripts\\python.exe media/tts.py [scene_id ...]
Writes media/build/vo/<scene>.mp3, <scene>.json (word timings) and durations.json.
"""
import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

import edge_tts

HERE = Path(__file__).resolve().parent
OUT = HERE / "build" / "vo"
SPEAK = {"MCP": "M C P", "Potestas AI": "po TEST us AI", "AI": "A I"}


def speak_text(line: str) -> str:
    s = line
    for k in sorted(SPEAK, key=len, reverse=True):
        s = re.sub(r"(?<![\w$/])" + re.escape(k) + r"(?![\w/])", SPEAK[k], s)
    return s


def duration(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


async def one(sid: str, text: str, voice: str, rate: str):
    for attempt in range(5):
        try:
            com = edge_tts.Communicate(speak_text(text), voice, rate=rate, boundary="WordBoundary")
            words, audio = [], bytearray()
            async for ch in com.stream():
                if ch["type"] == "audio":
                    audio += ch["data"]
                elif ch["type"] == "WordBoundary":
                    words.append({"word": ch["text"], "start": ch["offset"] / 1e7, "end": (ch["offset"] + ch["duration"]) / 1e7})
            if audio:
                break
        except Exception as e:  # noqa: BLE001
            print("retry", sid, type(e).__name__, e)
            await asyncio.sleep(4 * (attempt + 1))
    else:
        raise SystemExit(f"no audio for {sid}")
    (OUT / f"{sid}.mp3").write_bytes(bytes(audio))
    (OUT / f"{sid}.json").write_text(json.dumps({"scene": sid, "spoken": speak_text(text), "words": words}, indent=1), encoding="utf-8")
    await asyncio.sleep(1.0)


async def main():
    plan = json.loads((HERE / "script.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    dfile = OUT / "durations.json"
    durs = json.loads(dfile.read_text(encoding="utf-8")) if dfile.exists() else {}
    for s in plan["scenes"]:
        if only and s["id"] not in only:
            continue
        await one(s["id"], s["say"], plan["voice"], plan.get("rate", "+0%"))
        durs[s["id"]] = round(duration(OUT / f"{s['id']}.mp3"), 2)
        print(f"{s['id']:10s} {durs[s['id']]:5.2f}s  {s['say'][:70]}", flush=True)
    dfile.write_text(json.dumps(durs, indent=1), encoding="utf-8")
    print(f"total narration {sum(durs.values()):.1f}s")


asyncio.run(main())
