"""Сайт в настоящем браузере: страница открывается без ошибок, главные разделы заполняются.

Нужны Chrome/Chromium и собранные данные (python scripts/build.py); иначе тест пропускается.
Страница открывается в headless Chrome, после расчётов берётся готовый DOM (--dump-dom).
"""
from __future__ import annotations

import functools
import html
import http.server
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
CHROME = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")

pytestmark = pytest.mark.skipif(not CHROME or not (SITE / "data/dashboard.json").exists(),
                                reason="нужны Chrome и собранные данные (scripts/build.py)")


@pytest.fixture(scope="module")
def base():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


def dom(url: str, width: int = 1280) -> str:
    with tempfile.TemporaryDirectory() as prof:
        out = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", f"--user-data-dir={prof}",
                              f"--window-size={width},2000", "--virtual-time-budget=15000", "--dump-dom", url],
                             capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout


def text(page: str, id_: str) -> str:
    m = re.search(rf'id="{id_}"[^>]*>(.*?)</', page, re.S)
    assert m, f"нет элемента #{id_}"
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()


def no_errors(page: str) -> None:
    m = re.search(r'<html[^>]*data-js-errors="([^"]*)"', page)
    assert not m, f"ошибки на странице: {html.unescape(m.group(1))}"
    assert "Не удалось" not in page


@pytest.mark.parametrize("width", [1280, 390])
def test_main_page_renders_and_tour_starts(base, width):
    page = dom(f"{base}?tour=1&city={quote('Казань')}&goal=160", width)
    no_errors(page)
    assert 'id="app" aria-busy="false"' in page
    assert text(page, "kpi-tons").endswith("т")
    # обзор открылся на первом шаге
    assert re.search(r'class="tour-count">1 из \d+<', page)
    # лист координатора — Казань, в таблице есть строки
    assert "Казань" in text(page, "city-title")
    city = page[page.index('id="city-table"'):]
    assert city.count("<tr") > 5
    # цель: посчитано, сколько смен добавить
    assert re.fullmatch(r"[\d\s ]+\+?", text(page, "goal-need"))
    assert "смен" in text(page, "goal-verdict")


def test_demo_upload_runs_in_browser(base):
    page = dom(f"{base}?shot=upload&demo=1")
    no_errors(page)
    assert text(page, "up-tons").endswith("т")
    assert "%" in text(page, "up-wape")
    assert "Готово за" in text(page, "up-status")
