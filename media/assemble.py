"""Cut the demo video: one segment per scene, timed to its narration.

The video carries no captions in its picture: script.json says "burn_captions": false, and media/captions.py
writes the narration, word for word, as a captions file (.srt and .vtt) to upload beside the video, for the
viewer to switch on. With "burn_captions": true each scene's short "caption" is drawn into the picture instead.

  python media/assemble.py            # needs media/build/vo (tts.py), media/takes (record.py),
                                      # media/build/slides and media/build/rings (record.py slides, record.py rings)

Takes are sped up (never slowed below real time) to fit the narration, then hold on
their last frame. Cards get a slow push-in. Output: media/build/receipts_demo.mp4 (voice and music),
and media/build/receipts_demo_sfx.mp4, the same pictures with the two sound effects of media/sfx laid in.

What a scene in script.json may carry, beyond its line, caption and visual:
  "lead": seconds of picture before the voice starts; "tail": seconds of picture added after it.
  "sfx": [{"at": second of the scene, "sound": "ding" | "tap"}], a sound effect from media/sfx on that frame.
  visual "start": where in the take the scene begins; "speed": play the take at exactly this speed
    (1 = real time) instead of fitting what is left of it to the line; "end": stop the take there and
    hold that frame (for a page that is standing still anyway).
  visual "focus": the camera on a take. Either the simple form {"from", "zoom", "cx", "cy", "still"},
    or {"keys": [[second, zoom, x, y], ...]}: at each second of the scene the camera is at that zoom,
    centred on that point of the 1920x1080 page, and it eases from one key to the next. A key may carry
    a fifth value, "out": the camera is already moving when the stretch starts and lands softly on that key.
  visual "ring": {"at": second, "for": seconds, "box": [x, y, w, h]}: a hand-drawn red ring drawn on the page
    (so it moves with the camera) around that box of the 1920x1080 page; it draws itself, stays, and fades.
  visual "mask": {"keep": [x, y, w, h], "soft": [above, below]}: only that box of the 1920x1080 page is shown;
    the rest of the page is covered with the page's own background colour (for a shot of one line of the
    page and nothing else). "soft": the cover comes in gradually over that many page pixels above and below.
  visual "window": {"page": [w, h], "box": [x, y, w]}: for a take recorded in a window of another size (w x h page
    pixels): only that 16:9 box of it is used, as if it were the whole 1920x1080 page; the camera, mask and ring
    numbers of that picture are then on a 1920-wide canvas of the box.
  visual "inset": on a card, a strip of a take laid over it: {"take", "start", "speed", "crop": [x, y, w, h]
    of the take's page, "at": [x, y] on the card, "width": its width on the card}.
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
RING_FADE = 0.35   # a ring fades out over its last 0.35 s
PAGE_BG = "0xf5f1e9"   # the app's page background (#f4f0e8) as a take records it: this value comes out equal to it in the cut


def dur(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return float(r.stdout.strip())


def width(p: Path) -> int:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width", "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return int(r.stdout.strip().strip(","))


def frames(p: Path) -> int:
    """How many pictures a segment holds."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    return int(r.stdout.strip().strip(","))


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


def eased(keys, value):
    """One camera value over the scene, as an ffmpeg expression in the output frame number. It holds each
    key's value and eases to the next: gently away and gently in (the default), or, for a key marked "out",
    already moving at the start of the stretch and landing softly."""
    pts = [(int(round(k[0] * FPS)), float(value(k)), k[4] if len(k) > 4 else "inout") for k in keys]
    expr = f"{pts[-1][1]:.6f}"
    for (n0, v0, _), (n1, v1, how) in reversed(list(zip(pts, pts[1:]))):
        u = f"((on-{n0})/{max(1, n1 - n0)})"
        e = f"(1-(1-{u})*(1-{u}))" if how == "out" else f"({u}*{u}*(3-2*{u}))"
        seg = f"{v0:.6f}" if v0 == v1 else f"({v0:.6f}+({v1 - v0:.6f})*{e})"
        expr = f"if(lt(on,{n1}),{seg},{expr})"
    return f"if(lt(on,{pts[0][0]}),{pts[0][1]:.6f},{expr})"


