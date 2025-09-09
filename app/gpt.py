from openai import OpenAI

def generate_comment(api_key: str, today_value: float, delta: float | None):
    client = OpenAI(api_key=api_key)
    delta_txt = "0.0" if delta is None else f"{delta:.2f}"
    prompt = f"""Napíš krátke, vecné zhrnutie pre obchodníkov s plynom (ľudskou rečou, ale odborne):
- Aktuálna naplnenosť zásobníkov v EÚ: {today_value:.2f} %
- Denná zmena oproti včerajšku: {delta_txt} %

Štruktúra: 2–3 vety: (1) čo sa stalo, (2) prečo je to dôležité pre krátkodobé ceny, (3) poznámka k rizikám (max 1 veta).
Bez žiadnych predslovov, bez odrážok, zrozumiteľne.
"""
    resp = client.chat.completions.create(
        model="gpt-5",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()
