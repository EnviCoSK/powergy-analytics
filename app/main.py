from fastapi import FastAPI, Query, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, ORJSONResponse
from sqlalchemy import desc, func, text, inspect
from .gpt import generate_comment
from datetime import date as D, timedelta as TD
from jinja2 import Template
import io, csv

try:
    import openpyxl   # pre Excel export
except Exception:
    openpyxl = None

from .database import SessionLocal, init_db
from .models import GasStorageDaily
from . import models  # <<< PRIDANÉ

app = FastAPI(title="Powergy Analytics – Alfa", default_response_class=ORJSONResponse)
app.add_middleware(GZipMiddleware, minimum_size=512)

@app.on_event("startup")
def startup():
    init_db()

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
(() => {
  // UI prvky
  const rangeEl = document.getElementById('rangeSel') || document.querySelector('select');
  const chartEl = document.getElementById('chart');
  const tableEl = document.getElementById('table');
  const btnCsv  = document.getElementById('btnCsv');
  const btnXls  = document.getElementById('btnXlsx');

  // stav + cache
  const cache = new Map();
  let state = {
    records: [],
    prev: [],
    hoverIdx: null,
    scale: null   // uložíme si X/Y škále pre hover
  };

  function showMsg(text){
    let m = document.getElementById('msg');
    if(!m){
      m = document.createElement('div');
      m.id = 'msg';
      m.className = 'muted';
      chartEl.parentElement.appendChild(m);
    }
    m.textContent = text || '';
  }

  function drawEmpty(msg){
    const g = chartEl.getContext('2d');
    const W = chartEl.width, H = chartEl.height;
    g.clearRect(0,0,W,H);
    showMsg(msg || 'Žiadne záznamy pre zvolený rozsah.');
    tableEl.innerHTML = '<div class="muted">Žiadne záznamy</div>';
  }

  function renderTable(records){
    if(!records?.length){
      tableEl.innerHTML = '<div class="muted">Žiadne záznamy</div>';
      return;
    }
    tableEl.innerHTML = `
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr>
            <th style="text-align:left; padding:8px; border-bottom:1px solid #e5e7eb;">Dátum</th>
            <th style="text-align:left; padding:8px; border-bottom:1px solid #e5e7eb;">Naplnenie (%)</th>
            <th style="text-align:left; padding:8px; border-bottom:1px solid #e5e7eb;">Denná zmena</th>
          </tr>
        </thead>
        <tbody>
          ${records.map(r=>`
            <tr>
              <td style="padding:8px; border-bottom:1px solid #f3f4f6;">${r.date}</td>
              <td style="padding:8px; border-bottom:1px solid #f3f4f6;">${r.percent.toFixed(2)}</td>
              <td style="padding:8px; border-bottom:1px solid #f3f4f6;">${r.delta==null?'—':r.delta.toFixed(2)}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  }

  function drawChart(records, prev, hoverIdx=null){
    // HiDPI canvas
    const cssW = chartEl.clientWidth || 980;
    const cssH = 320;
    const dpi = window.devicePixelRatio || 1;
    chartEl.width = Math.round(cssW * dpi);
    chartEl.height = Math.round(cssH * dpi);
    chartEl.style.width = cssW+'px';
    chartEl.style.height = cssH+'px';

    const g = chartEl.getContext('2d');
    g.setTransform(dpi,0,0,dpi,0,0);

    const W = cssW, H = cssH;
    g.clearRect(0,0,W,H);
    showMsg('');

    const cur = records.map(r=>r.percent);
    const ref = (prev||[]).map(r=>r.percent);

    const max = Math.max(...cur, ...(ref.length?ref:[-Infinity]));
    const min = Math.min(...cur, ...(ref.length?ref:[Infinity]));

    const left=40, right=10, top=10, bottom=30;
    const nx = cur.length;
    const X = (i,n)=> left + i*((W-left-right)/Math.max(1,n-1));
    const Y = v => top + (H-top-bottom) * (1 - ((v-min)/Math.max(1,(max-min))));

    // uložíme škálu pre hover
    state.scale = {left,right,top,bottom,W,H,min,max, nx, X:(i)=>X(i,nx), Y};

    function line(data, dashed, color){
      if(!data.length) return;
      g.save();
      g.lineWidth = 2;
      if(dashed) g.setLineDash([6,6]);
      g.strokeStyle = color;
      g.beginPath();
      data.forEach((v,i)=>{
        const x = X(i,data.length), y = Y(v);
        if(i===0) g.moveTo(x,y); else g.lineTo(x,y);
      });
      g.stroke();
      g.restore();
    }

    // os X
    g.strokeStyle="#e5e7eb";
    g.beginPath(); g.moveTo(left,H-bottom); g.lineTo(W-right,H-bottom); g.stroke();

    // referencia 2024
    if(ref.length) line(ref, true, "#9ec5fe");
    // aktuálny rok
    line(cur, false, "#2563eb");

  // hover bod + label (2025 + 2024)
if(hoverIdx!=null && hoverIdx>=0 && hoverIdx<nx){
  const x = X(hoverIdx,nx);
  const vCur = cur[hoverIdx];
  const hasPrev = Array.isArray(ref) && ref.length === nx;   // zarovnané na rovnaké indexy
  const vPrev = hasPrev ? ref[hoverIdx] : null;

  // vodiaca čiara
  g.save();
  g.strokeStyle = "rgba(0,0,0,.15)";
  g.setLineDash([4,4]);
  g.beginPath(); g.moveTo(x, top); g.lineTo(x, H-bottom); g.stroke();
  g.restore();

  // body
  // 2025
  const yCur = Y(vCur);
  g.fillStyle = "#2563eb";
  g.beginPath(); g.arc(x,yCur,4,0,Math.PI*2); g.fill();

  // 2024 (ak je)
  if(vPrev!=null){
    const yPrev = Y(vPrev);
    g.fillStyle = "#9ec5fe";
    g.beginPath(); g.arc(x,yPrev,4,0,Math.PI*2); g.fill();
  }

  // label (dvojriadkový)
  const date = records[hoverIdx].date;
  const line1 = `2025: ${vCur.toFixed(2)} %`;
  const line2 = (vPrev!=null) ? `2024: ${vPrev.toFixed(2)} %` : '';
  const pad = 6;
  g.font = "12px system-ui, -apple-system, Segoe UI, Roboto, Arial";
  const w1 = g.measureText(`${date}`).width;
  const w2 = g.measureText(line1).width;
  const w3 = g.measureText(line2).width;
  const boxW = Math.ceil(Math.max(w1, w2, w3)) + pad*2;
  const lineH = 16; // výška riadku
  const lines = (vPrev!=null) ? 3 : 2;
  const boxH = lineH*lines + 6;

  const lx = Math.min(Math.max(x - boxW/2, left), W - right - boxW);
  const ly = Math.max(yCur - boxH - 10, top);

  // podklad
  g.fillStyle = "rgba(11,18,33,0.90)";
  g.fillRect(lx, ly, boxW, boxH);

  // texty
  g.fillStyle = "white";
  let ty = ly + 14;
  g.fillText(date, lx+pad, ty); ty += lineH;
  g.fillText(line1, lx+pad, ty); ty += lineH;
  if(vPrev!=null) g.fillText(line2, lx+pad, ty);
}
  }

  async function fetchHistory(days){
    const key = String(days);
    if(cache.has(key)){
      const data = cache.get(key);
      state.records = data.records;
      state.prev    = data.prev_year || [];
      drawChart(state.records, state.prev, state.hoverIdx);
      renderTable(state.records);
      return;
    }
    showMsg('Načítavam…');
    const r = await fetch(`/api/history?days=${encodeURIComponent(days)}`, {cache:'no-store'});
    if(!r.ok){
      drawEmpty(`Nepodarilo sa načítať dáta: HTTP ${r.status}`);
      return;
    }
    const data = await r.json();
    if(!data || !Array.isArray(data.records) || data.records.length===0){
      drawEmpty('Žiadne záznamy pre zvolený rozsah.');
      return;
    }
    cache.set(key, data);
    state.records = data.records;
    state.prev    = data.prev_year || [];
    drawChart(state.records, state.prev, state.hoverIdx);
    renderTable(state.records);
  }

  function currentRange(){
    const v = (rangeEl && rangeEl.value) ? Number(rangeEl.value) : 30;
    return (v && !Number.isNaN(v)) ? v : 30;
  }

  // EXPORT – len presmerujeme na API s aktuálnym rozsahom
  function bindExport(){
    if(btnCsv){
      btnCsv.addEventListener('click', () => {
        const d = currentRange();
        // ak máš iné endpointy (napr. /api/export-csv), zmeň URL tu
        window.location.href = `/api/export?fmt=csv&days=${encodeURIComponent(d)}`;
      });
    }
    if(btnXls){
      btnXls.addEventListener('click', () => {
        const d = currentRange();
        window.location.href = `/api/export?fmt=xlsx&days=${encodeURIComponent(d)}`;
      });
    }
  }

  // HOVER – jednoduchý nearest-point
  function bindHover(){
    const onMove = (ev) => {
      if(!state.scale || !state.records.length) return;
      const rect = chartEl.getBoundingClientRect();
      const px = (ev.clientX - rect.left) * (chartEl.width / chartEl.clientWidth);   // fyz. pixely
      const dpi = window.devicePixelRatio || 1;
      const xCss = px / dpi; // späť do CSS súradníc

      const {left, right, W, nx} = state.scale;
      if(xCss < left || xCss > (W - right)) {
        state.hoverIdx = null;
        drawChart(state.records, state.prev, state.hoverIdx);
        return;
      }
      const usable = (W - left - right);
      const t = (xCss - left) / Math.max(1, usable);     // 0..1
      const idx = Math.round(t * (nx - 1));
      state.hoverIdx = Math.max(0, Math.min(nx-1, idx));
      drawChart(state.records, state.prev, state.hoverIdx);
    };

    chartEl.addEventListener('mousemove', onMove);
    chartEl.addEventListener('mouseleave', () => {
      state.hoverIdx = null;
      if(state.records.length) drawChart(state.records, state.prev, null);
    });
  }

  // init
  if(rangeEl) rangeEl.addEventListener('change', () => fetchHistory(currentRange()));
  window.addEventListener('load', ()=> {
    bindExport();
    bindHover();
    fetchHistory(currentRange());
  });
})();
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
    # zdravé limity
    try:
        days = int(days)
    except Exception:
        days = 30
    if days <= 0 or days > 366:
        days = 30

    sess = SessionLocal()
    try:
        # posledných N dní (ASC, aby graf kreslil zľava doprava)
        q = (
            sess.query(GasStorageDaily)
            .order_by(GasStorageDaily.date.desc())
            .limit(days)
        )
        rows = list(reversed(q.all()))

        # keď nemáme nič, vráť prázdne polia (200 OK – UI to zvládne)
        if not rows:
            resp = JSONResponse({"records": [], "prev_year": []})
            resp.headers["Cache-Control"] = "public, max-age=30"
            return resp

        records = []
        for r in rows:
            records.append({
                "date": str(r.date),
                "percent": round(float(r.percent), 2),
                "delta": None if r.delta is None else round(float(r.delta), 2),
            })

        # okno pre minulý rok – batch query (žiadne per-row dotazy)
        start_prev = rows[0].date - TD(days=365)
        end_prev   = rows[-1].date - TD(days=365)

        prev_rows = (
            sess.query(GasStorageDaily)
            .filter(GasStorageDaily.date >= start_prev,
                    GasStorageDaily.date <= end_prev)
            .all()
        )
        by_date = {p.date: p for p in prev_rows}

        baseline = records[0]["percent"]  # fallback, aby graf nikdy nespadol
        prev_year = []
        for r in rows:
            key = r.date - TD(days=365)
            pr = by_date.get(key)
            if pr:
                prev_year.append({"date": str(pr.date),
                                  "percent": round(float(pr.percent), 2)})
            else:
                # keď AGSI/DB nemá presný „-365 dní“, daj baseline
                prev_year.append({"date": str(key), "percent": baseline})

        resp = JSONResponse({"records": records, "prev_year": prev_year})
        resp.headers["Cache-Control"] = "public, max-age=30"  # krátka cache
        return resp

    except Exception as e:
        # vrátime info, aby UI/logy ukázali konkrétne, čo sa stalo
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
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

