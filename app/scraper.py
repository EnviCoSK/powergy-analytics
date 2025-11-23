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

    # AGSI API má oneskorenie - dáta pre dnešok ešte nemusia byť dostupné
    # Použijeme včerajšok ako maximálny dátum
    max_date = dt.date.today() - dt.timedelta(days=1)

    base = {
        "type": "eu",                    # 🔑 kľúčové
        "from": from_date,
        "to": max_date.isoformat(),      # Použijeme včerajšok, nie dnes
        "size": 5000,                   # veľká strana, menej requestov
        "gas_day": "asc",               # staršie → novšie
    }

    return fetch_pages(base)

def _fetch_agsi_eu_full(date_str: str) -> float | None:
    """Vráti percento naplnenia 'full' pre EU v daný gas_day (YYYY-MM-DD), alebo None."""
    if not AGSI_API_KEY:
        return None
    url = "https://agsi.gie.eu/api"
    params = {
        "type": "eu",
        "from": date_str,
        "to": date_str,
        "size": 100,
        "gas_day": "asc",
        "page": 1,
    }
    headers = {"x-key": AGSI_API_KEY}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=25)
        r.raise_for_status()
        j = r.json()
        data = j.get("data") or []
        if not data:
            return None
        # Hľadáme presný záznam pre daný deň
        # gasDayStart môže byť v rôznych formátoch: "2025-11-20" alebo "2025-11-20T00:00:00+00:00"
        date_str_clean = date_str[:10]  # Zajistíme len dátum bez času
        for item in data:
            gas_day = item.get("gasDayStart") or item.get("gas_day") or ""
            gas_day_str = str(gas_day)[:10]  # Vezmeme len prvých 10 znakov (YYYY-MM-DD)
            if gas_day_str == date_str_clean:
                try:
                    full_val = item.get("full") or item.get("fullness") or item.get("percentage")
                    if full_val is not None:
                        return float(full_val)
                except Exception:
                    continue
        # fallback: ak je len jeden záznam, použi ho
        if len(data) > 0:
            try:
                full_val = data[-1].get("full") or data[-1].get("fullness") or data[-1].get("percentage")
                if full_val is not None:
                    return float(full_val)
            except Exception:
                pass
        return None
    except Exception as e:
        print(f"Error fetching AGSI data for {date_str}: {e}")
        return None

