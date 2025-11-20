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

    # Vypočítaj trend7 (7-dňový trend) a yoy_gap (medziročný rozdiel)
    trend7 = 0.0
    yoy_gap = 0.0
    try:
        # 7-dňový trend: rozdiel medzi dnes a pred 7 dňami
        week_ago = today - dt.timedelta(days=7)
        week_ago_row = sess.execute(
            select(GasStorageDaily).where(GasStorageDaily.date == week_ago)
        ).scalar_one_or_none()
        if week_ago_row:
            trend7 = round(current - week_ago_row.percent, 2)
        
        # Medziročný rozdiel
        try:
            prev_year_date = today.replace(year=today.year - 1)
        except ValueError:  # 29. február
            prev_year_date = today - dt.timedelta(days=365)
        prev_year_row = sess.execute(
            select(GasStorageDaily).where(GasStorageDaily.date == prev_year_date)
        ).scalar_one_or_none()
        if prev_year_row:
            yoy_gap = round(current - prev_year_row.percent, 2)
    except Exception:
        pass  # Použijeme default hodnoty 0.0

    comment = generate_comment(current, delta, trend7, yoy_gap)

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

import os
import requests

AGSI_API_KEY = os.getenv("AGSI_API_KEY", "")

def _agsi_fetch_all(from_date: str) -> list[dict]:
    """
    Stiahne všetky stránky agregovaných dát pre celú EÚ (type=eu).
    Žiadny 'country', žiadny 'dataset'. Paginácia podľa 'last_page'.
    """
    headers = {"x-key": AGSI_API_KEY}
    url = "https://agsi.gie.eu/api"

    def fetch_pages(params: dict) -> list[dict]:
        out: list[dict] = []
        page = 1
        last_page = 1
        while page <= last_page:
            p = dict(params)
            p["page"] = page
            r = requests.get(url, params=p, headers=headers, timeout=60)
            r.raise_for_status()
            j = r.json()
            last_page = int((j.get("last_page") or 1)) if isinstance(j, dict) else 1
            data = j.get("data") if isinstance(j, dict) else None
            if isinstance(data, list) and data:
                out.extend(data)
            page += 1
        return out

    base = {
        "type": "eu",                    # 🔑 kľúčové
        "from": from_date,
        "to": dt.date.today().isoformat(),
        "size": 5000,                   # veľká strana, menej requestov
        "gas_day": "asc",               # staršie → novšie
    }

    return fetch_pages(base)

def backfill_agsi(from_date: str = "2025-01-01"):
    """
    Načíta historické denné naplnenie zásobníkov pre EÚ z AGSI+ a uloží do DB.
    Expect: from_date = 'YYYY-MM-DD'
    """
    if not AGSI_API_KEY:
        raise RuntimeError("Missing AGSI_API_KEY")

    rows = _agsi_fetch_all(from_date)

    sess = SessionLocal()
    inserted, updated = 0, 0
    try:
        for row in rows:
            # dátum môže byť 'gasDayStart' alebo 'gas_day'
            d = (row.get("gasDayStart") or row.get("gas_day") or row.get("date") or "")[:10]
            # percentá bývajú 'full' | 'fullness' | 'percentage'
            p = row.get("full") or row.get("fullness") or row.get("percentage")
            if not d or p is None:
                continue
            d_obj = dt.date.fromisoformat(d)
            p_val = float(p)

            rec = sess.query(GasStorageDaily).filter(GasStorageDaily.date == d_obj).first()
            if rec:
                if rec.percent != p_val:
                    rec.percent = p_val
                    updated += 1
            else:
                sess.add(GasStorageDaily(date=d_obj, percent=p_val, delta=None, comment=None))
                inserted += 1

        sess.commit()
        return {"inserted": inserted, "updated": updated, "source_count": len(rows)}
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()

if __name__ == "__main__":
    run_daily()