@app.get("/api/health")
def api_health():
    return {"ok": True}

@app.get("/api/db-stats", response_class=JSONResponse)
def api_db_stats():
    sess = SessionLocal()
    try:
        total = sess.query(func.count(GasStorageDaily.id)).scalar() or 0
        last = (
            sess.query(GasStorageDaily.date, GasStorageDaily.percent)  # ← len tieto stĺpce
            .order_by(GasStorageDaily.date.desc())
            .first()
        )
        return {
            "ok": True,
            "rows": int(total),
            "last_date": (str(last[0]) if last else None),
            "last_percent": (float(last[1]) if last and last[1] is not None else None),
        }
    except Exception as e:
        return JSONResponse({"ok": False, "error": "exception", "detail": str(e)}, status_code=500)
    finally:
        sess.close()

@app.get("/api/db-tables", response_class=JSONResponse)
def api_db_tables():
    # Pre istotu vypíšeme tabuľky, ktoré SQLAlchemy vidí
    insp = inspect(SessionLocal().get_bind())
    return {"ok": True, "tables": insp.get_table_names(schema="public")}

@app.post("/api/init-db", response_class=JSONResponse)
def api_init_db():
    # nútene spustí create_all (ak by neprebehlo pri startupe)
    try:
        init_db()
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.get("/api/export", response_class=StreamingResponse)
def api_export(fmt: str = "csv", days: int = 30):
    sess = SessionLocal()
    try:
        rows = (
            sess.query(GasStorageDaily)
            .order_by(GasStorageDaily.date.desc())
            .limit(days)
            .all()
        )
        rows = list(reversed(rows))

        if fmt.lower() == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["date", "percent", "delta"])
            for r in rows:
                w.writerow([str(r.date), f"{r.percent:.2f}", "" if r.delta is None else f"{r.delta:.2f}"])
            buf.seek(0)
            return StreamingResponse(
                iter([buf.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": 'attachment; filename="powergy_gas_storage.csv"'}
            )
        elif fmt.lower() in ("xlsx", "xls"):
            if openpyxl is None:
                return JSONResponse({"ok": False, "error": "Excel export nie je povolený (chýba openpyxl)."}, status_code=400)
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "gas_storage"
            ws.append(["date", "percent", "delta"])
            for r in rows:
                ws.append([str(r.date), float(f"{r.percent:.2f}"), None if r.delta is None else float(f"{r.delta:.2f}")])
            xbuf = io.BytesIO()
            wb.save(xbuf)
            xbuf.seek(0)
            return StreamingResponse(
                xbuf,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": 'attachment; filename="powergy_gas_storage.xlsx"'}
            )
        else:
            return JSONResponse({"ok": False, "error": "Unknown format"}, status_code=400)
    finally:
        sess.close()

@app.get("/api/insight", response_class=JSONResponse)
def api_insight(days: int = 30):
    """
    Vráti metriku pre dashboard: latest, 7d trend, yoy gap + komentár (GPT s fallbackom).
    """
    sess = SessionLocal()
    try:
        # posledný záznam
        last = sess.query(GasStorageDaily).order_by(GasStorageDaily.date.desc()).first()
        if not last:
            return JSONResponse({"ok": False, "error": "No data"}, status_code=404)

        # 7-dňový trend (rozdiel percent medzi posledným a hodnotou spred 7 dní)
        seven_ago = sess.query(GasStorageDaily)\
            .filter(GasStorageDaily.date <= last.date - timedelta(days=7))\
            .order_by(GasStorageDaily.date.desc()).first()
        trend7 = (last.percent - seven_ago.percent) if seven_ago else 0.0

        # YoY gap – pokus o dátum -1 rok (s ošetrením 29.2.)
        try:
            prev_date = last.date.replace(year=last.date.year - 1)
        except ValueError:
            prev_date = last.date - timedelta(days=365)
        prev_row = sess.query(GasStorageDaily).filter(GasStorageDaily.date == prev_date).first()
        yoy_gap = last.percent - (prev_row.percent if prev_row else last.percent)

        # komentár (GPT / fallback)
        comment = generate_comment(last.percent, last.delta, trend7, yoy_gap)

        return {
            "ok": True,
            "latest": {
                "date": str(last.date),
                "percent": last.percent,
                "delta": last.delta,
            },
            "trend7": trend7,
            "yoy_gap": yoy_gap,
            "comment": comment,
        }
    finally:
        sess.close()
