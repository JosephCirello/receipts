"""Scripted screen recordings of the real app for the demo video (Playwright).

  python media/record.py <shot> [--url http://127.0.0.1:8090] [--scale 2]

Each shot is one clean take of the working product: a real page, real data,
real clicks. Nothing is mocked up. Output: media/takes/<shot>.webm

Takes are recorded at twice the size (3840x2160) so the cut can zoom in on one line and keep it
sharp: the window is 3840x2160 and the page is magnified 2x, which gives the same layout as a
1920x1080 window with twice the pixels (the two heights the page sets from the window's height are
halved to match). --scale 1 records the plain 1920x1080 window. A headless browser has no cursor,
so tap() draws a finger dot where a click lands.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
TAKES = HERE / "takes"
W, H = 1920, 1080
SCALE = [2]
T0 = [0.0]

# runs before the page's own scripts on every load: magnify the page, and keep the layout that of a 1920x1080 window
MAGNIFY = """
(() => {
  const S = %d;
  if (S === 1) return;
  const go = () => {
    document.documentElement.style.zoom = S;
    const st = document.createElement("style");
    st.textContent = `.feed{max-height:${72 / S}vh !important} .grid{height:${72 / S}vh !important}`;
    document.head.appendChild(st);
  };
  if (document.head) go(); else document.addEventListener("DOMContentLoaded", go);
})();
"""

# the finger dot: lands, presses, fades (pointer-events off, so the click goes to the page under it)
DOT = """
([x, y, press]) => {
  const d = document.createElement("div");
  d.style.cssText = `position:fixed;left:${x}px;top:${y}px;width:46px;height:46px;margin:-23px 0 0 -23px;border-radius:50%;` +
    "background:rgba(20,33,61,.30);border:2.5px solid rgba(255,255,255,.95);box-shadow:0 2px 10px rgba(20,33,61,.35);pointer-events:none;z-index:99999";
  document.documentElement.appendChild(d);
  const a = d.animate([{ transform: "scale(1.9)", opacity: 0 }, { transform: "scale(1)", opacity: 1 }], { duration: 320, easing: "ease-out", fill: "forwards" });
  a.finished.then(() => new Promise((r) => setTimeout(r, press - 320)))
    .then(() => d.animate([{ transform: "scale(1)", opacity: 1 }, { transform: "scale(.72)", opacity: 1, offset: .25 }, { transform: "scale(1.5)", opacity: 0 }], { duration: 520, easing: "ease-out", fill: "forwards" }).finished)
    .then(() => d.remove());
}
"""


# the two sides grow past the bottom of the window as the day is worked: keep the page at its newest line, as a
# viewer scrolling down would. The page is moved in the same instant a line arrives, so a line never slides:
# it appears where it will stay until the next one.
PIN = """() => {
  const pin = () => window.scrollTo(0, 1e7);
  window.__pin = new ResizeObserver(pin);
  window.__pin.observe(document.querySelector("main"));
}"""
# after the day: stop following, and bring the one-line summary above the two sides to the middle of the window
SUMMARY = """() => {
  if (window.__pin) window.__pin.disconnect();
  const r = document.querySelector("#outcome").getBoundingClientRect();
  window.scrollTo(0, scrollY + r.top + r.height / 2 - innerHeight / 2);
}"""


def mark(what):
    """Print how far into the take a moment falls, to set the scene's start trim in script.json (check by frame)."""
    print(f"  {time.time() - T0[0]:6.2f}s  {what}", flush=True)


def tap(page, selector, click=True, lead=0.45):
    """Click a control with the finger dot drawn where the click lands (click=False: point at it only)."""
    b = page.locator(selector).first.bounding_box()
    x, y = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
    s = SCALE[0]
    page.evaluate(DOT, [x / s, y / s, int(lead * 1000)])
    time.sleep(lead)
    if click:
        page.mouse.click(x, y)
    else:
        page.mouse.move(x, y)


def glide(page, top, seconds=1.2):
    """Scroll the page to `top` (in 1920x1080 page pixels) at an even, eased pace."""
    page.evaluate("""([top, ms]) => new Promise((done) => {
        const from = scrollY, t0 = performance.now();
        const step = (t) => { const u = Math.min(1, (t - t0) / ms), e = u * u * (3 - 2 * u);
          window.scrollTo(0, from + (top - from) * e); if (u < 1) requestAnimationFrame(step); else done(); };
        requestAnimationFrame(step); })""", [top * SCALE[0], int(seconds * 1000)])


