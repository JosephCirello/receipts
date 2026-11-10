"""The narration as a captions file the viewer switches on (YouTube's CC button): media/build/receipts_demo.srt and .vtt.

  python media/captions.py            # after media/assemble.py (it also runs at the end of assemble.py)

The video carries no captions in its picture. This file is the narration of script.json, word for word and in
order. The numbers the voice spells out are written the way the cards write them (the list is NUMBERS below);
no other word is changed, and the script stops if the captions and the narration ever differ.

Each cue is at most two lines of 42 characters and stays up between 1 and 6 seconds. Its times are where its
words are spoken in the finished video: the scene's start in the cut (media/build/timings.json), plus the time
the voice reported for each word when the line was recorded (media/build/vo/<scene>.json).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
B = HERE / "build"
LINE = 42             # characters to a line
MIN_S, MAX_S = 1.0, 6.0
LINGER = 0.4          # a cue stays this long after its last word, when the next cue leaves room
GAP = 0.04            # between one cue and the next
SHORT_S, SHORT_CHARS = 1.65, 12   # a sentence that would be up for less than this joins the one after it, if the two fit in one cue
WEAK_END = {"a", "an", "the", "to", "of", "in", "on", "and", "or", "is", "for", "with", "by", "at", "as", "her", "its", "their", "your"}

# What the voice says -> how the cards write it. Each entry is a run of whole words of that scene's line.
NUMBERS = {
    "maya": [("eighteen hundred and thirty-six dollars", "$1,836")],
    "pain1": [("thirty-eight", "38"), ("nineteen", "19"), ("Sixty-one percent", "61%")],
    "price": [("thirty-five", "35")],
    "finding1": [("fourteen hundred forty-four", "1,444"), ("seven percent", "7%"),
                 ("Seventy thousand dollars", "$70,000"), ("A hundred", "100")],
    "finding2": [("ninety-eight percent", "98%")],
}
ENDS = ",.;:?!"


def letters(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def timed_words(scene: str, say: str):
    """The line's words as written in script.json, each with the seconds (inside its clip) at which it is spoken."""
    spoken = json.loads((B / "vo" / f"{scene}.json").read_text(encoding="utf-8"))["words"]
    owner = [i for i, t in enumerate(spoken) for _ in letters(t["word"])]       # for every letter spoken, the word it belongs to
    if letters(say) != "".join(letters(t["word"]) for t in spoken):
        raise SystemExit(f"{scene}: the voice clip was not recorded from this line; run media/tts.py {scene}")
    out, at = [], 0
    for w in say.split():
        n = len(letters(w))
        out.append({"text": w, "start": spoken[owner[at]]["start"], "end": spoken[owner[at + n - 1]]["end"]})
        at += n
    return out


def write_numbers(scene: str, words, made):
    """Swap the spelled-out numbers of this scene for their written form (a run of words becomes one)."""
    for spoken, written in NUMBERS.get(scene, []):
        run = spoken.split()
        hits = [i for i in range(len(words) - len(run) + 1)
                if [w["text"].rstrip(ENDS) for w in words[i:i + len(run)]] == run]
        if len(hits) != 1:
            raise SystemExit(f"{scene}: '{spoken}' is in the line {len(hits)} times, expected once")
        i = hits[0]
        last = words[i + len(run) - 1]
        tail = last["text"][len(last["text"].rstrip(ENDS)):]
        made.append({"scene": scene, "spoken": spoken, "written": written})
        words[i:i + len(run)] = [{"text": written + tail, "start": words[i]["start"], "end": last["end"]}]
    return words


def text(words) -> str:
    return " ".join(w["text"] for w in words)


def two_lines(s: str):
    """The text on one line, or on two of at most LINE characters. The two are kept even, but a line that ends
    at a comma or a full stop is preferred, and one that ends on "the", "to", "of" and the like is avoided.
    None if it does not fit."""
    if len(s) <= LINE:
        return [s]
    parts = s.split(" ")
    best = None
    for i in range(1, len(parts)):
        a, b = " ".join(parts[:i]), " ".join(parts[i:])
        if len(a) <= LINE and len(b) <= LINE:
            cost = abs(len(a) - len(b)) - (24 if a[-1] in ENDS else 0) + (14 if parts[i - 1].lower() in WEAK_END else 0)
            if best is None or cost < best[0]:
                best = (cost, [a, b])
    return best[1] if best else None


def fits(words) -> bool:
    return two_lines(text(words)) is not None and words[-1]["end"] - words[0]["start"] + LINGER <= MAX_S


def split_long(words):
    """A sentence too long for one cue is cut where it is most even: at a comma, semicolon or colon if it has one."""
    if fits(words):
        return [words]
    for ok in (lambda t: t[-1] in ",;:", lambda t: True):
        cuts = [i for i in range(1, len(words)) if ok(words[i - 1]["text"])]
        if cuts:
            i = min(cuts, key=lambda i: abs(len(text(words[:i])) - len(text(words[i:]))))
            return split_long(words[:i]) + split_long(words[i:])
    raise SystemExit("a single word does not fit a caption line: " + text(words))


