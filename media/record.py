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
    page.goto(f"{base}/?scenario={scenario}&model={model}&speed={speed}")
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


SHOTS = {
    "sbs_s2": lambda p, b: shot_sbs(p, b, "S2_second_notice", "glm-5.2"),
    "rules": shot_rules,
    "ledger": shot_ledger,
    "results": shot_results,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shot", choices=sorted(SHOTS))
    ap.add_argument("--url", default="http://127.0.0.1:8090")
    ap.add_argument("--theme", default="light")
    a = ap.parse_args()
    TAKES.mkdir(exist_ok=True)
    tmp = TAKES / f"_tmp_{a.shot}"
    shutil.rmtree(tmp, ignore_errors=True)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        ctx = br.new_context(viewport={"width": W, "height": H}, device_scale_factor=1, color_scheme=a.theme,
                             record_video_dir=str(tmp), record_video_size={"width": W, "height": H})
        page = ctx.new_page()
        SHOTS[a.shot](page, a.url)
        vid = page.video.path()
        ctx.close()
        br.close()
    out = TAKES / f"{a.shot}.webm"
    shutil.move(vid, out)
    shutil.rmtree(tmp, ignore_errors=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