def shot_sbs(page, base, scenario, model, speed=1.4, hold=4, rep=None, follow=True):
    """The side-by-side: Receipts off on the left, on on the right, one recorded real run each.
    follow: keep the newest line in the window and end on the summary line; without it the page is never
    scrolled, so the top strip of each side stays exactly where it is while its figure changes."""
    page.goto(f"{base}/?scenario={scenario}&model={model}&speed={speed}&clean=1" + (f"&rep={rep}" if rep is not None else ""))
    page.wait_for_selector(".mail")
    time.sleep(1.5)
    mark("run the day")
    page.click("#go")
    if follow:
        page.evaluate(PIN)
    page.wait_for_selector("#feed-enforce .verdict", timeout=240_000)
    mark("Receipts' verdict on screen")
    page.wait_for_function("document.querySelectorAll('.done').length >= 2", timeout=240_000)
    mark("both sides finished")
    page.wait_for_selector("#outcome:not([hidden])", timeout=30_000)
    time.sleep(hold)
    if follow:
        mark("summary line to the middle")
        page.evaluate(SUMMARY)
        time.sleep(5)


def shot_rules(page, base):
    """Her rules in her words on the left; one press, and what Receipts understood on the right, each with her words under it."""
    page.goto(f"{base}/#rules")
    page.wait_for_selector("#english")
    page.wait_for_function("document.querySelector('#english').value.length > 20")
    time.sleep(4.0)
    mark("tap Turn these into exact rules")
    tap(page, "#compile")
    time.sleep(0.3)
    page.wait_for_function("!document.querySelector('#compile').disabled", timeout=120_000)
    mark("drafted")
    time.sleep(6.0)


def shot_ledger(page, base):
    """Maya's book: the one-tap view changes the rows and the live totals; the download is the accountant's copy."""
    page.goto(f"{base}/#ledger")
    page.wait_for_selector(".ag-row")
    time.sleep(2.5)
    mark("tap Would have paid twice")
    tap(page, "#ledgerViews [data-view=twice]")
    time.sleep(3.2)
    mark("point at Download for the accountant")
    tap(page, "#exportCsv", click=False, lead=1.6)
    time.sleep(1.5)


def shot_results(page, base):
    """What we measured: the headline and the tiles, then down to the cost-against-loss chart."""
    page.goto(f"{base}/#results")
    page.wait_for_selector(".tile")
    page.wait_for_selector("#costChart svg")
    time.sleep(4.5)
    mark("glide down to the chart")
    glide(page, 548, 1.3)
    time.sleep(4.5)


NEMO = "nemotron-3-nano-omni-30b-a3b-reasoning"


def shot_single(page, base, scenario, model, speed=1.5, hold=3.5, rep=None):
    """Receipts ON only, full width: one recorded real run replayed through Receipts and PayPal now."""
    page.goto(f"{base}/?scenario={scenario}&model={model}&speed={speed}&sbs=0&clean=1" + (f"&rep={rep}" if rep is not None else ""))
    page.wait_for_selector(".mail")
    time.sleep(1.2)
    mark("run the day")
    page.click("#go")
    page.wait_for_function("document.querySelectorAll('.done').length >= 1", timeout=240_000)
    mark("day finished")
    time.sleep(hold)


def shot_owner(page, base, scenario="S3_three_smaller_invoices", model=None, button="approve", read=2.5, after=3):
    """A held move lands on the owner's phone; she taps Approve (it goes to PayPal) or Decline (it never does)."""
    page.request.post(f"{base}/api/reset")
    page.goto(f"{base}/?scenario={scenario}&model={model or NEMO}&speed=6&sbs=0&clean=1")
    page.wait_for_selector(".mail")
    page.click("#go")
    page.wait_for_function("document.querySelectorAll('.done').length >= 1", timeout=240_000)
    page.click("#tabs button[data-tab=owner]")
    page.wait_for_selector(f".hold .{button}", timeout=30_000)
    mark("phone on screen")
    time.sleep(read)
    mark(f"tap {button}")
    tap(page, f".hold .{button}")
    page.wait_for_selector(".hold .state", timeout=30_000)
    mark("card answered")
    time.sleep(after)


# the crossed-in-the-mail day: chosen from the recorded runs after the batch (an observe run that checked
# PayPal with the default filter and paid twice; an enforce run of the same model that tried and was held)
S14_MODEL = "glm-5.3"


