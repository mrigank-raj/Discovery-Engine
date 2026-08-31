"""
Keeps the Wishlist Signal Engine's Streamlit Community Cloud app awake.

Streamlit's free tier puts an app to sleep after ~12 hours without a visitor.
A plain HTTP GET does NOT wake it — it returns a static "Zzz" shell without
starting the actual Python app. Waking it requires a real browser to load the
page and click the "Yes, get this app back up!" button, which is what this
script does via headless Chromium (Playwright).

This is fully separate from pipeline.py and the weekly discovery pipeline —
it makes no calls to Groq, Gemini, Supabase, or any other API in this project,
and does not touch or consume any of that quota.

Saves before/after screenshots to ./keepalive-evidence/ so a run's actual
result can be inspected (via the workflow's uploaded artifact) instead of
being inferred from log text alone.
"""

import sys
import os
from playwright.sync_api import sync_playwright

APP_URL = "https://discovery-engine-mvnj5ft2fjrnbcvzyphqka.streamlit.app"
WAKE_BUTTON_TEXT = "Yes, get this app back up!"
NAV_TIMEOUT_MS = 45_000
EVIDENCE_DIR = "keepalive-evidence"


def main() -> int:
    os.makedirs(EVIDENCE_DIR, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            page.goto(APP_URL, timeout=NAV_TIMEOUT_MS, wait_until="load")
            # Give any client-side rendering (Streamlit's sleep-screen shell
            # included) a real moment to finish painting before we look for
            # the button — checking immediately after "domcontentloaded" was
            # the likely cause of missed clicks in earlier runs.
            page.wait_for_timeout(5_000)
            page.screenshot(path=f"{EVIDENCE_DIR}/01_initial_state.png")

            wake_button = page.get_by_role("button", name=WAKE_BUTTON_TEXT)
            found = wake_button.count() > 0
            if not found:
                # Fall back to a plain text match in case it isn't exposed
                # with an accessible "button" role.
                wake_button = page.get_by_text(WAKE_BUTTON_TEXT, exact=False)
                found = wake_button.count() > 0

            if found:
                print("App appears asleep — attempting to click wake button...")
                wake_button.first.click(timeout=10_000)
                # Real cold boots can take well over a minute. Wait generously
                # and screenshot the result so it's verifiable, not assumed.
                page.wait_for_timeout(60_000)
                page.screenshot(path=f"{EVIDENCE_DIR}/02_after_click.png")

                still_sleeping = page.get_by_text(WAKE_BUTTON_TEXT, exact=False).count() > 0
                if still_sleeping:
                    print("WARNING: sleep screen still present 60s after click — "
                          "boot may still be in progress, or click did not register. "
                          "See 02_after_click.png.")
                else:
                    print("Sleep screen is gone after click — app appears to be waking/awake.")
            else:
                print("No wake button detected — app is already awake. See 01_initial_state.png.")

            return 0
        except Exception as exc:  # noqa: BLE001 — best-effort keepalive, never fail the workflow
            print(f"Keepalive check failed (non-fatal): {exc}")
            try:
                page.screenshot(path=f"{EVIDENCE_DIR}/error_state.png")
            except Exception:
                pass
            return 0
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
