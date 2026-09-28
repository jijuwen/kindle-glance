"""Render Lingdong Huang's original {Shan, Shui}* generator for Kindle."""

from __future__ import annotations

import io
import os
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageFilter, ImageOps


ASSET_DIR = Path(__file__).with_name("assets") / "shan-shui-inf"
RENDER_HTML = ASSET_DIR / "render.html"


def scene_period(now: datetime) -> tuple[str, str]:
    """Return a stable date/period pair for 06:00, 12:00, 18:00 and 23:00 scenes."""
    if now.hour < 6:
        return (now - timedelta(days=1)).date().isoformat(), "night"
    if now.hour < 12:
        return now.date().isoformat(), "morning"
    if now.hour < 18:
        return now.date().isoformat(), "noon"
    if now.hour < 23:
        return now.date().isoformat(), "evening"
    return now.date().isoformat(), "night"


def scene_seed(now: datetime, variant: int = 0) -> str:
    day, period = scene_period(now)
    return f"kindle-shan-shui:{day}:{period}:{max(0, int(variant))}"


def _chromium_executable() -> str:
    configured = os.getenv("CHROMIUM_EXECUTABLE", "").strip()
    candidates = [
        configured,
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("Chromium executable was not found")


def render_original(width: int, height: int, seed: str) -> Image.Image:
    """Execute the pinned upstream JavaScript and capture its generated SVG scene."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:  # pragma: no cover - deployment dependency guard
        raise RuntimeError("Playwright is required for Shan Shui rendering") from error

    if not RENDER_HTML.is_file():
        raise RuntimeError("Shan Shui source is unavailable")
    # The upstream composition is authored around an 800-unit-high scroll. Keep
    # that coordinate system, crop it to the Kindle aspect ratio, then let SVG
    # scale uniformly to the native framebuffer. This fills 4:3 without
    # stretching mountains or leaving a large empty band below the landscape.
    scene_height = 800
    scene_width = round(scene_height * width / height)
    url = (
        f"{RENDER_HTML.resolve().as_uri()}?seed={quote(seed, safe='')}"
        f"&width={scene_width}&height={scene_height}"
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=_chromium_executable(),
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-crash-reporter",
                "--disable-crashpad",
                "--no-sandbox",
                "--hide-scrollbars",
            ],
            env={
                **os.environ,
                "HOME": "/tmp",
                "XDG_CACHE_HOME": "/tmp/.cache",
                "XDG_CONFIG_HOME": "/tmp/.config",
            },
        )
        try:
            page = browser.new_page(
                viewport={"width": int(width), "height": int(height)},
                device_scale_factor=1,
            )
            page.goto(url, wait_until="load", timeout=90_000)
            page.wait_for_function(
                "document.querySelector('#BG > svg#SVG') !== null",
                timeout=90_000,
            )
            page.evaluate(
                """([width, height]) => {
                    document.documentElement.style.background = '#fff';
                    document.body.style.background = '#fff';
                    const bg = document.getElementById('BG');
                    bg.style.width = width + 'px';
                    bg.style.height = height + 'px';
                    const svg = document.getElementById('SVG');
                    svg.setAttribute('width', width);
                    svg.setAttribute('height', height);
                    svg.style.display = 'block';
                }""",
                [int(width), int(height)],
            )
            png = page.locator("#BG").screenshot(type="png", timeout=90_000)
        finally:
            browser.close()
    with Image.open(io.BytesIO(png)) as opened:
        image = opened.convert("L")
    if image.size != (width, height):
        image = ImageOps.fit(image, (width, height), method=Image.Resampling.LANCZOS)
    return image


def optimize_for_kindle(image: Image.Image) -> Image.Image:
    """Strengthen pale ink and fine strokes while retaining grayscale layers."""
    gray = image.convert("L")
    strengthened = gray.point(
        lambda value: max(0, min(255, round(255 - (255 - value) * 1.24)))
    )
    return strengthened.filter(ImageFilter.UnsharpMask(radius=0.7, percent=115, threshold=2))


def apply_render_mode(image: Image.Image, mode: str) -> Image.Image:
    if mode == "kindle_gray":
        return optimize_for_kindle(image)
    return image.convert("L")
