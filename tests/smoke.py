"""Drive the real page in Chromium: log in, click things, assert no errors.

index.html ships as a single inline <script>, so a parse error disables
every control on the page while still serving a 200. That shipped once.
These checks exercise the page the way a person does, with the n8n backend
aborted so the degraded paths are covered too.

Run: CHROMIUM_PATH=... python tests/smoke.py
"""
import functools
import http.server
import os
import pathlib
import socketserver
import sys
import threading
from playwright.sync_api import sync_playwright

ROOT = str(pathlib.Path(__file__).resolve().parents[1])
PORT = 8731

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
class Quiet(socketserver.TCPServer):
    allow_reuse_address = True
    def handle_error(self, *a): pass
srv = Quiet(("127.0.0.1", PORT), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()

CODE = os.environ.get("DORI_ACCESS_CODE")
if not CODE:
    sys.exit("set DORI_ACCESS_CODE to the current access code")

errors, console = [], []
fails = []

with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
    pg = b.new_page()
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: console.append(f"{m.type}: {m.text}"))
    # n8n is unreachable from here; fail every call so we also exercise the
    # degraded paths rather than only the happy one.
    pg.route("**/n8n.joelycannoli.com/**", lambda r: r.abort())
    pg.goto(f"http://127.0.0.1:{PORT}/index.html")

    def check(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond: fails.append(name)

    check("auth gate visible", pg.is_visible("#pw"))
    check("app hidden before login", not pg.is_visible("#dori-input"))

    # Wrong code must be rejected.
    pg.fill("#pw", "wrong"); pg.click("[data-action='login']")
    pg.wait_for_timeout(300)
    check("wrong code rejected", "ACCESS DENIED" in pg.inner_text("#err"))

    # Correct code, via the delegated login action.
    pg.fill("#pw", CODE); pg.click("[data-action='login']")
    pg.wait_for_timeout(900)
    check("login dismisses gate", pg.is_visible("#dori-input"))

    # The auto-question fires at 800ms and the backend is dead: it must
    # degrade to a message, not hang or throw.
    pg.wait_for_timeout(2500)
    msgs = pg.inner_text("#dori-messages")
    check("degrades when backend is down", "Unable to reach data systems" in msgs)

    # F13: typing during the auto-question must not be wiped.
    pg.fill("#dori-input", "typed by hand")
    pg.wait_for_timeout(200)
    check("F13 input preserved", pg.input_value("#dori-input") == "typed by hand")
    pg.fill("#dori-input", "")

    # Delegated sidebar action (data-ask) via click.
    before = pg.inner_text("#dori-messages")
    pg.click("[data-ask='What deals are closing soon?']")
    pg.wait_for_timeout(1500)
    check("data-ask click dispatches", "closing soon" in pg.inner_text("#dori-messages").lower()
          and pg.inner_text("#dori-messages") != before)

    # Keyboard activation of a role=button div.
    n_before = pg.inner_text("#dori-messages").count("Stale Deals") + len(pg.inner_text("#dori-messages"))
    pg.focus("[data-ask='Which deals are stale and need follow-up?']")
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(1500)
    txt = pg.inner_text("#dori-messages")
    check("keyboard activates data-ask once", txt.count("Which deals are stale and need follow-up?") == 1)

    # F12: no duplicate thinking ids left orphaned.
    check("no orphaned thinking node", pg.locator('[id^="dori-thinking-"]').count() == 0)

    # Escape closes the mobile sidebar (F26).
    pg.set_viewport_size({"width": 390, "height": 780})
    pg.click("[data-action='toggle-sidebar']")
    pg.wait_for_timeout(300)
    opened = "mobile-open" in (pg.get_attribute("#main-sidebar", "class") or "")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(300)
    closed = "mobile-open" not in (pg.get_attribute("#main-sidebar", "class") or "")
    check("F26 escape closes sidebar", opened and closed)

    # Send button still works through delegation.
    pg.set_viewport_size({"width": 1280, "height": 900})
    pg.fill("#dori-input", "ping")
    pg.click("[data-action='send']")
    pg.wait_for_timeout(1500)
    check("send button dispatches", "ping" in pg.inner_text("#dori-messages"))

    # F21: the KPI badge must say something honest when the backend is down.
    badge = pg.inner_text("#gauge-gci-badge")
    check(f"F21 badge reports failure (got {badge!r})", "UNAVAILABLE" in badge.upper())

    b.close()

srv.shutdown()
print("\nUncaught page errors:", errors or "none")
noise = [c for c in console if c.startswith("error:") and "net::" not in c and "Failed to load" not in c]
print("Console errors (excluding expected network):", noise or "none")
if fails or errors or noise:
    print("\nFAILURES:", fails); sys.exit(1)
print("\nall browser checks passed")
