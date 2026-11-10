"""Render the Devpost thumbnail and gallery images (1800x1200, 3:2) from media/gallery.html.

  python media/gallery.py        # -> media/gallery/01_thumb.png ... 08_how.png

Run after media/record.py slides and the screenshots are current; every number on them is media/stated_numbers.py's.
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "gallery"
ORDER = ["thumb", "story", "sbs", "phone", "book", "finding", "careful", "how"]


def main():
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        pg = br.new_page(viewport={"width": 1800, "height": 1200})
        for i, g in enumerate(ORDER, 1):
            pg.goto((HERE / "gallery.html").as_uri() + "?g=" + g)   # a query, not a hash: a hash change does not reload
            pg.wait_for_timeout(1200)
            path = OUT / f"{i:02d}_{g}.png"
            pg.screenshot(path=str(path))
            print("wrote", path.name)
        br.close()


if __name__ == "__main__":
    main()
