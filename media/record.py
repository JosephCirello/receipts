"""Scripted screen recordings of the real app for the demo video (Playwright, 1920x1080).

  python media/record.py <shot> [--url http://127.0.0.1:8090]

Each shot is one clean take of the working product: a real page, real data,
real clicks. Nothing is mocked up. Output: media/takes/<shot>.webm
"""
from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
TAKES = HERE / "takes"
W, H = 1920, 1080


def shot_sbs(page, base, scenario, model, speed=1.4, hold=4):
    """The side-by-side: Receipts off on the left, on on the right, one recorded real run each."""
    page.goto(f"{base}/?scenario={scenario}&model={model}&speed={speed}&clean=1")
    page.wait_for_selector(".mail")
    time.sleep(1.5)
    page.click("#go")
    page.wait_for_function("document.querySelectorAll('.done').length >= 2", timeout=240_000)
    time.sleep(hold)


def shot_rules(page, base):
    page.goto(f"{base}/#rules")
    page.wait_for_selector("#english")
    time.sleep(1.5)
    page.click("#compile")
    page.wait_for_function("!document.querySelector('#compile').disabled", timeout=120_000)
    time.sleep(2.5)
    page.click("#usePolicy")
    time.sleep(2)


def shot_ledger(page, base):
    page.goto(f"{base}/#ledger")
    page.wait_for_selector(".ag-row")
    time.sleep(1.5)
    page.fill("#quick", "BLOCK")
    time.sleep(2.5)
    page.fill("#quick", "")
    time.sleep(1)


def shot_results(page, base):
    page.goto(f"{base}/#results")
    page.wait_for_selector(".tile")
    time.sleep(4)


NEMO = "nemotron-3-nano-omni-30b-a3b-reasoning"


def shot_single(page, base, scenario, model, speed=1.5, hold=3.5):
    """Receipts ON only, full width: one recorded real run replayed through Receipts and PayPal now."""
    page.goto(f"{base}/?scenario={scenario}&model={model}&speed={speed}&sbs=0&clean=1")
    page.wait_for_selector(".mail")
    time.sleep(1.2)
    page.click("#go")
    page.wait_for_function("document.querySelectorAll('.done').length >= 1", timeout=240_000)
    time.sleep(hold)


def shot_owner(page, base):
    """A held move lands on the owner's phone; she approves; it goes to PayPal."""
    page.request.post(f"{base}/api/reset")
    page.goto(f"{base}/?scenario=S3_three_smaller_invoices&model={NEMO}&speed=6&sbs=0&clean=1")
    page.wait_for_selector(".mail")
    page.click("#go")
    page.wait_for_function("document.querySelectorAll('.done').length >= 1", timeout=240_000)
    page.click("#tabs button[data-tab=owner]")
    page.wait_for_selector(".hold .approve", timeout=30_000)
    time.sleep(2.5)
    page.click(".hold .approve")
    page.wait_for_selector(".hold .state", timeout=30_000)
    time.sleep(3)


def render_slides(base):
    out = HERE / "build" / "slides"
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        pg = br.new_page(viewport={"width": W, "height": H})
        for sid in ("problem", "finding", "line", "mcp", "results", "close"):
            pg.goto((HERE / "slides.html").as_uri() + "#" + sid)
            pg.wait_for_timeout(900)
            pg.screenshot(path=str(out / f"{sid}.png"))
            print("slide", sid)
        br.close()


SHOTS = {
    "live_split": lambda p, b: shot_single(p, b, "S3_three_smaller_invoices", NEMO),
    "claims": lambda p, b: shot_single(p, b, "S5_i_am_the_owner", NEMO),
    "report": lambda p, b: shot_single(p, b, "S1_new_paypal_address", NEMO, hold=4.5),
    "owner": shot_owner,
    "sbs_s2": lambda p, b: shot_sbs(p, b, "S2_second_notice", "glm-5.2"),
    "rules": shot_rules,
    "ledger": shot_ledger,
    "results": shot_results,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shot", choices=sorted(SHOTS) + ["slides", "all"])
    ap.add_argument("--url", default="http://127.0.0.1:8090")
    ap.add_argument("--theme", default="light")
    a = ap.parse_args()
    if a.shot == "slides":
        return render_slides(a.url)
    if a.shot == "all":
        for name in SHOTS:
            record(name, a.url, a.theme)
        return render_slides(a.url)
    record(a.shot, a.url, a.theme)


def record(shot, url, theme):
    TAKES.mkdir(exist_ok=True)
    tmp = TAKES / f"_tmp_{shot}"
    shutil.rmtree(tmp, ignore_errors=True)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        ctx = br.new_context(viewport={"width": W, "height": H}, device_scale_factor=1, color_scheme=theme,
                             record_video_dir=str(tmp), record_video_size={"width": W, "height": H})
        page = ctx.new_page()
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
