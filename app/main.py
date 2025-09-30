from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse  # ← pridaj sem
from sqlalchemy import desc
from datetime import timedelta
from jinja2 import Template
import io, csv  # ← kľudne sem (modulovo)

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
  :root{--fg:#0b1221;--muted:#6b7280;--border:#e5e7eb;--blue:#2563eb;--blue-200:#9ec5fe;}
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;margin:24px;color:var(--fg)}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;margin-bottom:24px}
  .card{border:1px solid var(--border);border-radius:16px;padding:16px;box-shadow:0 2px 10px rgba(0,0,0,.04)}
  h1{font-size:24px;margin-bottom:16px}
  .muted{color:var(--muted)}
  .section{margin-bottom:28px}
  .row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:6px 0 10px}
  select,button{border:1px solid var(--border);border-radius:10px;padding:8px 10px;background:#fff}
  button{cursor:pointer}
  .chart-wrap{position:relative;max-width:980px}
  canvas{width:100%;height:340px;border:1px solid var(--border);border-radius:12px;background:#fff}
  .legend{display:flex;gap:16px;align-items:center;margin:8px 0 6px 2px}
  .chip{display:inline-flex;align-items:center;gap:8px;color:var(--muted);font-size:14px}
  .chip .sw{width:20px;height:4px;border-radius:2px;display:inline-block}
  .sw.blue{background:var(--blue)}
  .sw.blue-dash{background:linear-gradient(90deg,var(--blue-200) 0 40%,transparent 0 60%)}
  .tt{position:absolute;pointer-events:none;z-index:5;background:#111827;color:#fff;font-size:12px;border-radius:8px;padding:8px 10px;box-shadow:0 6px 18px rgba(0,0,0,.12);opacity:0;transition:opacity .08s}
  .tt b{font-weight:700}
</style>
</head>
<body>
  <h1>Powergy Správy – Alfa</h1>

  <div class="cards" id="cards"></div>

  <div class="section">
    <div class="row">
      <h2 style="margin:0;">Trend (2025 vs. 2024)</h2>
      <label class="muted">Rozsah:</label>
      <select id="rangeSel">
        <option value="30">30 dní</option>
        <option value="90">90 dní</option>
        <option value="180">180 dní</option>
        <option value="365">365 dní</option>
      </select>
      <span style="flex:1"></span>
      <button id="btnCsv">Export CSV</button>
      <button id="btnXlsx">Export Excel</button>
    </div>
    <div class="legend">
      <span class="chip"><span class="sw blue"></span>2025 (EÚ – naplnenie %)</span>
      <span class="chip"><span class="sw blue-dash"></span>2024 (referencia)</span>
    </div>
    <div class="chart-wrap">
      <canvas id="chart"></canvas>
      <div id="tooltip" class="tt"></div>
    </div>
  </div>

  <div class="section">
    <h3>Posledné záznamy</h3>
    <div id="table"></div>
  </div>

<script>
async function fetchJson(url){
  const r = await fetch(url);
  let body = null;
  try { body = await r.json(); } catch(_){}
  if(!r.ok){
    throw new Error(`${r.status} ${r.statusText} – ${url}\n${JSON.stringify(body)}`);
  }
  return body;
}

function showMessage(html){
  const wrap = document.querySelector(".chart-wrap");
  const msgId = "inline-msg";
  let el = document.getElementById(msgId);
  if(!el){
    el = document.createElement("div");
    el.id = msgId;
    el.style.margin = "8px 0";
    el.className = "muted";
    wrap.parentElement.insertBefore(el, wrap.nextSibling);
  }
  el.innerHTML = html;
}

function clearMessage(){
  const el = document.getElementById("inline-msg");
  if(el) el.remove();
}

async function render(days){
  try{
    clearMessage();

    // 1) dnes
    const todayResp = await fetch("/api/today");
    if (todayResp.status !== 200){
      showMessage("Zatiaľ nemáme dáta. Spusť cron alebo endpoint <code>/api/run-daily</code>.");
      return;
    }
    const today = await todayResp.json();

    // 2) história
    const hist = await fetchJson(`/api/history?days=${days}`);

    // 3) karty
    const cards = document.getElementById("cards");
    const delta = today.delta===null ? "—" : (today.delta>0?("+"+today.delta.toFixed(2)+" %"):(today.delta.toFixed(2)+" %"));
    cards.innerHTML = `
      <div class="card">
        <div class="muted">Naplnenie zásobníkov (EÚ)</div>
        <div style="font-size:28px;font-weight:700;">${today.percent.toFixed(2)} %</div>
        <div class="muted">Denná zmena: ${delta}</div>
      </div>
      <div class="card" style="grid-column: span 2;">
        <div class="muted">Komentár</div>
        <div>${today.comment}</div>
      </div>
    `;

    // 4) ak nemáme záznamy pre zvolený rozsah
    if(!hist || !Array.isArray(hist.records) || hist.records.length === 0){
      const ctx = document.getElementById("chart");
      const g = ctx.getContext("2d");
      g.clearRect(0,0,ctx.width,ctx.height);
      document.getElementById("table").innerHTML =
        '<div class="muted">Žiadne záznamy pre zvolený rozsah.</div>';
      return;
    }

    // 5) tabuľka
    const table = document.getElementById("table");
    table.innerHTML = `
      <table style="width:100%;border-collapse:collapse;">
        <thead>
          <tr>
            <th style="text-align:left;padding:8px;border-bottom:1px solid var(--border);">Dátum</th>
            <th style="text-align:left;padding:8px;border-bottom:1px solid var(--border);">Naplnenie (%)</th>
            <th style="text-align:left;padding:8px;border-bottom:1px solid var(--border);">Denná zmena</th>
          </tr>
        </thead>
        <tbody>
          ${hist.records.map(r=>`
            <tr>
              <td style="padding:8px;border-bottom:1px solid #f3f4f6;">${r.date}</td>
              <td style="padding:8px;border-bottom:1px solid #f3f4f6;">${r.percent.toFixed(2)}</td>
              <td style="padding:8px;border-bottom:1px solid #f3f4f6;">${r.delta===null?"—":r.delta.toFixed(2)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;

    // 6) graf
    const ctx = document.getElementById("chart");
    const cur    = hist.records.map(r=>r.percent);
    const prev   = (hist.prev_year||[]).map(r=>r.percent);
    const labels = hist.records.map(r=>r.date);

    const W = ctx.clientWidth, H = ctx.clientHeight;
    const dpi = window.devicePixelRatio || 1; ctx.width = W*dpi; ctx.height = H*dpi;
    const g = ctx.getContext("2d"); g.scale(dpi,dpi);

    const left=40, right=12, top=16, bottom=30;
    const innerW = W-left-right, innerH = H-top-bottom;

    const nums = [...cur, ...prev].filter(v=>typeof v==="number");
    const vMax = Math.max(...nums), vMin = Math.min(...nums);
    const X = i => left + (innerW * (cur.length<=1?0.5 : i/(cur.length-1)));
    const Y = v => top + innerH*(1 - ((v - vMin)/Math.max(1e-9,(vMax - vMin))));

    function axes(){
      g.fillStyle="#fff"; g.fillRect(0,0,W,H);
      g.strokeStyle="var(--border)"; g.beginPath(); g.moveTo(left,H-bottom); g.lineTo(W-right,H-bottom); g.stroke();
    }
    function line(data, color, dashed=false){
      if(!data.length) return;
      g.save(); if(dashed) g.setLineDash([6,6]); g.strokeStyle=color; g.lineWidth=2;
      if(data.length>=2){
        g.beginPath();
        data.forEach((v,i)=>{ const x=X(i), y=Y(v); if(i===0) g.moveTo(x,y); else g.lineTo(x,y); });
        g.stroke();
        g.fillStyle=color;
        data.forEach((v,i)=>{ const x=X(i), y=Y(v); g.beginPath(); g.arc(x,y,2.2,0,Math.PI*2); g.fill(); });
      }else{
        const x=left+innerW/2, y=Y(data[0]);
        g.fillStyle=color; g.beginPath(); g.arc(x,y,4,0,Math.PI*2); g.fill();
      }
      g.restore();
    }

    axes();
    if(prev.length) line(prev,"#9ec5fe",true);
    if(cur.length)  line(cur,"#2563eb",false);

    // 7) tooltip
    const tt = document.getElementById("tooltip");
    function showTT(ix, xPix){
      const d = labels[ix];
      const vCur = cur[ix];
      const vPrev = prev[ix] ?? null;
      tt.innerHTML = `
        <div><b>${d}</b></div>
        <div>2025: <b>${(vCur??NaN).toFixed ? vCur.toFixed(2) : "—"}%</b></div>
        <div>2024: <b>${(vPrev??NaN).toFixed ? vPrev.toFixed(2) : "—"}%</b></div>
      `;
      tt.style.opacity = 1;
      const ttW = tt.offsetWidth; const tx = Math.min(Math.max(8, xPix - ttW/2), W - ttW - 8);
      const ty = top + 8; tt.style.transform = `translate(${tx}px, ${ty}px)`;
    }
    function hideTT(){ tt.style.opacity = 0; }

    if(cur.length){
      ctx.onmousemove = (e)=>{
        const rect = ctx.getBoundingClientRect();
        const x = (e.clientX - rect.left);
        let bestI = 0, bestD = 1e9;
        for (let i=0;i<cur.length;i++){
          const dx = Math.abs(X(i) - x);
          if (dx < bestD){ bestD = dx; bestI = i; }
        }
        axes(); if(prev.length) line(prev,"#9ec5fe",true); if(cur.length) line(cur,"#2563eb",false);
        g.save(); g.strokeStyle="rgba(0,0,0,.15)"; g.setLineDash([4,4]); g.beginPath();
        g.moveTo(X(bestI), top); g.lineTo(X(bestI), H-bottom); g.stroke(); g.restore();
        showTT(bestI, X(bestI));
      };
      ctx.onmouseleave = ()=>{ axes(); if(prev.length) line(prev,"#9ec5fe",true); if(cur.length) line(cur,"#2563eb",false); hideTT(); };
    }

  } catch(err){
    console.error(err);
    showMessage("Nepodarilo sa načítať dáta: <code>"+String(err).replace(/[<>]/g,'')+"</code>");
    const ctx = document.getElementById("chart");
    const g = ctx.getContext("2d");
    g.clearRect(0,0,ctx.width,ctx.height);
    document.getElementById("table").innerHTML = "";
  }
}

// ovládanie rozsahu + export
const sel   = document.getElementById("rangeSel");
const btnCsv  = document.getElementById("btnCsv");
const btnXlsx = document.getElementById("btnXlsx");

function currentDays(){ return parseInt(sel.value,10); }
sel.addEventListener("change", ()=>render(currentDays()));
btnCsv.addEventListener("click", ()=>{ window.location = `/api/export.csv?days=${currentDays()}`; });
btnXlsx.addEventListener("click", ()=>{ window.location = `/api/export.xlsx?days=${currentDays()}`; });

// prvé načítanie
render(currentDays());
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

from fastapi.responses import StreamingResponse
import io, csv

def _history_rows(days: int):
    """Vracia zoznam (date, percent, delta, comment) za posledné dni (vzostupne)."""
    sess = SessionLocal()
    try:
        rows = (
            sess.query(GasStorageDaily)
            .order_by(GasStorageDaily.date.desc())
            .limit(days)
            .all()
        )
        rows = list(reversed(rows))
        out = []
        for r in rows:
            out.append([
                str(r.date),
                float(r.percent),
                (None if r.delta is None else float(r.delta)),
                r.comment or ""
            ])
        return out
    finally:
        sess.close()


@app.get("/api/export.csv")
def api_export_csv(days: int = 30):
    buff = io.StringIO()
    writer = csv.writer(buff)
    writer.writerow(["date", "percent", "delta", "comment"])
    for row in _history_rows(days):
        writer.writerow(row)
    buff.seek(0)
    return StreamingResponse(
        buff,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="powergy_{days}d.csv"'}
    )


@app.get("/api/export.xlsx")
def api_export_xlsx(days: int = 30):
    # import lokálne (ak nechceš globálny import openpyxl)
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["date", "percent", "delta", "comment"])
    for row in _history_rows(days):
        ws.append(row)

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return StreamingResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="powergy_{days}d.xlsx"'}
    )
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

# Diagnostika AGSI API – kontrola, čo sa vracia
@app.get("/api/agsi-probe", response_class=JSONResponse)
def api_agsi_probe(from_: str = Query("2025-01-01", alias="from")):
    import os
    import requests
    import datetime as dt

    key = os.getenv("AGSI_API_KEY", "")
    if not key:
        return JSONResponse({"ok": False, "error": "Missing AGSI_API_KEY"}, status_code=400)

    url = "https://agsi.gie.eu/api"
 
    params = {
    "type": "eu",
    "from": from_,
    "to": dt.date.today().isoformat(),
    "size": 5000,
    "gas_day": "asc",
    "page": 1,
}
    r = requests.get(url, params=params, headers={"x-key": key}, timeout=60)

    try:
        j = r.json()
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