def run_daily_agsi():
    """
    Dotiahne a uloží posledný dostupný deň z AGSI (EU 'full' %), spraví upsert a spočíta deltu.
    Používa AGSI API namiesto KYOS scrapingu.
    """
    import sys
    print("=" * 60, file=sys.stderr)
    print(f"Starting run_daily_agsi at {dt.datetime.now()}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    
    if not AGSI_API_KEY:
        error_msg = "Missing AGSI_API_KEY"
        print(f"ERROR: {error_msg}", file=sys.stderr)
        raise RuntimeError(error_msg)
    
    print(f"AGSI_API_KEY is set: {bool(AGSI_API_KEY)}", file=sys.stderr)
    
    try:
        init_db()
        print("Database initialized", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Database initialization error: {e}", file=sys.stderr)
    
    sess = SessionLocal()
    try:
        # Najprv zistíme posledný dátum v DB
        last_row = sess.query(GasStorageDaily).order_by(GasStorageDaily.date.desc()).first()
        # Pre sezónne porovnanie potrebujeme dáta minimálne od 2021
        last_date = last_row.date if last_row else dt.date(2021, 1, 1)
        
        # Skúsime stiahnuť dáta od posledného dátumu + 1 deň až po dnes
        today = dt.date.today()
        days_missing = (today - last_date).days
        
        # Ak je posledný dátum starší ako 2 dni, použijeme backfill
        if days_missing > 2:
            print(f"Last date in DB is {last_date} ({days_missing} days ago), using backfill from {last_date + dt.timedelta(days=1)}")
            try:
                start_date = last_date + dt.timedelta(days=1)
                result = backfill_agsi(str(start_date))
                print(f"Backfill result: {result}")
                # Po backfille aktualizujeme last_date a refreshneme session
                sess.expire_all()
                last_row = sess.query(GasStorageDaily).order_by(GasStorageDaily.date.desc()).first()
                last_date = last_row.date if last_row else last_date
                print(f"After backfill, last date is: {last_date}")
            except Exception as e:
                print(f"Backfill failed: {e}, continuing with single day fetch")
                import traceback
                traceback.print_exc()
        
        # AGSI API má oneskorenie - dáta pre dnešok ešte nemusia byť dostupné
        # Skúsime najnovšie dáta od včerajška dozadu
        # Aktualizujeme last_date po backfille (ak sa vykonal)
        if days_missing > 2:
            # Po backfille sme už aktualizovali last_date v riadku 208
            pass
        
        candidates = []
        # Skúsime najnovšie dáta od včerajška dozadu (nie dnes, lebo AGSI má oneskorenie)
        for i in range(1, 6):  # Včera až 5 dní dozadu
            candidate = today - dt.timedelta(days=i)
            # Pridáme len dátumy, ktoré sú >= last_date (aby sme nepreskakovali)
            if candidate >= last_date:
                candidates.append(str(candidate))
        
        # Ak nemáme žiadne kandidáty (napr. ak last_date je v budúcnosti), použijeme aspoň posledných 5 dní
        if not candidates:
            for i in range(1, 6):
                candidates.append(str(today - dt.timedelta(days=i)))
        
        picked_date = None
        picked_full = None
        for d in candidates:
            val = _fetch_agsi_eu_full(d)
            if val is not None:
                picked_date = d
                picked_full = round(float(val), 2)
                print(f"Found AGSI data for {d}: {picked_full}%")
                break
        
        if picked_date is None:
            raise RuntimeError(f"No AGSI data for candidates: {candidates}")
        
        # Upsert do DB
        d = dt.date.fromisoformat(picked_date)
        row = sess.query(GasStorageDaily).filter(GasStorageDaily.date == d).first()
        
        # nájdi včerajšok pre deltu
        prev_date = d - dt.timedelta(days=1)
        prev = sess.query(GasStorageDaily).filter(GasStorageDaily.date == prev_date).first()
        prev_percent = float(prev.percent) if prev and prev.percent is not None else None
        delta = None if prev_percent is None else round(picked_full - prev_percent, 2)
        
        # Vypočítaj trend7 (7-dňový trend) a yoy_gap (medziročný rozdiel)
        trend7 = 0.0
        yoy_gap = 0.0
        try:
            # 7-dňový trend
            week_ago = d - dt.timedelta(days=7)
            week_ago_row = sess.query(GasStorageDaily).filter(GasStorageDaily.date == week_ago).first()
            if week_ago_row and week_ago_row.percent is not None:
                trend7 = round(picked_full - float(week_ago_row.percent), 2)
            
            # Medziročný rozdiel
            try:
                prev_year_date = d.replace(year=d.year - 1)
            except ValueError:  # 29. február
                prev_year_date = d - dt.timedelta(days=365)
            prev_year_row = sess.query(GasStorageDaily).filter(GasStorageDaily.date == prev_year_date).first()
            if prev_year_row and prev_year_row.percent is not None:
                yoy_gap = round(picked_full - float(prev_year_row.percent), 2)
        except Exception:
            pass
        
        # Generuj komentár (ak je OPENAI_API_KEY dostupný, inak použije fallback)
        try:
            from .gpt import generate_comment
            comment = generate_comment(picked_full, delta, trend7, yoy_gap)
        except Exception as e:
            print(f"Warning: Could not generate comment with GPT: {e}, using fallback", file=sys.stderr)
            # Fallback komentár
            d = "—" if delta is None else f"{delta:+.2f} p.b."
            y = "—" if yoy_gap is None else f"{yoy_gap:+.2f} p.b. vs. 2024"
            comment = (
                f"Zásobníky sú na {picked_full:.2f} %, denná zmena {d}. "
                f"Medziročný rozdiel je {y}. "
                f"Vývoj zodpovedá sezóne; riziká: počasie, prítoky LNG a prípadné neplánované odstávky."
            )
        
        if row:
            row.percent = picked_full
            row.delta = delta
            row.comment = comment
        else:
            sess.add(GasStorageDaily(date=d, percent=picked_full, delta=delta, comment=comment))
        
        sess.commit()
        result = {"ok": True, "date": picked_date, "percent": picked_full, "delta": delta}
        print(f"SUCCESS: {result}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        return result
    except Exception as e:
        sess.rollback()
        import traceback
        error_trace = traceback.format_exc()
        print(f"ERROR in run_daily_agsi: {e}", file=sys.stderr)
        print(error_trace, file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        raise
    finally:
        sess.close()

def backfill_agsi(from_date: str = "2021-01-01"):
    """
    Načíta historické denné naplnenie zásobníkov pre EÚ z AGSI+ a uloží do DB.
    Expect: from_date = 'YYYY-MM-DD'
    Používa upsert logiku - aktualizuje existujúce záznamy, pridáva nové.
    Pre sezónne porovnanie v grafe potrebujeme dáta minimálne od 2021-01-01.
    """
    if not AGSI_API_KEY:
        raise RuntimeError("Missing AGSI_API_KEY")

    rows = _agsi_fetch_all(from_date)

    sess = SessionLocal()
    inserted, updated = 0, 0
    try:
        # Získame všetky existujúce dátumy naraz pre rýchlejšie vyhľadávanie
        existing_dates = {
            r.date: r 
            for r in sess.query(GasStorageDaily).all()
        }
        
        for row in rows:
            # dátum môže byť 'gasDayStart' alebo 'gas_day'
            d = (row.get("gasDayStart") or row.get("gas_day") or row.get("date") or "")[:10]
            # percentá bývajú 'full' | 'fullness' | 'percentage'
            p = row.get("full") or row.get("fullness") or row.get("percentage")
            if not d or p is None:
                continue
            
            try:
            d_obj = dt.date.fromisoformat(d)
            p_val = float(p)
            except (ValueError, TypeError):
                continue

            # Použijeme cache existujúcich dátumov
            rec = existing_dates.get(d_obj)
            if rec:
                # Aktualizujeme vždy, aj ak sa hodnota nezmenila (pre istotu)
                old_percent = rec.percent
                    rec.percent = p_val
                # Počítame ako update len ak sa hodnota skutočne zmenila
                if abs(old_percent - p_val) > 0.001:  # Použijeme malú toleranciu pre float porovnanie
                    updated += 1
                else:
                    # Záznam už existuje s rovnakou hodnotou - stále to počítame ako "processed"
                    pass
            else:
                # Nový záznam - pridáme do session a do cache
                new_rec = GasStorageDaily(date=d_obj, percent=p_val, delta=None, comment=None)
                sess.add(new_rec)
                existing_dates[d_obj] = new_rec  # Pridáme do cache, aby sme zabránili duplikátom
                inserted += 1

        # Commitneme aj ak sa nič nezmenilo (pre istotu)
        sess.commit()
        
        # Po commite vypočítame delty pre všetky záznamy od from_date
        # Vypočítame delty aj ak sme len overili existujúce záznamy
        if len(rows) > 0:
            try:
                # Vypočítame delty pre záznamy od from_date (vrátane predchádzajúceho dňa pre správny výpočet)
                from sqlalchemy import text
                start_date_obj = dt.date.fromisoformat(from_date)
                # Potrebujeme aj predchádzajúci deň pre správny výpočet delty
                prev_day = start_date_obj - dt.timedelta(days=1)
                
                sess.execute(text("""
                    WITH lagged AS (
                      SELECT date,
                             LAG(percent) OVER (ORDER BY date) AS lag_percent
                      FROM gas_storage_daily
                      WHERE date >= :prev_day
                    )
                    UPDATE gas_storage_daily g
                       SET delta = CASE
                                     WHEN l.lag_percent IS NULL THEN NULL
                                     ELSE ROUND((g.percent - l.lag_percent)::numeric, 2)::double precision
                                   END
                      FROM lagged l
                     WHERE l.date = g.date
                       AND g.date >= :start_date
                """), {"start_date": start_date_obj, "prev_day": prev_day})
                sess.commit()
                print(f"Updated deltas for dates >= {from_date}")
            except Exception as e:
                print(f"Warning: Failed to update deltas: {e}")
                import traceback
                traceback.print_exc()
        
        # Vrátime informáciu aj o tom, koľko záznamov už existovalo
        existing_count = len(rows) - inserted - updated
        
        return {
            "inserted": inserted, 
            "updated": updated, 
            "source_count": len(rows),
            "already_exists": existing_count,
            "processed": inserted + updated + existing_count
        }
    except Exception as e:
        sess.rollback()
        raise RuntimeError(f"Backfill failed: {str(e)}") from e
    finally:
        sess.close()

if __name__ == "__main__":
    # Použi AGSI ak je dostupný, inak KYOS
    if AGSI_API_KEY:
        run_daily_agsi()
    else:
    run_daily()