def camera(fo, d):
    """The zoompan filter for a take's focus (the take is 3840x2160 by then; the picture out is 1920x1080).
    Between keys it is the frame's edges that move evenly, so a push-in does not lurch at its start."""
    if "keys" in fo:
        w = eased(fo["keys"], lambda k: 1 / k[1])            # the width of the frame, as a share of the page
        cx, cy = eased(fo["keys"], lambda k: k[2]), eased(fo["keys"], lambda k: k[3])
        return (f",zoompan=z='1/({w})':x='max(0,min(iw-iw/zoom,({cx})*iw/1920-iw/zoom/2))'"
                f":y='max(0,min(ih-ih/zoom,({cy})*ih/1080-ih/zoom/2))':d=1:s=1920x1080:fps={FPS}")
    n0, z = int(fo["from"] * d * FPS), fo["zoom"]
    step = (z - 1) / max(1, int(0.35 * d * FPS))
    zexpr = f"{z}" if fo.get("still") else f"if(lt(on,{n0}),1,min(1+(on-{n0})*{step:.5f},{z}))"   # still: a fixed crop, no push-in
    return f",zoompan=z='{zexpr}':x='(iw-iw/zoom)*{fo['cx']}':y='(ih-ih/zoom)*{fo['cy']}':d=1:s=1920x1080:fps={FPS}"


def take_chain(v, d, i, size="3840:2160"):
    """A take laid out at an even frame rate from its start time (a take only stores a frame when the page
    changes, so the scene starts on exactly what was on screen at `start`), at its speed, for d seconds."""
    src = HERE / "takes" / f"{v['take']}.webm"
    start = float(v.get("start", 0))            # skip the page load at the head of a take
    f = float(v["speed"]) if "speed" in v else max(1.0, min(3.0, (dur(src) - start) / d))
    end = f":end={float(v['end']):.3f}" if "end" in v else ""
    fit = f"scale={size}:flags=lanczos," if size else ""        # an inset strip is cut from the take at its own size
    win = v.get("window")
    if win:                                                     # a 16:9 box of a take recorded in a window of another size
        k = width(src) / win["page"][0]                         # the take's pixels to a page pixel
        x, y, w = win["box"]
        fit = f"crop={round(w * k)}:{round(w * k * 9 / 16)}:{round(x * k)}:{round(y * k)}," + fit
    return (["-i", str(src)],
            f"[{i}:v]fps={FPS},trim=start={start:.3f}{end},setpts=(PTS-STARTPTS)/{f:.4f},fps={FPS},{fit}"
            f"tpad=stop_mode=clone:stop_duration=30,trim=duration={d},setpts=PTS-STARTPTS")


def picture(v, d, i, tag):
    """One picture held for d seconds: its ffmpeg inputs (the first is input number i), and the filter chains
    that end in [p<tag>]. The page (a take or a card) is built at 3840x2160; what is drawn on the page (an
    inset strip of a take, a red ring) goes on before the camera, so it moves with the page."""
    ins, chains = [], []
    fo, ring, inset = v.get("focus"), v.get("ring"), v.get("inset")
    if "take" in v:
        big = bool(fo or ring or v.get("mask"))
        inp, chain = take_chain(v, d, i, "3840:2160" if big else "1920:1080")
        if not big:
            return inp, [chain + f"[p{tag}]"], 1
        ins += inp
        chains.append(chain + f"[b{tag}0]")
    else:
        src = B / "slides" / f"{v['slide']}.png"
        ins += ["-loop", "1", "-framerate", str(FPS), "-t", f"{d + 0.2:.2f}", "-i", str(src)]
        chains.append(f"[{i}:v]scale=3840:2160,trim=duration={d + 0.1:.2f},setpts=PTS-STARTPTS[b{tag}0]")
    used, layer = 1, 0
    if v.get("mask"):
        x, y, w, h = (int(round(c * 2)) for c in v["mask"]["keep"])
        col = v["mask"].get("color", PAGE_BG)
        up, down = (int(c) for c in v["mask"].get("soft", [0, 0]))
        boxes = [(0, 0, 3840, y - up * 2, 1), (0, y + h + down * 2, 3840, 2160 - y - h - down * 2, 1), (0, y, x, h, 1), (x + w, y, 3840 - x - w, h, 1)]
        boxes += [(0, y - 2 * (k + 1), 3840, 2, (k + 0.5) / up) for k in range(up)]             # the cover fades in over the rows above...
        boxes += [(0, y + h + 2 * k, 3840, 2, (k + 0.5) / down) for k in range(down)]           # ...and below the box
        chains.append(f"[b{tag}{layer}]" + ",".join(f"drawbox=x={bx}:y={by}:w={bw}:h={bh}:color={col}@{al:.3f}:t=fill" for bx, by, bw, bh, al in boxes if bw > 0 and bh > 0)
                      + f"[b{tag}{layer + 1}]")
        layer += 1
    if inset:
        x, y, w, h = inset["crop"]
        inp, chain = take_chain(inset, d + 0.1, i + used, None)
        ins += inp
        chains.append(chain + f",crop={w * 2:.0f}:{h * 2:.0f}:{x * 2:.0f}:{y * 2:.0f},scale={inset['width'] * 2:.0f}:-2:flags=lanczos[in{tag}]")
        chains.append(f"[b{tag}{layer}][in{tag}]overlay=x={inset['at'][0] * 2:.0f}:y={inset['at'][1] * 2:.0f}:eof_action=repeat[b{tag}{layer + 1}]")
        used, layer = used + 1, layer + 1
    if ring:
        g = json.loads((B / "rings" / ring["id"] / "geom.json").read_text(encoding="utf-8"))
        at, life = float(ring["at"]), float(ring["for"])
        ins += ["-framerate", str(FPS), "-i", str(B / "rings" / ring["id"] / "%02d.png")]
        chains.append(f"[{i + used}:v]format=rgba,tpad=stop_mode=clone:stop_duration={life:.2f},fade=t=out:st={life - RING_FADE:.2f}:d={RING_FADE}:alpha=1,"
                      f"trim=duration={life:.2f},setpts=PTS-STARTPTS+{at:.3f}/TB[rg{tag}]")
        chains.append(f"[b{tag}{layer}][rg{tag}]overlay=x={g['x']}:y={g['y']}:eof_action=pass:enable='between(t,{at:.3f},{at + life:.3f})'[b{tag}{layer + 1}]")
        used, layer = used + 1, layer + 1
    if "take" in v:
        cam = camera(fo, d)[1:] if fo else "scale=1920:1080:flags=lanczos"
        chains.append(f"[b{tag}{layer}]{cam},trim=duration={d},setpts=PTS-STARTPTS[p{tag}]")
    else:
        frames = int(d * FPS)
        chains.append(f"[b{tag}{layer}]zoompan=z='1+0.035*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1920x1080:fps={FPS},"
                      f"trim=duration={d},setpts=PTS-STARTPTS[p{tag}]")
    return ins, chains, used


