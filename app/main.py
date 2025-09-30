from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from datetime import timedelta, datetime
from jinja2 import Template
import csv, io

from .database import SessionLocal, init_db
from .models import GasStorageDaily

app = FastAPI(title="Powergy Analytics – Alfa")

INDEX_HTML = Template("""<!doctype html>
<html lang="sk">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Powergy Správy – Alfa</title>
<style>
 body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 24px; color:#0b1221; }
 .cards { display:grid; grid-template-columns: repeat(auto-fit,minmax(240px,1fr)); gap:16px; margin-bottom:24px; }
 .card { border:1px solid #e5e7eb; border-radius:16px; padding:16px; box-shadow: 0 2px 10px rgba(0,0,0,.04);}
 h1 { font-size: 24px; margin-bottom: 16px; }
 .muted { color:#6b7280; }
 canvas { width: 100%; max-width: 980px; height: 320px; }
 .section { margin-bottom: 28px; }
</style>
</head>
<body>
  <h1>Powergy Správy – Alfa</h1>
  <div class="cards" id="cards"></div>
  <div class="section">
    <h2>30-dňový trend (2025 vs. 2024)</h2>
    <canvas id="chart"></canvas>
  </div>
  <div class="section">
    <h3>Posledné záznamy</h3>
    <div id="table"></div>
  </div>

  <script>
    async function loadData() {
      const todayResp = await fetch("/api/today");
      if (todayResp.status !== 200) {
        document.body.innerHTML = "<p>Zatiaľ nemáme dáta. Spusť cron alebo endpoint /api/run-daily.</p>";
        return;
      }
      const today = await todayResp.json();
      const history = await fetch("/api/history?days=30").then(r=>r.json());

      // Karty
      const cards = document.getElementById("cards");
      const delta = today.delta === null ? "—" : (today.delta > 0 ? ("+"+today.delta.toFixed(2)+" %") : (today.delta.toFixed(2)+" %"));
      cards.innerHTML = `
        <div class="card">
          <div class="muted">Naplnenie zásobníkov (EÚ)</div>
          <div style="font-size:28px; font-weight:700;">${today.percent.toFixed(2)} %</div>
          <div class="muted">Denná zmena: ${delta}</div>
        </div>
        <div class="card" style="grid-column: span 2;">
          <div class="muted">Komentár</div>
          <div>${today.comment}</div>
        </div>
      `;

      // Tabuľka
      const table = document.getElementById("table");
      table.innerHTML = `
        <table style="width:100%; border-collapse:collapse;">
          <thead>
            <tr>
              <th style="text-align:left; padding:8px; border-bottom:1px solid #e5e7eb;">Dátum</th>
              <th style="text-align:left; padding:8px; border-bottom:1px solid #e5e7eb;">Naplnenie (%)</th>
              <th style="text-align:left; padding:8px; border-bottom:1px solid #e5e7eb;">Denná zmena</th>
            </tr>
          </thead>
          <tbody>
            ${history.records.map(r=>`
              <tr>
                <td style="padding:8px; border-bottom:1px solid #f3f4f6;">${r.date}</td>
                <td style="padding:8px; border-bottom:1px solid #f3f4f6;">${r.percent.toFixed(2)}</td>
                <td style="padding:8px; border-bottom:1px solid #f3f4f6;">${r.delta===null?"—":r.delta.toFixed(2)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `;

      // Graf – ošetrenie 1 dňa dát
      const ctx = document.getElementById("chart");
      const cur = history.records.map(r=>r.percent);
      const prev = history.prev_year.map(r=>r.percent);

      const W = ctx.width, H = ctx.height;
      const dpi = window.devicePixelRatio || 1; ctx.width = W*dpi; ctx.height = H*dpi;
      const g = ctx.getContext("2d"); g.scale(dpi,dpi);

      function drawAxes() {
        g.fillStyle="#fff"; g.fillRect(0,0,W,H);
        g.strokeStyle="#e5e7eb"; g.beginPath(); g.moveTo(40,H-30); g.lineTo(W-10,H-30); g.stroke();
      }
      function drawLine(data, color, dashed=false) {
        const all = [...cur, ...prev];
        const vMax = Math.max(...all), vMin = Math.min(...all);
        const left=40, right=10, top=10, bottom=30;
        const X = i => left + i*((W-left-right)/Math.max(1,(data.length-1)));
        const Y = v => top + (H-top-bottom) * (1 - ((v-vMin)/Math.max(1,(vMax-vMin))));
        g.save();
        if (dashed) g.setLineDash([6,6]);
        g.strokeStyle = color; g.lineWidth = 2;
        if (data.length >= 2) {
          g.beginPath();
          data.forEach((v,i)=>{ const x=X(i), y=Y(v); if(i===0) g.moveTo(x,y); else g.lineTo(x,y); });
          g.stroke();
        } else if (data.length === 1) {
          const x = left + (W-left-right)/2;
          const y = Y(data[0]);
          g.fillStyle = color;
          g.beginPath(); g.arc(x, y, 4, 0, Math.PI*2); g.fill();
        }
        g.restore();
      }

      drawAxes();
      if (cur.length >= 2) {
        drawLine(prev, "#9ec5fe", true);
        drawLine(cur,  "#2563eb", false);
      } else if (cur.length === 1) {
        drawLine(cur, "#2563eb", false);
        g.fillStyle="#6b7280";
        g.font="14px system-ui, -apple-system, Segoe UI, Roboto, Arial";
        g.fillText("Potrebujeme aspoň 2 dni dát na zobrazenie trendu. Zajtra pribudne krivka.", 50, 40);
      } else {
        g.fillStyle="#6b7280";
        g.font="14px system-ui, -apple-system, Segoe UI, Roboto, Arial";
        g.fillText("Zatiaľ bez historických dát.", 50, 40);
      }
    }
    loadData();
  </script>
</body>
</html>
""")