def shot_mcp_term(page, base):
    """The real output of examples/mcp_client_demo.py, played back in a terminal frame."""
    import json as _json
    page.add_init_script("window.OUTPUT = " + _json.dumps((HERE / "mcp_demo_output.txt").read_text(encoding="utf-8")))
    page.goto((HERE / "terminal.html").as_uri())
    page.wait_for_function("document.body.dataset.done === '1'", timeout=60_000)
    time.sleep(2.5)


def render_slides(base):
    out = HERE / "build" / "slides"
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        pg = br.new_page(viewport={"width": W, "height": H})
        # every card the script uses, plus the stills for the README and Devpost gallery
        plan = json.loads((HERE / "script.json").read_text(encoding="utf-8"))
        ids = [v["slide"] for s in plan["scenes"] for v in (s["visual"], s["visual"].get("then") or {}) if "slide" in v]
        for sid in ids + [x for x in ("pain", "finding", "advice", "results", "cover") if x not in ids]:
            pg.goto((HERE / "slides.html").as_uri() + "#" + sid)
            pg.wait_for_timeout(900)
            pg.screenshot(path=str(out / f"{sid}.png"))
            print("slide", sid)
        br.close()


# the company's hand-drawn ring (the one on its post images), as a path around a box of half-width 1 and
# half-height 1: it starts at the left, goes over the top and round, and its end runs on past its start
RING_PATH = ("M -1.000 -0.053 C -1.042 -0.816, -0.456 -1.079, 0.060 -1.000 C 0.597 -0.921, 1.007 -0.684, 1.000 0.026 "
             "C 0.993 0.842, 0.322 1.079, -0.173 1.000 C -0.647 0.921, -0.972 0.658, -0.986 0.026 C -0.993 -0.289, -0.901 -0.526, -0.774 -0.632")
RING_FRAMES = 15                                    # the ring draws itself on over half a second


def render_rings():
    """The red rings of script.json, each as the frames of it drawing itself (media/build/rings/<scene>/NN.png,
    see-through), at twice the page size like the takes, with where it sits on the page (geom.json)."""
    plan = json.loads((HERE / "script.json").read_text(encoding="utf-8"))
    out = HERE / "build" / "rings"
    nums = [float(t) for t in re.findall(r"-?\d+\.\d+", RING_PATH)]
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        pg = br.new_page(viewport={"width": 800, "height": 400})
        for s in plan["scenes"]:
            for part, suffix in ((s["visual"], ""), (s["visual"].get("then") or {}, "_then")):
                ring = part.get("ring")
                if not ring:
                    continue
                x, y, w, h = ring["box"]
                zoom = 1.0                              # the camera's zoom when the ring appears: the line is about 8.5 px wide on screen
                for k in (part.get("focus") or {}).get("keys", []):
                    if k[0] <= ring["at"]:
                        zoom = k[1]
                stroke = float(ring.get("stroke", 8.5 / zoom))
                mx, my = 0.06 * w + stroke, 0.06 * h + stroke
                x0, y0 = int((x - mx) * 2), int((y - my) * 2)                       # the picture's corner on the 3840x2160 page
                cw, ch = int(round((w + 2 * mx) * 2)) + 2, int(round((h + 2 * my) * 2)) + 2
                cx, cy = (x + w / 2) * 2 - x0, (y + h / 2) * 2 - y0
                # around a long thin target the ring's top and bottom run flatter, as a pen ring round a line of text does:
                # the handles each side of the path's top and bottom points (pairs 2, 4 and 8, 10) are made longer
                flat = 1 + 0.6 * max(0.0, min(1.0, (w / h - 2) / 4))
                unit = [[nums[i], nums[i + 1]] for i in range(0, len(nums), 2)]
                if ring.get("snug"):                    # round words in a line of text: the end lies along the ring's own start
                    unit[-2], unit[-1] = [-0.965, -0.470], [-0.897, -0.600]
                for handle, anchor in ((2, 3), (4, 3), (8, 9), (10, 9)):
                    unit[handle][0] = unit[anchor][0] + (unit[handle][0] - unit[anchor][0]) * flat
                pts = [(cx + ux * w, cy + uy * h) for ux, uy in unit]
                d = f"M {pts[0][0]:.1f} {pts[0][1]:.1f} " + " ".join(
                    "C " + ", ".join(f"{px:.1f} {py:.1f}" for px, py in pts[j:j + 3]) for j in range(1, len(pts), 3))
                pg.set_viewport_size({"width": cw, "height": ch})
                pg.set_content(f'<html><body style="margin:0;background:transparent"><svg width="{cw}" height="{ch}" style="display:block">'
                               f'<path d="{d}" fill="none" stroke="#c7392f" stroke-width="{stroke * 2:.1f}" stroke-linecap="round" '
                               f'stroke-linejoin="round" opacity=".92"/></svg></body></html>')
                length = pg.evaluate("document.querySelector('path').getTotalLength()") + 1
                folder = out / (s["id"] + suffix)
                folder.mkdir(parents=True, exist_ok=True)
                for old in folder.glob("*.png"):
                    old.unlink()
                for k in range(1, RING_FRAMES + 1):
                    drawn = 1 - (1 - k / RING_FRAMES) ** 2              # the pen starts fast and slows as it closes the ring
                    pg.evaluate("([len, off]) => { const p = document.querySelector('path'); p.style.strokeDasharray = len; p.style.strokeDashoffset = off; }",
                                [length, length * (1 - drawn)])
                    pg.screenshot(path=str(folder / f"{k - 1:02d}.png"), omit_background=True)
                (folder / "geom.json").write_text(json.dumps({"x": x0, "y": y0, "w": cw, "h": ch, "frames": RING_FRAMES, "stroke": round(stroke, 2)}), encoding="utf-8")
                print("ring", s["id"] + suffix, f"{cw}x{ch} at {x0},{y0}, line {stroke:.1f} page px")
        br.close()


