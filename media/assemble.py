"""Cut the demo video: one segment per scene, timed to its narration, captions burned in.

  python media/assemble.py            # needs media/build/vo (tts.py), media/takes (record.py), media/build/slides

Takes are sped up (never slowed below real time) to fit the narration, then hold on
their last frame. Cards get a slow push-in. Output: media/build/receipts_demo.mp4

What a scene in script.json may carry, beyond its line, caption and visual:
  "lead": seconds of picture before the voice starts; "tail": seconds of picture added after it.
  visual "start": where in the take the scene begins; "speed": play the take at exactly this speed
    (1 = real time) instead of fitting what is left of it to the line.
  visual "focus": the camera on a take. Either the simple form {"from", "zoom", "cx", "cy", "still"},
    or {"keys": [[second, zoom, x, y], ...]}: at each second of the scene the camera is at that zoom,
    centred on that point of the 1920x1080 page, and it eases from one key to the next.
  visual "then": a second picture for the rest of the same line, {"at": second, ...a visual...},
    with its own optional "caption" from that second on.
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


def ass(lines, path: Path):
    """Captions for one scene: a list of (text, from second, to second)."""
    def ts(x):
        h, m, s = int(x // 3600), int(x % 3600 // 60), x % 60
        return f"{h}:{m:02d}:{s:05.2f}"
    path.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Cap,Segoe UI Semibold,40,&H00FFFFFF,&H00FFFFFF,&H00241C14,&H96241C14,0,0,0,0,100,100,0,0,3,14,0,2,160,160,46,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        + "".join(f"Dialogue: 0,{ts(a)},{ts(max(a + 0.35, b))},Cap,,0,0,0,,{text}\n" for text, a, b in lines), encoding="utf-8")


def run(cmd):
    r = subprocess.run(cmd, cwd=str(SEG), capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(r.stderr[-2000:])


def eased(keys, col):
    """One camera value over the scene, as an ffmpeg expression in the output frame number: it holds each key's
    value and eases (smoothstep) to the next."""
    pts = [(int(round(k[0] * FPS)), float(k[col])) for k in keys]
    expr = f"{pts[-1][1]:.4f}"
    for (n0, v0), (n1, v1) in reversed(list(zip(pts, pts[1:]))):
        u = f"((on-{n0})/{max(1, n1 - n0)})"
        seg = f"{v0:.4f}" if v0 == v1 else f"({v0:.4f}+({v1 - v0:.4f})*{u}*{u}*(3-2*{u}))"
        expr = f"if(lt(on,{n1}),{seg},{expr})"
    return f"if(lt(on,{pts[0][0]}),{pts[0][1]:.4f},{expr})"


def camera(fo, d):
    """The zoompan filter for a take's focus (the take is 3840x2160 by then; the picture out is 1920x1080)."""
    if "keys" in fo:
        z, cx, cy = (eased(fo["keys"], c) for c in (1, 2, 3))
        return (f",zoompan=z='{z}':x='max(0,min(iw-iw/zoom,({cx})*iw/1920-iw/zoom/2))'"
                f":y='max(0,min(ih-ih/zoom,({cy})*ih/1080-ih/zoom/2))':d=1:s=1920x1080:fps={FPS}")
    n0, z = int(fo["from"] * d * FPS), fo["zoom"]
    step = (z - 1) / max(1, int(0.35 * d * FPS))
    zexpr = f"{z}" if fo.get("still") else f"if(lt(on,{n0}),1,min(1+(on-{n0})*{step:.5f},{z}))"   # still: a fixed crop, no push-in
    return f",zoompan=z='{zexpr}':x='(iw-iw/zoom)*{fo['cx']}':y='(ih-ih/zoom)*{fo['cy']}':d=1:s=1920x1080:fps={FPS}"


def picture(v, d, i):
    """One picture held for d seconds: its ffmpeg input, and the filter chain from input i to [p<i>]."""
    if "take" in v:
        src = HERE / "takes" / f"{v['take']}.webm"
        start = float(v.get("start", 0))            # skip the page load at the head of a take
        f = float(v["speed"]) if "speed" in v else max(1.0, min(3.0, (dur(src) - start) / d))
        fo = v.get("focus")
        # a take only stores a frame when the page changes, so it is laid out at an even frame rate first:
        # the scene then starts on exactly what was on screen at `start`, not on the next change after it
        chain = (f"[{i}:v]fps={FPS},trim=start={start:.3f},setpts=(PTS-STARTPTS)/{f:.4f},fps={FPS},"
                 f"scale={'3840:2160' if fo else '1920:1080'}:flags=lanczos,"
                 f"tpad=stop_mode=clone:stop_duration=20,trim=duration={d},setpts=PTS-STARTPTS{camera(fo, d) if fo else ''}[p{i}]")
        return ["-i", str(src)], chain
    src = B / "slides" / f"{v['slide']}.png"
    frames = int(d * FPS)
    chain = (f"[{i}:v]scale=3840:2160,zoompan=z='1+0.035*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1920x1080:fps={FPS},"
             f"trim=duration={d},setpts=PTS-STARTPTS[p{i}]")
    return ["-loop", "1", "-framerate", str(FPS), "-t", f"{d + 0.2:.2f}", "-i", str(src)], chain


