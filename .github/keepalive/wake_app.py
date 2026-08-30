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
"""

import sys
from playwright.sync_api import sync_playwright

APP_URL = "https://discovery-engine-mvnj5ft2fjrnbcvzyphqka.streamlit.app"
WAKE_BUTTON_TEXT = "Yes, get this app back up!"
TIMEOUT_MS = 30_000


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(APP_URL, timeout=TIMEOUT_MS, wait_until="domcontentloaded")

            # If the app is sleeping, a wake button appears. If it's already
            # awake, this simply won't be found and we do nothing further.
            wake_button = page.get_by_text(WAKE_BUTTON_TEXT, exact=False)
            if wake_button.count() > 0:
                print("App is asleep — clicking wake button...")
                wake_button.first.click()
                # Give the app a real moment to boot before we close the browser,
                # otherwise the wake request can be dropped mid-flight.
                page.wait_for_timeout(15_000)
                print("Wake click sent.")
            else:
                print("App is already awake — nothing to do.")

            return 0
        except Exception as exc:  # noqa: BLE001 — this is a best-effort keepalive job
            print(f"Keepalive check failed (non-fatal): {exc}")
            return 0  # never fail the workflow over a flaky single run
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