# a take in a window of another size (page pixels). The opening's strip is the top of the "Without Receipts" side,
# never scrolled, in a window just wide enough for the two sides to stand side by side: the strip is then
# narrow, so the cut can show its own words large.
WINDOW = {"strip_s14": (1120, 1080)}

SHOTS = {
    "live_split": lambda p, b: shot_single(p, b, "S3_three_smaller_invoices", NEMO),
    "claims": lambda p, b: shot_single(p, b, "S5_i_am_the_owner", NEMO, rep=1),
    "report": lambda p, b: shot_single(p, b, "S9_normal_tuesday", NEMO, hold=4.5, rep=0),
    "owner": shot_owner,
    "mcp_term": shot_mcp_term,
    "sbs_s2": lambda p, b: shot_sbs(p, b, "S2_second_notice", "glm-5.2"),
    "sbs_s14": lambda p, b: shot_sbs(p, b, "S14_crossed_in_the_mail", S14_MODEL, speed=1.2, hold=3, rep=0),
    "strip_s14": lambda p, b: shot_sbs(p, b, "S14_crossed_in_the_mail", S14_MODEL, speed=1.2, hold=5, rep=0, follow=False),
    "owner_s14": lambda p, b: shot_owner(p, b, "S14_crossed_in_the_mail", S14_MODEL, button="decline", read=6, after=5),
    "rules": shot_rules,
    "ledger": shot_ledger,
    "results": shot_results,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shot", choices=sorted(SHOTS) + ["slides", "rings", "all"])
    ap.add_argument("--url", default="http://127.0.0.1:8090")
    ap.add_argument("--theme", default="light")
    ap.add_argument("--scale", type=int, default=2, choices=(1, 2), help="2 records 3840x2160 (the page magnified 2x); 1 records 1920x1080")
    a = ap.parse_args()
    SCALE[0] = a.scale
    if a.shot == "slides":
        return render_slides(a.url)
    if a.shot == "rings":
        return render_rings()
    if a.shot == "all":
        for name in SHOTS:
            record(name, a.url, a.theme)
        render_slides(a.url)
        return render_rings()
    record(a.shot, a.url, a.theme)


def record(shot, url, theme):
    TAKES.mkdir(exist_ok=True)
    tmp = TAKES / f"_tmp_{shot}"
    shutil.rmtree(tmp, ignore_errors=True)
    s = SCALE[0]
    w, h = WINDOW.get(shot, (W, H))
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        ctx = br.new_context(viewport={"width": w * s, "height": h * s}, device_scale_factor=1, color_scheme=theme,
                             record_video_dir=str(tmp), record_video_size={"width": w * s, "height": h * s})
        ctx.add_init_script(MAGNIFY % s)
        page = ctx.new_page()
        T0[0] = time.time()                         # the video starts with the page; mark() prints seconds into the take
        page.request.post(f"{url}/api/reset")       # every take starts with no leftover holds
        SHOTS[shot](page, url)
        vid = page.video.path()
        ctx.close()
        br.close()
    out = TAKES / f"{shot}.webm"
    shutil.move(vid, out)
    shutil.rmtree(tmp, ignore_errors=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
