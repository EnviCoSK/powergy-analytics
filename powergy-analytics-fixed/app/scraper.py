import re
import datetime as dt
from playwright.sync_api import sync_playwright
from sqlalchemy import select
from .settings import KYOS_URL, OPENAI_API_KEY
from .database import SessionLocal, init_db
from .models import GasStorageDaily
from .gpt import generate_comment

def _extract_percent_from_html(html: str) -> float | None:
    m = re.search(r"(\d{2,3}\.\d)\s?%", html)
    if m:
        return float(m.group(1))
    return None

def fetch_kyos_percent() -> float:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(KYOS_URL, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        html = page.content()
        browser.close()
    value = _extract_percent_from_html(html)
    if value is None:
        raise RuntimeError("Nepodarilo sa extrahovať percento zo stránky KYOS.")
    return value

def run_daily():
    init_db()
    today = dt.date.today()
    sess = SessionLocal()

    yesterday = today - dt.timedelta(days=1)
    prev = sess.execute(
        select(GasStorageDaily).where(GasStorageDaily.date == yesterday)
    ).scalar_one_or_none()

    current = fetch_kyos_percent()

    delta = None
    if prev:
        delta = round(current - prev.percent, 3)

    comment = generate_comment(OPENAI_API_KEY, current, delta)

    existing = sess.execute(
        select(GasStorageDaily).where(GasStorageDaily.date == today)
    ).scalar_one_or_none()

    if existing:
        existing.percent = current
        existing.delta = delta
        existing.comment = comment
    else:
        rec = GasStorageDaily(date=today, percent=current, delta=delta, comment=comment)
        sess.add(rec)

    sess.commit()
    sess.close()

if __name__ == "__main__":
    run_daily()