def scene_cues(words):
    """One scene's words as cues: a sentence each. A long sentence is cut at a clause. A sentence that would be
    up too briefly joins the one after it ("This is Maya." with the sentence that follows); one that could not
    stay up a second on its own, and has nothing after it, joins the one before."""
    sentences, cur = [], []
    for w in words:
        cur.append(w)
        if w["text"][-1] in ".?!":
            sentences.append(cur)
            cur = []
    if cur:
        sentences.append(cur)
    cues = [c for s in sentences for c in split_long(s)]

    def up(i):                                  # how long cue i can stay on screen before the next one starts
        nxt = cues[i + 1][0]["start"] - GAP if i + 1 < len(cues) else float("inf")
        return min(cues[i][-1]["end"] + LINGER, nxt) - cues[i][0]["start"]
    i = 0
    while i < len(cues):
        tiny = len(text(cues[i])) < SHORT_CHARS
        if (tiny or up(i) < SHORT_S) and i + 1 < len(cues) and fits(cues[i] + cues[i + 1]):
            cues[i:i + 2] = [cues[i] + cues[i + 1]]
            continue
        if (tiny or up(i) < MIN_S + 0.1) and i > 0 and fits(cues[i - 1] + cues[i]):
            cues[i - 1:i + 1] = [cues[i - 1] + cues[i]]
            i -= 1
            continue
        i += 1
    return cues


def build():
    plan = json.loads((HERE / "script.json").read_text(encoding="utf-8"))
    times = {s["scene"]: s for s in json.loads((B / "timings.json").read_text(encoding="utf-8"))["scenes"]}
    final = B / "receipts_demo.mp4"
    if final.exists():
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(final)], capture_output=True, text=True)
        video_end = float(r.stdout.strip())
    else:
        video_end = max(s["start"] + s["length"] for s in times.values())
    cues, made = [], []
    for s in plan["scenes"]:
        t0 = times[s["id"]]["start"] + times[s["id"]].get("lead", 0.0)      # where this scene's voice clip starts in the video
        words = write_numbers(s["id"], timed_words(s["id"], s["say"]), made)
        for c in scene_cues(words):
            cues.append({"scene": s["id"], "start": t0 + c[0]["start"], "spoken_to": t0 + c[-1]["end"], "lines": two_lines(text(c)),
                         "words": [{"text": w["text"], "at": round(t0 + w["start"], 3)} for w in c]})
    for k, c in enumerate(cues):
        room = (cues[k + 1]["start"] - GAP) if k + 1 < len(cues) else video_end - 0.05
        c["end"] = min(max(c["spoken_to"] + LINGER, c["start"] + MIN_S), c["start"] + MAX_S, room)
    check(plan, cues, video_end)
    return cues, made, video_end


def check(plan, cues, video_end):
    """Stop if the captions are not the narration, or a cue breaks a rule."""
    for s in plan["scenes"]:
        back = " ".join(" ".join(c["lines"]) for c in cues if c["scene"] == s["id"])
        for spoken, written in NUMBERS.get(s["id"], []):
            if back.count(written) != 1:
                raise SystemExit(f"{s['id']}: '{written}' should be in the captions once")
            back = back.replace(written, spoken)
        if back != s["say"]:
            raise SystemExit(f"{s['id']}: the captions are not the narration:\n  {back}\n  {s['say']}")
    for k, c in enumerate(cues):
        d = c["end"] - c["start"]
        if not (MIN_S - 1e-6 <= d <= MAX_S + 1e-6):
            raise SystemExit(f"cue {k + 1} is on screen {d:.2f} s: {' / '.join(c['lines'])}")
        if len(c["lines"]) > 2 or max(len(x) for x in c["lines"]) > LINE:
            raise SystemExit(f"cue {k + 1} does not fit two lines of {LINE}: {c['lines']}")
        if k and c["start"] < cues[k - 1]["end"]:
            raise SystemExit(f"cue {k + 1} starts before cue {k} ends")
    if cues[-1]["end"] > video_end:
        raise SystemExit("the last cue runs past the end of the video")


def clock(t: float, comma: bool) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{',' if comma else '.'}{ms:03d}"


def write():
    cues, made, video_end = build()
    srt = "".join(f"{k}\n{clock(c['start'], True)} --> {clock(c['end'], True)}\n" + "\n".join(c["lines"]) + "\n\n" for k, c in enumerate(cues, 1))
    vtt = "WEBVTT\n\n" + "".join(f"{k}\n{clock(c['start'], False)} --> {clock(c['end'], False)}\n" + "\n".join(c["lines"]) + "\n\n" for k, c in enumerate(cues, 1))
    (B / "receipts_demo.srt").write_bytes(srt.encode("utf-8"))
    (B / "receipts_demo.vtt").write_bytes(vtt.encode("utf-8"))
    (B / "captions.json").write_text(json.dumps({"video_end": video_end, "numbers": made, "cues": cues}, indent=1), encoding="utf-8")
    on = [c["end"] - c["start"] for c in cues]
    print(f"captions: {len(cues)} cues, on screen {min(on):.2f} to {max(on):.2f} s each, longest line {max(len(x) for c in cues for x in c['lines'])} characters, "
          f"last cue ends {cues[-1]['end']:.2f} s of {video_end:.2f} s; {len(made)} numbers written as figures; the text is the narration word for word")
    print("wrote", B / "receipts_demo.srt", "and", B / "receipts_demo.vtt")
    return cues, made


if __name__ == "__main__":
    write()
