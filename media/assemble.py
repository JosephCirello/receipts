"""Cut the demo video: one segment per scene, timed to its narration, captions burned in.

  python media/assemble.py            # needs media/build/vo (tts.py), media/takes (record.py), media/build/slides

Takes are sped up (never slowed below real time) to fit the narration, then hold on
their last frame. Cards get a slow push-in. Output: media/build/receipts_demo.mp4
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
B = HERE / "build"
SEG = B / "segments"
PAD = 0.7          # breath after each line
FPS = 30


def dur(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return float(r.stdout.strip())


def ass(text: str, t: float, path: Path):
    def ts(x):
        h, m, s = int(x // 3600), int(x % 3600 // 60), x % 60
        return f"{h}:{m:02d}:{s:05.2f}"
    path.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Cap,Segoe UI Semibold,40,&H00FFFFFF,&H00FFFFFF,&H00241C14,&H96241C14,0,0,0,0,100,100,0,0,3,14,0,2,160,160,46,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        f"Dialogue: 0,{ts(0.15)},{ts(max(0.5, t - 0.1))},Cap,,0,0,0,,{text}\n", encoding="utf-8")


def run(cmd):
    r = subprocess.run(cmd, cwd=str(SEG), capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(r.stderr[-2000:])


def main():
    plan = json.loads((HERE / "script.json").read_text(encoding="utf-8"))
    SEG.mkdir(parents=True, exist_ok=True)
    listing = []
    t_total = 0.0
    for i, s in enumerate(plan["scenes"]):
        vo = B / "vo" / f"{s['id']}.mp3"
        T = round(dur(vo) + PAD + (1.4 if i == len(plan["scenes"]) - 1 else 0), 2)
        sub = f"cap_{i:02d}.ass"
        ass(s["caption"], T, SEG / sub)
        out = f"seg_{i:02d}.mp4"
        common_a = ["-i", str(vo)]
        if "take" in s["visual"]:
            src = HERE / "takes" / f"{s['visual']['take']}.webm"
            start = float(s["visual"].get("start", 0))            # skip the page load at the head of a take
            f = max(1.0, min(3.0, (dur(src) - start) / T))
            vf = (f"[0:v]setpts=PTS/{f:.4f},fps={FPS},scale=1920:1080,tpad=stop_mode=clone:stop_duration=20,"
                  f"trim=duration={T},setpts=PTS-STARTPTS,subtitles={sub}[v]")
            cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", str(src)] + common_a
        else:
            src = B / "slides" / f"{s['visual']['slide']}.png"
            frames = int(T * FPS)
            vf = (f"[0:v]scale=3840:2160,zoompan=z='1+0.035*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1920x1080:fps={FPS},"
                  f"trim=duration={T},setpts=PTS-STARTPTS,subtitles={sub}[v]")
            cmd = ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS), "-t", str(T), "-i", str(src)] + common_a
        cmd += ["-filter_complex", vf + f";[1:a]apad,atrim=duration={T},asetpts=PTS-STARTPTS[a]",
                "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
                "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", out]
        run(cmd)
        listing.append(f"file '{out}'")
        t_total += T
        print(f"{i:02d} {s['id']:9s} {T:5.2f}s  total {t_total:6.2f}s", flush=True)
    (SEG / "list.txt").write_text("\n".join(listing) + "\n", encoding="utf-8")
    final = B / "receipts_demo.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "-movflags", "+faststart", str(final)])
    print(f"wrote {final}  ({dur(final):.1f}s)")


if __name__ == "__main__":
    main()