@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML.render()

@app.get("/healthz", response_class=JSONResponse)
def healthz():
    return {"status": "ok"}

@app.on_event("startup")
def startup():
    init_db()

@app.get("/api/today", response_class=JSONResponse)
def api_today():
    sess = SessionLocal()
    row = sess.query(GasStorageDaily).order_by(GasStorageDaily.date.desc()).first()
    if not row:
        sess.close()
        return JSONResponse({"message":"No data yet"}, status_code=404)
    out = {"date": str(row.date), "percent": row.percent, "delta": row.delta, "comment": row.comment}
    sess.close()
    return out

@app.get("/api/history", response_class=JSONResponse)
def api_history(days: int = 30):
    sess = SessionLocal()
    rows = sess.query(GasStorageDaily).order_by(GasStorageDaily.date.desc()).limit(days).all()
    rows = list(reversed(rows))
    records = [{"date": str(r.date), "percent": r.percent, "delta": r.delta} for r in rows]

    # minulý rok – posun o 365 dní (proxy) + ošetrenie 29.2.
    prev_rows = []
    for r in rows:
        try:
            prev_date = r.date.replace(year=r.date.year-1)
        except ValueError:
            prev_date = r.date - timedelta(days=365)
        prev = sess.query(GasStorageDaily).filter(GasStorageDaily.date==prev_date).first()
        if prev:
            prev_rows.append({"date": str(prev.date), "percent": prev.percent})
        else:
            prev_rows.append({"date": str(prev_date), "percent": records[0]["percent"] if records else 0})

    sess.close()
    return {"records": records, "prev_year": prev_rows}

# manuálny trigger – prvé naplnenie dát (POST)
@app.post("/api/run-daily", response_class=JSONResponse)
def api_run_daily():
    try:
        from .scraper import run_daily
        run_daily()
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

# pohodlný GET spúšťač scraperu (klik z prehliadača)
@app.get("/api/run-now", response_class=JSONResponse)
def api_run_now_get():
    try:
        from .scraper import run_daily
        run_daily()
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

# Backfill z AGSI – GET napr. /api/backfill-agsi?from=2025-01-01
@app.get("/api/backfill-agsi", response_class=JSONResponse)
def api_backfill_agsi(from_: str = Query("2025-01-01", alias="from")):
    try:
        from .scraper import backfill_agsi
        res = backfill_agsi(from_)
        return {"ok": True, **res}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

# Diagnostika AGSI API – na kontrolu či vracia dáta
@app.get("/api/agsi-probe", response_class=JSONResponse)
def api_agsi_probe(from_: str = Query("2025-01-01", alias="from")):
    import os, requests, datetime
    key = os.getenv("AGSI_API_KEY", "")
    if not key:
        return JSONResponse({"ok": False, "error": "Missing AGSI_API_KEY"}, status_code=400)

    url = "https://agsi.gie.eu/api"
    params = {"country": "EU", "from": from_, "to": datetime.date.today().isoformat(), "type": "aggregated"}
    r = requests.get(url, params=params, headers={"x-key": key}, timeout=60)

    ct = r.headers.get("content-type", "")
    try:
        j = r.json() if "application/json" in ct else {}
    except Exception:
        j = {}

   return {
  "ok": r.ok,
  "status": r.status_code,
  "request_url": r.url,
  "json_keys": list(j.keys()) if isinstance(j, dict) else None,
  "total": (j.get("total") if isinstance(j, dict) else None),
  "last_page": (j.get("last_page") if isinstance(j, dict) else None),
  "count": (len(j.get("data", [])) if isinstance(j, dict) and isinstance(j.get("data", []), list) else None),
  "sample": (j.get("data") or [])[:3] if isinstance(j, dict) else None,
}

# (voliteľné) spätný prepočet dennej zmeny po importe
@app.post("/api/recompute-deltas", response_class=JSONResponse)
def api_recompute_deltas():
    sess = SessionLocal()
    try:
        rows = sess.query(GasStorageDaily).order_by(GasStorageDaily.date.asc()).all()
        prev = None
        for r in rows:
            if prev is None:
                r.delta = None
            else:
                r.delta = round(r.percent - prev.percent, 2)
            prev = r
        sess.commit()
        return {"ok": True, "count": len(rows)}
    except Exception as e:
        sess.rollback()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        sess.close()