def main(only=()):
    plan = json.loads((HERE / "script.json").read_text(encoding="utf-8"))
    burn = bool(plan.get("burn_captions", True))    # false: no captions in the picture (media/captions.py writes the captions file)
    SEG.mkdir(parents=True, exist_ok=True)
    times, effects = [], []
    t_total = 0.0
    for i, s in enumerate(plan["scenes"]):
        vo = B / "vo" / f"{s['id']}.mp3"
        lead, tail = float(s.get("lead", 0)), float(s.get("tail", 0))
        T = round(lead + dur(vo) + PAD + tail + (1.4 if i == len(plan["scenes"]) - 1 else 0), 2)
        out = f"seg_{i:02d}.mp4"
        v = s["visual"]
        then = v.get("then")
        marks = {"scene": s["id"], "length": T, "lead": lead}               # times inside the scene; its start is filled in below
        for pv, at in ((v, 0.0), (then or {}, float((then or {}).get("at", 0)))):
            if pv.get("ring"):
                marks.setdefault("rings", []).append({"from": at + pv["ring"]["at"], "to": at + pv["ring"]["at"] + pv["ring"]["for"]})
        marks["sfx"] = [{"sound": e["sound"], "at": float(e["at"])} for e in s.get("sfx", [])]
        times.append(marks)
        t_total += T
        if only and s["id"] not in only:            # python media/assemble.py <scene id ...>: recut only these scenes
            continue
        parts = [(v, round(float(then["at"]), 2)), (then, round(T - float(then["at"]), 2))] if then else [(v, T)]
        caps = [(s["caption"], 0.15, (float(then["at"]) if then and "caption" in then else T) - 0.1)] if s["caption"] else []
        if then and then.get("caption"):
            caps.append((then["caption"], float(then["at"]) + 0.1, T - 0.1))
        sub = f"cap_{i:02d}.ass"
        if burn:
            ass(caps, SEG / sub)
        draw = f"subtitles={sub}" if burn else "null"
        cmd, chains, n = ["ffmpeg", "-y", "-v", "error"], [], 0
        for k, (pv, d) in enumerate(parts):
            if pv.get("ring"):
                pv["ring"]["id"] = s["id"] + ("_then" if k else "")
            inp, ch, used = picture(pv, d, n, k)
            cmd += inp
            chains += ch
            n += used
        joined = "".join(f"[p{k}]" for k in range(len(parts)))
        chains.append(f"{joined}concat=n={len(parts)}:v=1:a=0,{draw}[v]" if len(parts) > 1 else f"[p0]{draw}[v]")
        late = f"adelay={int(lead * 1000)}:all=1," if lead else ""
        chains.append(f"[{n}:a]{late}apad,atrim=duration={T},asetpts=PTS-STARTPTS[a]")
        cmd += ["-i", str(vo), "-filter_complex", ";".join(chains),
                "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
                "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-t", f"{T}", out]
        run(cmd)
        print(f"{i:02d} {s['id']:9s} cut ({T:5.2f}s)", flush=True)
    # The picture: the segments' frames laid end to end, so a scene starts exactly where the one before it ends.
    counts = [frames(SEG / f"seg_{i:02d}.mp4") for i in range(len(times))]
    starts = [sum(counts[:i]) / FPS for i in range(len(counts))]
    total = sum(counts) / FPS
    (SEG / "list.txt").write_text("".join(f"file 'seg_{i:02d}.mp4'\nduration {c / FPS:.6f}\n" for i, c in enumerate(counts)), encoding="utf-8")
    picture_only = B / "receipts_demo_picture.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "list.txt", "-map", "0:v", "-c", "copy", str(picture_only)])
    # The narration: one sound track for the whole video, each line laid at its scene's start (plus its lead), to the
    # sample. Joining the segments' own sound tracks instead lets the voice slip later at every join, by the padding
    # an AAC track carries at each end: about 25 ms a scene, close to half a second by the end of a three-minute cut.
    cmd, fc = ["ffmpeg", "-y", "-v", "error", "-i", str(picture_only)], []
    for k, (s, tm) in enumerate(zip(plan["scenes"], times), 1):
        cmd += ["-i", str(B / "vo" / f"{s['id']}.mp3")]
        fc.append(f"[{k}:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={int(round((starts[k - 1] + tm['lead']) * 48000))}S:all=1[n{k}]")
    fc.append("".join(f"[n{k}]" for k in range(1, len(times) + 1))
              + f"amix=inputs={len(times)}:duration=longest:dropout_transition=0:normalize=0,apad,atrim=duration={total:.6f}[a]")
    final = B / "receipts_demo.mp4"
    run(cmd + ["-filter_complex", ";".join(fc), "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
               "-movflags", "+faststart", str(final)])
    picture_only.unlink()
    for tm, st in zip(times, starts):                                       # where everything falls in the finished video
        tm["start"] = round(st, 3)
        for r in tm.get("rings", []):
            r["from"], r["to"] = round(st + r["from"], 2), round(st + r["to"], 2)
        effects += [{"sound": e["sound"], "at": round(st + e["at"], 3), "scene": tm["scene"]} for e in tm.pop("sfx")]
        print(f"{tm['scene']:9s} starts {st:7.2f}s  {tm['length']:5.2f}s", flush=True)
    (B / "timings.json").write_text(json.dumps({"scenes": times, "sfx": effects}, indent=1), encoding="utf-8")
    print(f"wrote {final}  ({dur(final):.1f}s)")
    music = HERE / "music" / "bed.mp3"          # provenance in media/music/SOURCE.md
    if music.exists():
        add_music(final, music)
    if effects:
        add_effects(final, effects)
    import captions                             # the narration as a captions file, timed to this cut
    captions.write()


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


def add_effects(final: Path, effects):
    """The same video with the sound effects of media/sfx laid in at their frames (provenance in
    media/sfx/SOURCE.md). The picture is copied, not re-encoded, so the two files show the same frames."""
    out = final.with_name(final.stem + "_sfx.mp4")
    cmd, fc = ["ffmpeg", "-y", "-v", "error", "-i", str(final)], []
    for k, e in enumerate(effects, 1):
        cmd += ["-i", str(HERE / "sfx" / f"{e['sound']}.wav")]
        fc.append(f"[{k}:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={int(round(e['at'] * 1000))}:all=1[e{k}]")
    fc.append("[0:a]" + "".join(f"[e{k}]" for k in range(1, len(effects) + 1)) + f"amix=inputs={len(effects) + 1}:duration=first:dropout_transition=0:normalize=0[a]")
    run(cmd + ["-filter_complex", ";".join(fc), "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    print(f"sound effects laid in ({', '.join(e['sound'] + '@' + format(e['at'], '.2f') for e in effects)}): {out.name}")


if __name__ == "__main__":
    import sys
    main(tuple(sys.argv[1:]))
