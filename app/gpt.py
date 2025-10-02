# app/gpt.py
import os
from datetime import date

try:
    from openai import OpenAI
except Exception:  # openai lib nemusí byť dostupná pri lokálnom teste
    OpenAI = None

def _fallback_comment(current_percent: float, delta: float | None, trend7: float, yoy_gap: float) -> str:
    d = "—" if delta is None else f"{delta:+.2f} p.b."
    t = f"{trend7:+.2f} p.b./7d"
    y = f"{yoy_gap:+.2f} p.b. vs. 2024"
    tone = "stabilný" if abs(trend7) < 0.1 else ("rastový" if trend7 > 0 else "klesajúci")
    return (
        f"Zásobníky sú na {current_percent:.2f} %, denná zmena {d}. "
        f"Krátkodobý trend je {tone} ({t}) a medziročne {y}. "
        f"Vývoj zodpovedá sezóne; riziká: počasie, LNG prílevy, neplánované odstávky."
    )

def generate_comment(current_percent: float, delta: float | None, trend7: float, yoy_gap: float) -> str:
    """Vráti krátky komentár. Ak nie je OPENAI_API_KEY alebo model nedostupný, použije fallback."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or OpenAI is None:
        return _fallback_comment(current_percent, delta, trend7, yoy_gap)

    client = OpenAI(api_key=api_key)
    prompt = (
        "Napíš 2–3 vety k situácii zásobníkov plynu v EÚ v slovenčine. "
        f"Aktuálne: {current_percent:.2f} %, denná zmena: "
        f"{'—' if delta is None else f'{delta:+.2f} p.b.'}. "
        f"7-dňový trend: {trend7:+.2f} p.b., medziročný rozdiel vs. 2024: {yoy_gap:+.2f} p.b. "
        "Buď vecný, bez prehnaných varovaní; uveď kľúčové riziká (počasie, LNG, odstávky)."
    )
    # Dôležité: žiadna 'temperature' — niektoré modely podporujú len default=1
    resp = client.responses.create(model="gpt-5", input=prompt)
    try:
        return resp.output_text.strip()
    except Exception:
        return _fallback_comment(current_percent, delta, trend7, yoy_gap)