def main(only=()):
    plan = json.loads((HERE / "script.json").read_text(encoding="utf-8"))
    SEG.mkdir(parents=True, exist_ok=True)
    listing, times = [], []
    t_total = 0.0
    for i, s in enumerate(plan["scenes"]):
        vo = B / "vo" / f"{s['id']}.mp3"
        lead, tail = float(s.get("lead", 0)), float(s.get("tail", 0))
        T = round(lead + dur(vo) + PAD + tail + (1.4 if i == len(plan["scenes"]) - 1 else 0), 2)
        out = f"seg_{i:02d}.mp4"
        listing.append(f"file '{out}'")
        times.append({"scene": s["id"], "start": round(t_total, 2), "length": T})
        t_total += T
        if only and s["id"] not in only:            # python media/assemble.py <scene id ...>: recut only these scenes
            continue
        v = s["visual"]
        then = v.get("then")
        parts = [(v, round(float(then["at"]), 2)), (then, round(T - float(then["at"]), 2))] if then else [(v, T)]
        caps = [(s["caption"], 0.15, (float(then["at"]) if then and "caption" in then else T) - 0.1)] if s["caption"] else []
        if then and then.get("caption"):
            caps.append((then["caption"], float(then["at"]) + 0.1, T - 0.1))
        sub = f"cap_{i:02d}.ass"
        ass(caps, SEG / sub)
        cmd, chains = ["ffmpeg", "-y", "-v", "error"], []
        for k, (pv, d) in enumerate(parts):
            inp, chain = picture(pv, d, k)
            cmd += inp
            chains.append(chain)
        joined = "".join(f"[p{k}]" for k in range(len(parts)))
        chains.append(f"{joined}concat=n={len(parts)}:v=1:a=0,subtitles={sub}[v]" if len(parts) > 1 else f"[p0]subtitles={sub}[v]")
        late = f"adelay={int(lead * 1000)}:all=1," if lead else ""
        chains.append(f"[{len(parts)}:a]{late}apad,atrim=duration={T},asetpts=PTS-STARTPTS[a]")
        cmd += ["-i", str(vo), "-filter_complex", ";".join(chains),
                "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
                "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-t", f"{T}", out]
        run(cmd)
        print(f"{i:02d} {s['id']:9s} starts {t_total - T:6.2f}s  {T:5.2f}s  total {t_total:6.2f}s", flush=True)
    (SEG / "list.txt").write_text("\n".join(listing) + "\n", encoding="utf-8")
    (B / "timings.json").write_text(json.dumps(times, indent=1), encoding="utf-8")
    final = B / "receipts_demo.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "-movflags", "+faststart", str(final)])
    print(f"wrote {final}  ({dur(final):.1f}s)")
    music = HERE / "music" / "bed.mp3"          # provenance in media/music/SOURCE.md
    if music.exists():
        add_music(final, music)


def add_music(final: Path, music: Path):
    """Lay the instrumental bed under the narration: quiet, faded in and out, and ducked a little
    further whenever the voice speaks (sidechain), so no word is ever covered. The voice-only cut is
    kept beside it."""
    T = dur(final)
    quiet = final.with_name(final.stem + "_voice_only.mp4")
    quiet.write_bytes(final.read_bytes())
    fc = (f"[1:a]atrim=0:{T:.2f},asetpts=PTS-STARTPTS,afade=t=in:st=0:d=2.5,afade=t=out:st={max(0, T - 4):.2f}:d=4,volume=0.14[m];"
          f"[m][0:a]sidechaincompress=threshold=0.015:ratio=5:attack=40:release=700:makeup=1[md];"
          f"[0:a][md]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
    out = final.with_name(final.stem + "_music.mp4")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(final), "-i", str(music), "-filter_complex", fc,
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    final.write_bytes(out.read_bytes())
    out.unlink()
    print(f"music bed laid under the narration ({music.name}); voice-only cut kept at {quiet.name}")


if __name__ == "__main__":
    import sys
    main(tuple(sys.argv[1:]))
