"""Regenerate every README image from the live Studio UI.

    pip install playwright pillow
    python assets/make_screenshots.py        # uses your installed Chrome, no browser download

Starts its own API server on a spare port, drives each page into an
interesting state, and writes the PNGs plus tour.gif next to this script.
"""
import io
import os
import threading

from PIL import Image
from playwright.sync_api import sync_playwright

from busbench.server import make_server

OUT = os.path.dirname(os.path.abspath(__file__))


def main():
    srv = make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    frames = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--lang=en-US"])
        page = browser.new_page(viewport={"width": 1480, "height": 920}, device_scale_factor=1.25)

        def go(name):
            page.goto(url + "#/" + name)
            page.wait_for_timeout(900)

        def shot(name):
            page.wait_for_timeout(400)
            png = page.screenshot(path=os.path.join(OUT, f"{name}.png"))
            frames.append(Image.open(io.BytesIO(png)).convert("RGB").resize((1110, 690), Image.LANCZOS))

        go("overview")
        page.click("#run-tests")
        page.wait_for_function("() => document.querySelectorAll('.mcard .chip.pass').length >= 20", timeout=240000)
        page.wait_for_timeout(800)
        shot("overview")

        go("can")
        page.click("#can-frames tr[data-i='1']")
        page.click("#can-sig [data-s='4']")          # SteeringAngle: Motorola, signed
        shot("can")

        go("uds")
        for label in ("Read VIN", "Read engine speed (slow)", "Write DID 0xF199"):
            page.click(f"button.preset:has-text('{label}')")
            page.wait_for_timeout(250)
        shot("uds")

        go("autosar")
        page.click("#aut-run5")
        page.wait_for_timeout(600)
        shot("autosar")

        go("safety")
        for _ in range(3):
            page.click("#fm-report")
            page.wait_for_timeout(150)
        shot("safety")

        go("doip")
        for i in range(4):
            page.click(f"[data-step='{i}']")
            page.wait_for_timeout(300)
        shot("doip")

        go("arinc429")
        page.click("#a4-table tr[data-i='4']")      # decodes fine, SSM says no computed data
        shot("arinc429")

        go("mil1553")
        page.click("#m-go")
        page.wait_for_timeout(300)
        page.click("#m-run")
        shot("mil1553")

        go("arinc653")
        shot("arinc653")

        go("traceability")
        shot("traceability")

        go("fdr")
        page.click("#f-buses")
        page.wait_for_timeout(300)
        page.click("#f-ten")
        page.wait_for_timeout(300)
        page.click("[data-slot='5']")
        page.click("#f-corrupt")
        page.wait_for_timeout(300)
        shot("fdr")
        browser.close()

    frames[0].save(os.path.join(OUT, "tour.gif"), save_all=True, append_images=frames[1:],
                   duration=1700, loop=0, optimize=True)
    srv.shutdown()
    print("images written to", OUT)


if __name__ == "__main__":
    main()
