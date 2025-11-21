# app/main.py
from __future__ import annotations

import os
import io
import csv
import datetime as dt
from datetime import timedelta as TD
from typing import Optional
from functools import lru_cache
from time import time

import requests
from fastapi import FastAPI, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from jinja2 import Template
from sqlalchemy import func, text, inspect
from sqlalchemy.exc import SQLAlchemyError

# Optional Excel support
try:
    import openpyxl  # type: ignore
except Exception:
    openpyxl = None

from .database import SessionLocal, init_db
from .models import GasStorageDaily

# -----------------------------------------------------------------------------
# JSON with explicit UTF-8 to avoid mojibake
# -----------------------------------------------------------------------------
class JSONUTF8Response(JSONResponse):
    media_type = "application/json; charset=utf-8"


app = FastAPI(title="Powergy Analytics – Alfa", default_response_class=JSONUTF8Response)
app.add_middleware(GZipMiddleware, minimum_size=512)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def fix_mojibake(s: str) -> str:
    """Repair UTF-8 text that was decoded as Latin-1 (e.g., 'ZĂĄsobnĂ­ky')."""
    if not s:
        return s
    if any(ch in s for ch in "ĂÄÅÃÂŠŽŤĎĽĹ"):
        try:
            repaired = s.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
            if repaired and repaired != s:
                return repaired
        except Exception:
            pass
    return s


def _to_float(x):
    """Safely convert common numeric inputs to float."""
    if x is None:
        return None
    try:
        from decimal import Decimal
        if isinstance(x, (int, float)):
            return float(x)
        if isinstance(x, Decimal):
            return float(x)
        if isinstance(x, str):
            s = x.strip().replace("%", "").replace(",", ".")
            return float(s)
        return float(x)
    except Exception:
        return None


def _format_date(date_obj) -> str:
    """Formátuje dátum do formátu DD.MM.YYYY."""
    if isinstance(date_obj, str):
        try:
            date_obj = dt.date.fromisoformat(date_obj)
        except Exception:
            return date_obj
    if isinstance(date_obj, dt.date):
        return f"{date_obj.day:02d}.{date_obj.month:02d}.{date_obj.year}"
    return str(date_obj)


def _fallback_comment(percent: float, delta: Optional[float], yoy_gap: Optional[float]) -> str:
    d_text = "bez dennej zmeny" if (delta is None or abs(delta) < 0.005) else (
        f"denná zmena +{delta:.2f} p.b." if delta > 0 else f"denná zmena {delta:.2f} p.b."
    )
    yoy_text = "" if yoy_gap is None else f" vs. minulý rok {('+' if yoy_gap>0 else '')}{yoy_gap:.2f} p.b."
    return (
        f"Zásobníky plynu v EÚ sú aktuálne naplnené na {percent:.2f} %. "
        f"{d_text}{yoy_text}. Úroveň zásob pôsobí stabilizačne na prompt; krátkodobo rozhodnú počasie, "
        f"prítoky LNG a prípadné neplánované odstávky."
    )


# External generator (if present)
try:
    from .gpt import generate_comment as _generate_comment_inner  # type: ignore
except Exception:
    _generate_comment_inner = None  # type: ignore


def generate_comment_safe(percent: float, delta: Optional[float], yoy_gap: Optional[float], trend7: Optional[float] = None) -> str:
    """Generate short comment; uses fallback if GPT not configured/failed."""
    if _generate_comment_inner is None:
        return _fallback_comment(percent, delta, yoy_gap or 0.0)
    try:
        # trend7 default je 0.0 ak nie je poskytnutý
        trend7_val = trend7 if trend7 is not None else 0.0
        yoy_gap_val = yoy_gap if yoy_gap is not None else 0.0
        txt = _generate_comment_inner(percent, delta, trend7_val, yoy_gap_val)
        if not txt or not str(txt).strip():
            return _fallback_comment(percent, delta, yoy_gap_val)
        return str(txt).strip()
    except Exception:
        return _fallback_comment(percent, delta, yoy_gap or 0.0)


# -----------------------------------------------------------------------------
# HTML (kept minimal; focuses on API correctness in this patch)
# -----------------------------------------------------------------------------
INDEX_HTML = Template("""<!doctype html>
<html lang="sk">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Powergy Správy – Alfa</title>
<style>
 body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 24px; color:#0b1221; }
 .row { display:flex; gap:12px; align-items:center; justify-content:space-between; margin-bottom:10px; }
 .cards { display:grid; grid-template-columns: repeat(auto-fit,minmax(240px,1fr)); gap:16px; margin-bottom:24px; }
 .card { border:1px solid #e5e7eb; border-radius:16px; padding:16px; box-shadow: 0 2px 10px rgba(0,0,0,.04); }
 h1 { font-size: 22px; margin: 0 0 8px; }
 h3 { margin: 24px 0 12px 0; }
 .muted { color:#6b7280; }
 canvas { width: 100%; max-width: 980px; height: 320px; }
 button, select { padding:8px 10px; border-radius:10px; border:1px solid #e5e7eb; background:#fff; cursor:pointer; }
 button:hover { background:#f9fafb; }
 .toolbar { display:flex; gap:8px; align-items:center; }
 .section { margin-bottom:32px; }
 .positive { color:#10b981; }
 .negative { color:#ef4444; }
 .neutral { color:#6b7280; }
 .loading { opacity:0.5; pointer-events:none; }
 .skeleton { background:linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%); background-size:200% 100%; animation:loading 1.5s infinite; }
 @keyframes loading { 0% { background-position:200% 0; } 100% { background-position:-200% 0; } }
 .stats { display:grid; grid-template-columns: repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:24px; }
 .stat-card { border:1px solid #e5e7eb; border-radius:12px; padding:12px; background:#f9fafb; }
 .stat-label { font-size:12px; color:#6b7280; margin-bottom:4px; }
 .stat-value { font-size:18px; font-weight:600; }
 .alert { padding:12px; border-radius:8px; margin-bottom:16px; }
 .alert-warning { background:#fef3c7; border:1px solid #fbbf24; color:#92400e; }
 .alert-info { background:#dbeafe; border:1px solid #60a5fa; color:#1e40af; }
 .legend { display:flex; gap:16px; margin-bottom:12px; font-size:12px; }
 .legend-item { display:flex; align-items:center; gap:6px; }
 .legend-line { width:20px; height:2px; }
 .legend-dash { width:20px; height:2px; background-image: repeating-linear-gradient(to right, currentColor 0, currentColor 4px, transparent 4px, transparent 8px); }
 table { width:100%; border-collapse:collapse; }
 th { text-align:left; padding:8px; border-bottom:1px solid #e5e7eb; cursor:pointer; user-select:none; }
 th:hover { background:#f9fafb; }
 th.sort-asc::after { content:" ▲"; font-size:10px; }
 th.sort-desc::after { content:" ▼"; font-size:10px; }
 td { padding:8px; border-bottom:1px solid #f3f4f6; }
 tr:hover { background:#f9fafb; }
 .current-date { background:#eff6ff !important; font-weight:500; }
</style>
</head>
<body>
  <div class="row">
    <h1>Powergy Správy – Alfa</h1>
    <div class="toolbar">
      <select id="rangeSel">
        <option value="30" selected>30 dní</option>
        <option value="90">90 dní</option>
        <option value="180">180 dní</option>
        <option value="365">365 dní</option>
      </select>
      <button id="btnCsv">Export CSV</button>
      <button id="btnXlsx">Export Excel</button>
      <button id="btnChartPng">Export grafu PNG</button>
    </div>
  </div>

  <div id="alerts"></div>
  <div class="cards" id="cards"></div>
  <div class="stats" id="stats"></div>

  <div class="section">
    <h3>Trend zásob (porovnanie s minulým rokom)</h3>
    <div class="legend" id="legend"></div>
    <canvas id="chart"></canvas>
    <div id="msg" class="muted"></div>
  </div>

  <div class="section">
    <h3>Posledné záznamy</h3>
    <div id="table"></div>
  </div>

<script>
(() => {
  const rangeEl = document.getElementById('rangeSel');
  const chartEl = document.getElementById('chart');
  const tableEl = document.getElementById('table');
  const cardsEl = document.getElementById('cards');
  const statsEl = document.getElementById('stats');
  const alertsEl = document.getElementById('alerts');
  const legendEl = document.getElementById('legend');
  const btnCsv = document.getElementById('btnCsv');
  const btnXls = document.getElementById('btnXlsx');
  const btnChartPng = document.getElementById('btnChartPng');
  
  if(!rangeEl || !chartEl || !tableEl || !cardsEl || !statsEl || !alertsEl || !legendEl) {
    console.error('Missing required DOM elements');
    return;
  }

  const cache = new Map();
  let state = { records: [], prev: [], hoverIdx: null, scale: null, sortCol: null, sortDir: 'desc', stats: {}, yearsData: {} };

  function showMsg(text){ document.getElementById('msg').textContent = text || ''; }
  function showLoading(show) {
    document.body.classList.toggle('loading', show);
  }

  function getDeltaColor(delta) {
    if (delta === null || delta === undefined) return 'neutral';
    return delta > 0 ? 'positive' : delta < 0 ? 'negative' : 'neutral';
  }

  function renderAlerts(today) {
    const alerts = [];
    if (today.percent < 50) {
      alerts.push({type: 'warning', msg: '⚠️ Kritická úroveň: Zásoby pod 50%'});
    } else if (today.percent > 90) {
      alerts.push({type: 'info', msg: '✅ Vysoká úroveň: Zásoby nad 90%'});
    }
    if (today.delta !== null && Math.abs(today.delta) > 1.0) {
      alerts.push({type: 'warning', msg: `⚠️ Významná denná zmena: ${today.delta > 0 ? '+' : ''}${today.delta.toFixed(2)} p.b.`});
    }
    alertsEl.innerHTML = alerts.map(a => `<div class="alert alert-${a.type}">${a.msg}</div>`).join('');
  }

  function renderCards(today){
    const delta = (today.delta == null) ? "—" : (today.delta > 0 ? `+${today.delta.toFixed(2)} p.b.` : `${today.delta.toFixed(2)} p.b.`);
    const deltaClass = getDeltaColor(today.delta);
    cardsEl.innerHTML = `
      <div class="card">
        <div class="muted">Naplnenie zásobníkov (EÚ)</div>
        <div style="font-size:28px; font-weight:700;">${today.percent.toFixed(2)} %</div>
        <div class="muted">Dátum: ${today.date}</div>
        <div class="${deltaClass}">Denná zmena: ${delta}</div>
      </div>
      <div class="card" style="grid-column: span 2;">
        <div class="muted">Komentár</div>
        <div id="commentBox">${today.comment || '—'}</div>
      </div>
    `;
    renderAlerts(today);
  }

  function renderStats(stats) {
    if (!stats || !stats.min) {
      statsEl.innerHTML = '';
      return;
    }
    const trendClass = stats.trend === 'rast' ? 'positive' : stats.trend === 'pokles' ? 'negative' : 'neutral';
    statsEl.innerHTML = `
      <div class="stat-card">
        <div class="stat-label">Minimum</div>
        <div class="stat-value">${stats.min} %</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Maximum</div>
        <div class="stat-value">${stats.max} %</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Priemer</div>
        <div class="stat-value">${stats.avg} %</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Priem. denná zmena</div>
        <div class="stat-value ${getDeltaColor(stats.avg_delta)}">${stats.avg_delta !== null ? (stats.avg_delta > 0 ? '+' : '') + stats.avg_delta.toFixed(2) : '—'} p.b.</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Celková zmena</div>
        <div class="stat-value ${trendClass}">${stats.total_change !== null ? (stats.total_change > 0 ? '+' : '') + stats.total_change.toFixed(2) : '—'} p.b.</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Trend</div>
        <div class="stat-value ${trendClass}">${stats.trend || '—'}</div>
      </div>
    `;
  }

  function renderTable(records){
    if(!records?.length){
      tableEl.innerHTML = '<div class="muted">Žiadne záznamy</div>';
      return;
    }
    // Zobrazíme záznamy v opačnom poradí (od najnovšieho po najstarší) pre tabuľku
    let reversedRecords = [...records].reverse();
    
    // Triedenie
    if (state.sortCol) {
      reversedRecords.sort((a, b) => {
        let valA, valB;
        if (state.sortCol === 'date') {
          valA = a.date.split('.').reverse().join('');
          valB = b.date.split('.').reverse().join('');
        } else if (state.sortCol === 'percent') {
          valA = a.percent;
          valB = b.percent;
        } else if (state.sortCol === 'delta') {
          valA = a.delta === null ? -999 : a.delta;
          valB = b.delta === null ? -999 : b.delta;
        }
        const cmp = valA > valB ? 1 : valA < valB ? -1 : 0;
        return state.sortDir === 'asc' ? cmp : -cmp;
      });
    }
    
    const todayDate = reversedRecords[0]?.date;
    const sortClass = (col) => state.sortCol === col ? `sort-${state.sortDir}` : '';
    
    tableEl.innerHTML = `
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr>
            <th class="${sortClass('date')}" data-col="date" style="text-align:left; padding:8px; border-bottom:1px solid #e5e7eb;">Dátum</th>
            <th class="${sortClass('percent')}" data-col="percent" style="text-align:left; padding:8px; border-bottom:1px solid #e5e7eb;">Naplnenie (%)</th>
            <th class="${sortClass('delta')}" data-col="delta" style="text-align:left; padding:8px; border-bottom:1px solid #e5e7eb;">Denná zmena</th>
          </tr>
        </thead>
        <tbody>
          ${reversedRecords.map((r, idx) => {
            const isToday = idx === 0 && r.date === todayDate;
            const deltaClass = getDeltaColor(r.delta);
            return `
            <tr ${isToday ? 'class="current-date"' : ''}>
              <td style="padding:8px; border-bottom:1px solid #f3f4f6;">${r.date}</td>
              <td style="padding:8px; border-bottom:1px solid #f3f4f6;">${r.percent.toFixed(2)}</td>
              <td class="${deltaClass}" style="padding:8px; border-bottom:1px solid #f3f4f6;">${r.delta==null?'—':r.delta.toFixed(2)}</td>
            </tr>
          `;
          }).join('')}
        </tbody>
      </table>
    `;
    
    // Bind sort handlers
    tableEl.querySelectorAll('th[data-col]').forEach(th => {
      th.addEventListener('click', () => {
        const col = th.dataset.col;
        if (state.sortCol === col) {
          state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
        } else {
          state.sortCol = col;
          state.sortDir = 'desc';
        }
        renderTable(records);
      });
    });
  }

  function drawChart(records, prev, hoverIdx=null, yearsData={}){
    try {
    if(!records || !records.length) {
      showMsg('Žiadne dáta pre graf');
      return;
    }
    
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
    
    // Pripravíme dáta pre ďalšie roky
    const currentYear = new Date().getFullYear();
    const yearColors = [
      {key: `year_${currentYear-2}`, color: '#10b981', name: String(currentYear-2)},
      {key: `year_${currentYear-3}`, color: '#f59e0b', name: String(currentYear-3)},
      {key: `year_${currentYear-4}`, color: '#ef4444', name: String(currentYear-4)}
    ];
    const yearsPercent = {};
    Object.keys(yearsData || {}).forEach(key => {
      yearsPercent[key] = (yearsData[key] || []).map(r => r.percent);
    });

    // Vypočítame min/max pre všetky roky
    const allValues = [...cur, ...(ref.length?ref:[]), ...Object.values(yearsPercent).flat()];
    const max = Math.max(...allValues, -Infinity);
    const min = Math.min(...allValues, Infinity);
    const range = max - min;
    const padding = range * 0.1; // 10% padding
    const chartMax = max + padding;
    const chartMin = Math.max(0, min - padding);

    const left=50, right=20, top=30, bottom=50;
    const nx = cur.length;
    const X = (i,n)=> left + i*((W-left-right)/Math.max(1,n-1));
    const Y = v => top + (H-top-bottom) * (1 - ((v-chartMin)/Math.max(1,(chartMax-chartMin))));
    
    // Počiatočný scale (bude aktualizovaný po výpočte predpovede)
    let totalDays = nx;

    // Grid lines a Y-os
    g.strokeStyle = "#e5e7eb";
    g.lineWidth = 1;
    g.font = "11px system-ui, -apple-system, Segoe UI, Roboto, Arial";
    g.fillStyle = "#6b7280";
    g.textAlign = "right";
    g.textBaseline = "middle";
    
    const yTicks = 5;
    for (let i = 0; i <= yTicks; i++) {
      const val = chartMin + (chartMax - chartMin) * (i / yTicks);
      const y = Y(val);
      g.beginPath();
      g.moveTo(left, y);
      g.lineTo(W - right, y);
      g.stroke();
      g.fillText(val.toFixed(1) + '%', left - 8, y);
    }

    // X-os s dátumami - zobrazíme len pred výpočtom predpovede (budeme aktualizovať neskôr)
    // Túto časť presunieme po výpočte predpovede

    // Y-os čiara
    g.beginPath();
    g.moveTo(left, top);
    g.lineTo(left, H-bottom);
    g.stroke();

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

    // Predpoveď trendu (lineárna regresia na posledných 7 dňoch) až do konca mesiaca
    let forecastDates = [];
    let forecastValues = [];
    let totalDays = nx; // Počet dní v grafe vrátane predpovede
    
    try {
      if (cur.length >= 7 && records.length > 0) {
        const last7 = cur.slice(-7);
        const n = last7.length;
        const sumX = (n * (n - 1)) / 2;
        const sumY = last7.reduce((a, b) => a + b, 0);
        const sumXY = last7.reduce((sum, y, i) => sum + i * y, 0);
        const sumX2 = (n * (n - 1) * (2 * n - 1)) / 6;
        const slope = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX);
        const intercept = (sumY - slope * sumX) / n;
        
        // Zistíme posledný dátum a koniec mesiaca
        const lastDateStr = records[records.length - 1].date; // Formát: "DD.MM.YYYY"
        if (lastDateStr && lastDateStr.split('.').length === 3) {
          const [lastDay, lastMonth, lastYear] = lastDateStr.split('.').map(Number);
          if (!isNaN(lastDay) && !isNaN(lastMonth) && !isNaN(lastYear)) {
            const lastDate = new Date(lastYear, lastMonth - 1, lastDay);
            
            // Koniec aktuálneho mesiaca - používame deň 0 nasledujúceho mesiaca
            const endOfMonthDate = new Date(lastYear, lastMonth, 0);
            
            // Počet dní od posledného dátumu do konca mesiaca
            const daysToEndOfMonth = Math.floor((endOfMonthDate - lastDate) / (1000 * 60 * 60 * 24));
            
            if (daysToEndOfMonth > 0 && daysToEndOfMonth <= 31) {
              // Vytvoríme dátumy a hodnoty predpovede
              forecastDates = [];
              forecastValues = [];
              
              for (let i = 1; i <= daysToEndOfMonth; i++) {
                const forecastDate = new Date(lastDate);
                forecastDate.setDate(forecastDate.getDate() + i);
                
                // Formát dátum ako "DD.MM.YYYY"
                const day = String(forecastDate.getDate()).padStart(2, '0');
                const month = String(forecastDate.getMonth() + 1).padStart(2, '0');
                const year = forecastDate.getFullYear();
                forecastDates.push(`${day}.${month}.${year}`);
                
                // Vypočítame predpovedanú hodnotu
                const futureVal = intercept + slope * (n + i - 1);
                forecastValues.push(futureVal);
              }
              
              totalDays = nx + forecastValues.length;
              
              // Vykreslíme predpoveď
              if (forecastValues.length > 0) {
                g.save();
                g.strokeStyle = "#8b5cf6";
                g.lineWidth = 2;
                g.setLineDash([4, 4]);
                g.beginPath();
                const lastX = X(nx - 1, totalDays);
                const lastY = Y(cur[cur.length - 1]);
                g.moveTo(lastX, lastY);
                
                forecastValues.forEach((val, i) => {
                  const x = X(nx + i, totalDays);
                  const y = Y(val);
                  g.lineTo(x, y);
                });
                g.stroke();
                g.restore();
              }
            }
          }
        }
      }
    } catch(e) {
      console.error('Error calculating forecast:', e);
      // Pokračujeme bez predpovede
      forecastDates = [];
      forecastValues = [];
      totalDays = nx;
    }
    
    // Aktualizujeme scale s novým počtom dní
    state.scale = {left,right,top,bottom,W,H,min:chartMin,max:chartMax, nx:totalDays, X:(i)=>X(i,totalDays), Y};
    
    // X-os s dátumami - zobrazíme pre všetky dáta vrátane predpovede
    g.textAlign = "center";
    g.textBaseline = "top";
    g.fillStyle = "#6b7280";
    const allDates = [...records.map(r => r.date), ...forecastDates];
    const dateStep = Math.max(1, Math.floor(totalDays / 6));
    for (let i = 0; i < totalDays; i += dateStep) {
      const x = X(i, totalDays);
      const date = allDates[i] || '';
      if (date) {
        g.fillText(date, x, H - bottom + 8);
        g.beginPath();
        g.moveTo(x, H - bottom);
        g.lineTo(x, H - bottom + 4);
        g.stroke();
      }
    }
    
    // Hlavná X-os čiara - rozšírime ju na celú šírku
    g.strokeStyle="#e5e7eb";
    g.lineWidth = 2;
    g.beginPath(); 
    g.moveTo(left, H-bottom); 
    g.lineTo(W-right, H-bottom); 
    g.stroke();

    // Zobrazíme všetky roky
    yearColors.forEach(({key, color}) => {
      if (yearsPercent[key] && yearsPercent[key].length > 0) {
        line(yearsPercent[key], true, color);
      }
    });
    if(ref.length) line(ref, true, "#9ec5fe");
    line(cur, false, "#2563eb");

    if(hoverIdx!=null && hoverIdx>=0 && hoverIdx<totalDays){
      const x = X(hoverIdx,totalDays);
      // Pre predpoveď použijeme iné hodnoty
      let vCur, vPrev, date, isForecast;
      if (hoverIdx < nx) {
        // Skutočné dáta
        vCur = cur[hoverIdx];
        const hasPrev = Array.isArray(ref) && ref.length === nx;
        vPrev = hasPrev ? ref[hoverIdx] : null;
        date = records[hoverIdx].date;
        isForecast = false;
      } else {
        // Predpoveď
        const forecastIdx = hoverIdx - nx;
        if (forecastValues && forecastValues.length > forecastIdx && forecastDates && forecastDates.length > forecastIdx) {
          vCur = forecastValues[forecastIdx];
          vPrev = null;
          date = forecastDates[forecastIdx];
          isForecast = true;
        } else {
          return; // Neplatný index predpovede
        }
      }

      g.save();
      g.strokeStyle = "rgba(0,0,0,.15)";
      g.setLineDash([4,4]);
      g.beginPath(); g.moveTo(x, top); g.lineTo(x, H-bottom); g.stroke();
      g.restore();

      const yCur = Y(vCur);
      if (isForecast) {
        g.fillStyle = "#8b5cf6";
      } else {
        g.fillStyle = "#2563eb";
      }
      g.beginPath(); g.arc(x,yCur,4,0,Math.PI*2); g.fill();

      if(vPrev!=null && !isForecast){
        const yPrev = Y(vPrev);
        g.fillStyle = "#9ec5fe";
        g.beginPath(); g.arc(x,yPrev,4,0,Math.PI*2); g.fill();
      }

      const currentYear = new Date().getFullYear();
      let line1, line2 = '';
      if (isForecast) {
        line1 = `Predpoveď: ${vCur.toFixed(2)} %`;
      } else {
        line1 = `${currentYear}: ${vCur.toFixed(2)} %`;
        line2 = (vPrev!=null) ? `${currentYear-1}: ${vPrev.toFixed(2)} %` : '';
      }
      const pad = 6;
      g.font = "12px system-ui, -apple-system, Segoe UI, Roboto, Arial";
      g.textAlign = "left";
      const w1 = g.measureText(`${date}`).width;
      const w2 = g.measureText(line1).width;
      const w3 = line2 ? g.measureText(line2).width : 0;
      const boxW = Math.ceil(Math.max(w1, w2, w3)) + pad*2;
      const lineH = 16;
      const lines = line2 ? 3 : 2;
      const boxH = lineH*lines + 6;
      const lx = Math.min(Math.max(x - boxW/2, left), W - right - boxW);
      const ly = Math.max(yCur - boxH - 10, top);
      g.fillStyle = "rgba(11,18,33,0.90)";
      g.fillRect(lx, ly, boxW, boxH);
      g.fillStyle = "white";
      let ty = ly + 14;
      g.fillText(date, lx+pad, ty); ty += lineH;
      g.fillText(line1, lx+pad, ty); ty += lineH;
      if(line2) g.fillText(line2, lx+pad, ty);
    }
    
    // Legenda
    if(legendEl) {
      const currentYear = new Date().getFullYear();
      const legendItems = [
        `<div class="legend-item">
          <div class="legend-line" style="background:#2563eb;"></div>
          <span>${currentYear}</span>
        </div>`
      ];
      if(ref.length > 0) {
        legendItems.push(`
        <div class="legend-item">
          <div class="legend-dash" style="color:#9ec5fe;"></div>
          <span>${currentYear-1}</span>
        </div>`);
      }
      yearColors.forEach(({key, color, name}) => {
        if (yearsPercent[key] && yearsPercent[key].length > 0) {
          legendItems.push(`
          <div class="legend-item">
            <div class="legend-dash" style="color:${color};"></div>
            <span>${name}</span>
          </div>`);
        }
      });
      if(cur.length >= 7) {
        legendItems.push(`
        <div class="legend-item">
          <div class="legend-dash" style="color:#8b5cf6;"></div>
          <span>Predpoveď</span>
        </div>`);
      }
      legendEl.innerHTML = legendItems.join('');
    }
    } catch(e) {
      console.error('Error in drawChart:', e);
      showMsg('Chyba pri vykresľovaní grafu');
    }
  }

  async function fetchToday(){
    showLoading(true);
    try {
      const r = await fetch('/api/today', {cache:'no-store'});
      if(!r.ok){ 
        cardsEl.innerHTML = '<div class="muted">Dáta sa nepodarilo načítať.</div>'; 
        return; 
      }
      const j = await r.json();
      if(j && j.percent !== undefined) {
        renderCards(j);
      } else {
        cardsEl.innerHTML = '<div class="muted">Žiadne dáta.</div>';
      }
    } catch(e) {
      console.error('Error fetching today:', e);
      cardsEl.innerHTML = '<div class="muted">Chyba pri načítaní dát.</div>';
    } finally {
      showLoading(false);
    }
  }

  async function fetchHistory(days){
    showLoading(true);
    try {
      const key = String(days);
      if(cache.has(key)){
        const data = cache.get(key);
        state.records = data.records || [];
        state.prev    = data.prev_year || [];
        state.stats   = data.stats || {};
        state.yearsData = data.years_data || {};
        if(state.records.length > 0) {
          drawChart(state.records, state.prev, state.hoverIdx, state.yearsData);
        }
        renderTable(state.records);
        renderStats(state.stats);
        return;
      }
      const r = await fetch(`/api/history?days=${encodeURIComponent(days)}`, {cache:'no-store'});
      if(!r.ok){ 
        showMsg(`HTTP ${r.status}`);
        tableEl.innerHTML = '<div class="muted">Chyba pri načítaní dát.</div>';
        return; 
      }
      const data = await r.json();
      if(data && data.records) {
        cache.set(key, data);
        state.records = data.records || [];
        state.prev    = data.prev_year || [];
        state.stats   = data.stats || {};
        state.yearsData = data.years_data || {};
        if(state.records.length > 0) {
          drawChart(state.records, state.prev, state.hoverIdx, state.yearsData);
        }
        renderTable(state.records);
        renderStats(state.stats);
      } else {
        tableEl.innerHTML = '<div class="muted">Žiadne dáta.</div>';
      }
    } catch(e) {
      console.error('Error fetching history:', e);
      showMsg('Chyba pri načítaní dát.');
      tableEl.innerHTML = '<div class="muted">Chyba pri načítaní dát.</div>';
    } finally {
      showLoading(false);
    }
  }

  function bindExport(){
    if(btnCsv){
      btnCsv.addEventListener('click', ()=>{
        const d = Number(rangeEl.value || 30);
        window.location.href = `/api/export?fmt=csv&days=${encodeURIComponent(d)}`;
      });
    }
    if(btnXls){
      btnXls.addEventListener('click', ()=>{
        const d = Number(rangeEl.value || 30);
        window.location.href = `/api/export?fmt=xlsx&days=${encodeURIComponent(d)}`;
      });
    }
    if(btnChartPng){
      btnChartPng.addEventListener('click', ()=>{
        const url = chartEl.toDataURL('image/png');
        const a = document.createElement('a');
        a.href = url;
        a.download = `powergy-graf-${new Date().toISOString().split('T')[0]}.png`;
        a.click();
      });
    }
  }

  function bindHover(){
    const onMove = (ev)=>{
      if(!state.scale || !state.records.length) return;
      const rect = chartEl.getBoundingClientRect();
      const px = (ev.clientX - rect.left) * (chartEl.width / chartEl.clientWidth);
      const dpi = window.devicePixelRatio || 1;
      const xCss = px / dpi;
      const {left, right, W, nx} = state.scale;
      if(xCss < left || xCss > (W-right)){
        state.hoverIdx = null; drawChart(state.records, state.prev, null, state.yearsData); return;
      }
      const usable = (W-left-right);
      const t = (xCss - left) / Math.max(1, usable);
      const idx = Math.round(t * (nx - 1));
      state.hoverIdx = Math.max(0, Math.min(nx-1, idx));
      drawChart(state.records, state.prev, state.hoverIdx, state.yearsData);
    };
    chartEl.addEventListener('mousemove', onMove);
    chartEl.addEventListener('mouseleave', ()=>{ state.hoverIdx = null; drawChart(state.records, state.prev, null, state.yearsData); });
  }

  rangeEl.addEventListener('change', ()=> fetchHistory(Number(rangeEl.value || 30)));
  bindExport(); bindHover();
  fetchToday(); fetchHistory(Number(rangeEl.value || 30));
})();
</script>
</body>
</html>
""")


@app.on_event("startup")
def _startup():
    init_db()


# ---------------------------- Diagnostics ----------------------------
@app.get("/api/health", response_class=JSONUTF8Response)
def api_health():
    try:
        sess = SessionLocal()
        sess.execute(text("select 1"))
        sess.close()
        return {"ok": True}
    except Exception as e:
        return JSONUTF8Response({"ok": False, "detail": str(e)}, status_code=500)


@app.get("/api/db-tables", response_class=JSONUTF8Response)
def api_db_tables():
    sess = SessionLocal()
    try:
        insp = inspect(sess.bind)
        return {"ok": True, "tables": insp.get_table_names()}
    finally:
        sess.close()


@app.get("/api/db-stats", response_class=JSONUTF8Response)
def api_db_stats():
    sess = SessionLocal()
    try:
        total = sess.query(func.count(GasStorageDaily.id)).scalar() or 0
        last = sess.query(GasStorageDaily.date, GasStorageDaily.percent)\
                   .order_by(GasStorageDaily.date.desc()).first()
        return {
            "ok": True,
            "rows": int(total),
            "last_date": (str(last[0]) if last else None),
            "last_percent": (float(last[1]) if last else None),
        }
    except Exception as e:
        return JSONUTF8Response({"ok": False, "error": "exception", "detail": str(e)}, status_code=500)
    finally:
        sess.close()


# ---------------------------- UI Root ----------------------------
@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML.render()


# ---------------------------- Core API ----------------------------
@app.get("/api/today", response_class=JSONUTF8Response)
def api_today():
    sess = SessionLocal()
    try:
        row = sess.query(GasStorageDaily).order_by(GasStorageDaily.date.desc()).first()
        if not row:
            return JSONUTF8Response({"message": "No data yet"}, status_code=404)

        percent = _to_float(row.percent)
        delta   = _to_float(row.delta)
        comment_out = fix_mojibake(row.comment or "")

        return {
            "date": _format_date(row.date),
            "percent": percent,
            "delta": delta,
            "comment": comment_out,
        }
    except SQLAlchemyError as e:
        sess.rollback()
        return JSONUTF8Response({"ok": False, "error": "db_error", "detail": str(e)}, status_code=500)
    finally:
        sess.close()


# Jednoduchý in-memory cache pre history endpoint
_history_cache = {}
_cache_ttl = 30  # sekúnd

@app.get("/api/history", response_class=JSONUTF8Response)
def api_history(days: int = 30):
    try:
        days = int(days)
    except Exception:
        days = 30
    if days <= 0 or days > 366:
        days = 30

    # Skontrolujeme cache
    cache_key = f"history_{days}"
    now = time()
    if cache_key in _history_cache:
        cached_data, cached_time = _history_cache[cache_key]
        if now - cached_time < _cache_ttl:
            resp = JSONUTF8Response(cached_data)
            resp.headers["Cache-Control"] = "public, max-age=30"
            return resp

    sess = SessionLocal()
    try:
        # Optimalizácia: načítame len potrebné stĺpce
        q = sess.query(GasStorageDaily.date, GasStorageDaily.percent, GasStorageDaily.delta).order_by(GasStorageDaily.date.desc()).limit(days)
        rows = list(reversed(q.all()))  # Zoradené od najstaršieho po najnovší (pre graf)

        if not rows:
            resp = JSONUTF8Response({"records": [], "prev_year": [], "stats": {}})
            resp.headers["Cache-Control"] = "public, max-age=30"
            return resp

        records = [{
            "date": _format_date(r.date),
            "percent": round(float(_to_float(r.percent)), 2),
            "delta": None if r.delta is None else round(float(_to_float(r.delta)), 2),
        } for r in rows]

        # Vypočítaj štatistiky
        percents = [r["percent"] for r in records]
        deltas = [r["delta"] for r in records if r["delta"] is not None]
        stats = {
            "min": round(min(percents), 2) if percents else None,
            "max": round(max(percents), 2) if percents else None,
            "avg": round(sum(percents) / len(percents), 2) if percents else None,
            "avg_delta": round(sum(deltas) / len(deltas), 2) if deltas else None,
            "total_change": round(records[-1]["percent"] - records[0]["percent"], 2) if len(records) > 1 else None,
            "trend": "rast" if (records[-1]["percent"] > records[0]["percent"]) else "pokles" if len(records) > 1 else "stabilný"
        }

        # Optimalizácia: jeden dotaz pre predchádzajúci rok
        start_prev = rows[0].date - TD(days=365)
        end_prev   = rows[-1].date - TD(days=365)

        prev_rows = (
            sess.query(GasStorageDaily.date, GasStorageDaily.percent)
            .filter(GasStorageDaily.date >= start_prev,
                    GasStorageDaily.date <= end_prev)
            .all()
        )
        by_date = {p.date: p for p in prev_rows}

        baseline = records[0]["percent"]
        prev_year = []
        for r in rows:
            key = r.date - TD(days=365)
            pr = by_date.get(key)
            if pr:
                prev_year.append({"date": _format_date(pr.date), "percent": round(float(_to_float(pr.percent)), 2)})
            else:
                prev_year.append({"date": _format_date(key), "percent": baseline})

        # Sezónne porovnanie - pridať dáta pre predchádzajúce roky (2023, 2022, atď.)
        # Optimalizácia: namiesto N*M dotazov (N=dni, M=roky), urobíme M dotazov
        years_data = {}
        if rows:
            current_year = rows[0].date.year
            baseline = records[0]["percent"]
            
            # Vypočítame všetky dátumy, ktoré potrebujeme pre každý rok
            for year_offset in range(2, 5):  # 2023, 2022, 2021
                year_key = f"year_{current_year - year_offset}"
                # Vytvoríme zoznam dátumov pre tento rok
                target_dates = [r.date - TD(days=365 * year_offset) for r in rows]
                if not target_dates:
                    continue
                
                # Jeden dotaz pre všetky dátumy tohto roka - optimalizácia: načítame len potrebné stĺpce
                min_date = min(target_dates)
                max_date = max(target_dates)
                prev_rows_year_all = (
                    sess.query(GasStorageDaily.date, GasStorageDaily.percent)
                    .filter(GasStorageDaily.date >= min_date,
                            GasStorageDaily.date <= max_date)
                    .all()
                )
                # Vytvoríme mapu dátum -> percent
                by_date_year = {p.date: p for p in prev_rows_year_all}
                
                # Zostavíme výsledok
                year_rows = []
                for r in rows:
                    key = r.date - TD(days=365 * year_offset)
                    pr = by_date_year.get(key)
                    if pr:
                        year_rows.append({"date": _format_date(key), "percent": round(float(_to_float(pr.percent)), 2)})
                    else:
                        year_rows.append({"date": _format_date(key), "percent": baseline})
                
                if year_rows:
                    years_data[year_key] = year_rows

        result_data = {"records": records, "prev_year": prev_year, "stats": stats, "years_data": years_data}
        
        # Uložíme do cache
        _history_cache[cache_key] = (result_data, now)
        
        resp = JSONUTF8Response(result_data)
        resp.headers["Cache-Control"] = "public, max-age=30"
        return resp

    except Exception as e:
        return JSONUTF8Response({"ok": False, "error": str(e)}, status_code=500)
    finally:
        sess.close()


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
            w.writerow(["date", "percent", "delta", "comment"])
            for r in rows:
                w.writerow([str(r.date),
                            f"{_to_float(r.percent):.2f}" if _to_float(r.percent) is not None else "",
                            "" if r.delta is None else f"{_to_float(r.delta):.2f}",
                            (r.comment or "").replace("\n"," ").strip()])
            buf.seek(0)
            return StreamingResponse(
                iter([buf.getvalue()]),
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": 'attachment; filename="powergy_gas_storage.csv"'}
            )
        elif fmt.lower() in ("xlsx", "xls"):
            if openpyxl is None:
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(["date", "percent", "delta", "comment"])
                for r in rows:
                    w.writerow([str(r.date),
                                f"{_to_float(r.percent):.2f}" if _to_float(r.percent) is not None else "",
                                "" if r.delta is None else f"{_to_float(r.delta):.2f}",
                                (r.comment or "").replace("\n"," ").strip()])
                buf.seek(0)
                return StreamingResponse(
                    iter([buf.getvalue()]),
                    media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="powergy_gas_storage.csv"'}
                )
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "gas_storage"
            ws.append(["date", "percent", "delta", "comment"])
            for r in rows:
                ws.append([str(r.date),
                           float(f"{_to_float(r.percent):.2f}") if _to_float(r.percent) is not None else None,
                           None if r.delta is None else float(f"{_to_float(r.delta):.2f}"),
                           (r.comment or "").strip()])
            xbuf = io.BytesIO()
            wb.save(xbuf)
            xbuf.seek(0)
            return StreamingResponse(
                xbuf,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": 'attachment; filename="powergy_gas_storage.xlsx"'}
            )
        else:
            return JSONUTF8Response({"ok": False, "error": "Unknown format"}, status_code=400)

    finally:
        sess.close()


# ---------------------------- Comments ----------------------------
@app.api_route("/api/backfill-agsi", methods=["GET", "POST"], response_class=JSONUTF8Response)
def api_backfill_agsi(from_date: str | None = Query(None, description="YYYY-MM-DD; ak chýba, použije najstarší dátum v DB alebo 2021-01-01")):
    """
    Manuálne spustenie backfillu dát z AGSI API.
    Stiahne všetky dáta od from_date (alebo od najstaršieho dátumu v DB) po včerajšok.
    Poznámka: AGSI API má oneskorenie, dáta pre dnešok ešte nemusia byť dostupné.
    Pre sezónne porovnanie potrebujeme dáta minimálne od 2021-01-01.
    """
    if not os.getenv("AGSI_API_KEY"):
        return JSONUTF8Response({"ok": False, "error": "AGSI_API_KEY missing"}, status_code=400)
    
    sess = SessionLocal()
    try:
        # Zistíme maximálny dátum (včerajšok, lebo AGSI API má oneskorenie)
        max_date = dt.date.today() - dt.timedelta(days=1)
        
        if from_date:
            start_date = from_date
            start_date_obj = dt.date.fromisoformat(start_date)
            if start_date_obj > max_date:
                return JSONUTF8Response({
                    "ok": False, 
                    "error": f"from_date ({start_date}) is in the future. AGSI API has delay, max available date is {max_date}",
                    "from_date": start_date,
                    "max_available_date": str(max_date)
                }, status_code=400)
        else:
            # Zistíme najstarší dátum v DB - ak chýbajú dáta pred 2021, načítame od 2021
            earliest_row = sess.query(GasStorageDaily).order_by(GasStorageDaily.date.asc()).first()
            last_row = sess.query(GasStorageDaily).order_by(GasStorageDaily.date.desc()).first()
            
            # Pre sezónne porovnanie potrebujeme dáta minimálne od 2021-01-01
            min_required_date = dt.date(2021, 1, 1)
            
            if earliest_row and earliest_row.date <= min_required_date:
                # Máme dáta od 2021, takže načítame len chýbajúce dátumy
                if last_row:
                    calculated_start = last_row.date + dt.timedelta(days=1)
                    if calculated_start > max_date:
                        return JSONUTF8Response({
                            "ok": False,
                            "message": "Database is up to date",
                            "earliest_date": str(earliest_row.date),
                            "latest_date": str(last_row.date),
                            "max_available_date": str(max_date)
                        })
                    start_date = str(calculated_start)
                else:
                    start_date = str(min_required_date)
            else:
                # Chýbajú dáta pred 2021 alebo DB je prázdna - načítame od 2021
                start_date = str(min_required_date)
        
        from .scraper import backfill_agsi
        result = backfill_agsi(start_date)
        return {"ok": True, "from_date": start_date, "max_available_date": str(max_date), **result}
    except Exception as e:
        return JSONUTF8Response({"ok": False, "error": str(e)}, status_code=500)
    finally:
        sess.close()


@app.post("/api/backfill-comments", response_class=JSONUTF8Response)
def backfill_comments(limit: int = 60, force: bool = False):
    """Fill missing comments for last N rows; if force=True, overwrite all (CAREFUL with tokens)."""
    sess = SessionLocal()
    try:
        rows = (sess.query(GasStorageDaily)
                    .order_by(GasStorageDaily.date.desc())
                    .limit(limit).all())
        changed = 0
        for r in rows:
            if force or not r.comment or not str(r.comment).strip():
                current = _to_float(r.percent)
                delta   = _to_float(r.delta)
                # compute yoy_gap
                try:
                    prev_date = r.date.replace(year=r.date.year - 1)
                except ValueError:
                    prev_date = r.date - TD(days=365)
                prev = (sess.query(GasStorageDaily)
                             .filter(GasStorageDaily.date == prev_date)
                             .first())
                yoy_gap = None
                if prev and current is not None and _to_float(prev.percent) is not None:
                    yoy_gap = round(current - _to_float(prev.percent), 2)
                # compute trend7 (7-day trend)
                trend7 = 0.0
                try:
                    week_ago = r.date - TD(days=7)
                    week_ago_row = sess.query(GasStorageDaily).filter(GasStorageDaily.date == week_ago).first()
                    if week_ago_row and current is not None and _to_float(week_ago_row.percent) is not None:
                        trend7 = round(current - _to_float(week_ago_row.percent), 2)
                except Exception:
                    pass
                r.comment = generate_comment_safe(current or 0.0, delta, yoy_gap, trend7)
                changed += 1
        sess.commit()
        return {"ok": True, "updated": changed}
    except Exception as e:
        sess.rollback()
        return JSONUTF8Response({"ok": False, "error": str(e)}, status_code=500)
    finally:
        sess.close()


@app.api_route("/api/refresh-comment", methods=["GET", "POST"], response_class=JSONUTF8Response)
def api_refresh_comment(force: bool = Query(False, description="Ak true, prepíše existujúci komentár")):
    """
    Vygeneruje a uloží komentár pre najnovší záznam.
    - ak komentár už existuje a force=false → neregeneruje (šetrenie tokenov),
    - vypočíta yoy_gap (rozdiel voči minuloročnému dátumu),
    - všetky čísla pretypuje na float (žiadny 'Unknown format code f').
    """
    sess = SessionLocal()
    try:
        row = sess.query(GasStorageDaily).order_by(GasStorageDaily.date.desc()).first()
        if not row:
            return JSONUTF8Response({"ok": False, "error": "No rows"}, status_code=404)

        # Regeneruj komentár ak je prázdny alebo ak je force=True
        # Kontrolujeme aj prázdne stringy a whitespace
        comment_text = str(row.comment) if row.comment else ""
        has_comment = comment_text.strip() and len(comment_text.strip()) > 0
        
        if has_comment and not force:
            return {"ok": True, "skipped": True, "date": str(row.date), "has_comment": True, "comment_length": len(comment_text)}

        current = _to_float(row.percent)
        delta   = _to_float(row.delta)

        # nájdi minuloročný deň (ošetrenie 29.2.)
        d = row.date
        try:
            prev_date = d.replace(year=d.year - 1)
        except ValueError:
            prev_date = d - TD(days=365)

        prev = sess.query(GasStorageDaily).filter(GasStorageDaily.date == prev_date).first()
        prev_percent = _to_float(prev.percent) if prev else None
        yoy_gap = None if (current is None or prev_percent is None) else round(current - prev_percent, 2)

        # compute trend7 (7-day trend)
        trend7 = 0.0
        try:
            week_ago = d - TD(days=7)
            week_ago_row = sess.query(GasStorageDaily).filter(GasStorageDaily.date == week_ago).first()
            if week_ago_row and current is not None and _to_float(week_ago_row.percent) is not None:
                trend7 = round(current - _to_float(week_ago_row.percent), 2)
        except Exception:
            pass

        comment_text = generate_comment_safe(current or 0.0, delta, yoy_gap, trend7)
        row.comment = comment_text
        sess.commit()

        return {
            "ok": True, 
            "date": str(row.date), 
            "percent": current, 
            "delta": delta, 
            "yoy_gap": yoy_gap, 
            "trend7": trend7,
            "comment_generated": bool(comment_text and comment_text.strip())
        }
    except Exception as e:
        sess.rollback()
        return JSONUTF8Response({"ok": False, "error": str(e)}, status_code=500)
    finally:
        sess.close()


# ---------------------------- Deltas recompute ----------------------------
@app.post("/api/recompute-deltas")
@app.get("/api/recompute-deltas")
def api_recompute_deltas(days: int | None = Query(None)):
    """
    Prepočíta denné zmeny (delta) v tabuľke gas_storage_daily.
    - Bez parametru -> prepočet celej tabuľky
    - ?days=N      -> prepočet iba za posledných N dní (+ predchádzajúci deň ako lag)
    """
    sess = SessionLocal()
    try:
        if days is not None:
            try:
                days = int(days)
            except Exception:
                return JSONUTF8Response({"ok": False, "error": "days must be integer"}, status_code=400)
            if days <= 0:
                return JSONUTF8Response({"ok": False, "error": "days must be > 0"}, status_code=400)
            days = min(days, 365*5)

            # inkrementálny prepočet s bezpečným intervalom
            sql = text("""
                WITH bounds AS (
                  SELECT (MAX(date) - (:d || ' days')::interval)::date AS since
                  FROM gas_storage_daily
                ),
                lagged AS (
                  SELECT g.date,
                         LAG(g.percent) OVER (ORDER BY g.date) AS lag_percent
                  FROM gas_storage_daily g
                  WHERE g.date >= (SELECT since FROM bounds) - INTERVAL '1 day'
                )
                UPDATE gas_storage_daily g
                   SET delta = CASE
                                 WHEN l.lag_percent IS NULL THEN NULL
                                 ELSE ROUND((g.percent - l.lag_percent)::numeric, 2)::double precision
                               END
                  FROM lagged l
                 WHERE l.date = g.date
                   AND g.date >= (SELECT since FROM bounds)
            """)
            res = sess.execute(sql, {"d": days})
            sess.commit()
            changed = getattr(res, "rowcount", 0) or 0
            return {"ok": True, "mode": f"last_{days}_days", "changed": changed}

        # full prepočet
        sql = text("""
            WITH lagged AS (
              SELECT date,
                     LAG(percent) OVER (ORDER BY date) AS lag_percent
              FROM gas_storage_daily
            )
            UPDATE gas_storage_daily g
               SET delta = CASE
                             WHEN l.lag_percent IS NULL THEN NULL
                             ELSE ROUND((g.percent - l.lag_percent)::numeric, 2)::double precision
                           END
              FROM lagged l
             WHERE l.date = g.date
        """)
        res = sess.execute(sql)
        sess.commit()
        changed = getattr(res, "rowcount", 0) or 0
        return {"ok": True, "mode": "full", "changed": changed}

    except Exception as e:
        sess.rollback()
        return JSONUTF8Response({"ok": False, "error": str(e)}, status_code=500)
    finally:
        sess.close()


# ---------------------------- Daily ingest from AGSI ----------------------------
def _agsi_headers():
    key = os.getenv("AGSI_API_KEY", "")
    return {"x-key": key} if key else {}

def _fetch_agsi_eu_full(date_str: str) -> float | None:
    """Vráti percento naplnenia 'full' pre EU v daný gas_day (YYYY-MM-DD), alebo None."""
    url = "https://agsi.gie.eu/api"
    params = {
        "type": "eu",
        "from": date_str,
        "to": date_str,
        "size": 100,
        "gas_day": "asc",
        "page": 1,
    }
    r = requests.get(url, headers=_agsi_headers(), params=params, timeout=25)
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

@app.api_route("/api/ingest-agsi-today", methods=["GET", "POST"], response_class=JSONUTF8Response)
def api_ingest_agsi_today(date: str | None = Query(None, description="YYYY-MM-DD; ak chýba, skúsi today→today-1→today-2")):
    """
    Dotiahne a uloží posledný dostupný deň z AGSI (EU 'full' %), spraví upsert a spočíta deltu.
    """
    if not os.getenv("AGSI_API_KEY"):
        return JSONUTF8Response({"ok": False, "error": "AGSI_API_KEY missing"}, status_code=400)

    sess = SessionLocal()
    try:
        # Zistíme posledný dátum v DB
        last_row = sess.query(GasStorageDaily).order_by(GasStorageDaily.date.desc()).first()
        # Pre sezónne porovnanie potrebujeme dáta minimálne od 2021
        last_date = last_row.date if last_row else dt.date(2021, 1, 1)
        
        candidates = []
        if date:
            candidates = [date]
        else:
            today = dt.date.today()
            days_missing = (today - last_date).days
            
            # Ak je posledný dátum starší ako 2 dni, použijeme backfill
            if days_missing > 2:
                from .scraper import backfill_agsi
                try:
                    start_date = last_date + dt.timedelta(days=1)
                    result = backfill_agsi(str(start_date))
                    # Po backfille aktualizujeme last_date
                    last_row = sess.query(GasStorageDaily).order_by(GasStorageDaily.date.desc()).first()
                    last_date = last_row.date if last_row else last_date
                except Exception as e:
                    pass  # Pokračujeme s jednotlivými dňami
            
            # AGSI API má oneskorenie - dáta pre dnešok ešte nemusia byť dostupné
            # Skúsime najnovšie dáta od včerajška dozadu
            for i in range(1, 6):  # Včera až 5 dní dozadu (nie dnes!)
                candidate = today - dt.timedelta(days=i)
                if candidate >= last_date:
                    candidates.append(str(candidate))

        picked_date = None
        picked_full = None
        for d in candidates:
            val = _fetch_agsi_eu_full(d)
            if val is not None:
                picked_date = d
                picked_full = round(float(val), 2)
                break

        if picked_date is None:
            return JSONUTF8Response({"ok": False, "error": "No AGSI data for candidates", "candidates": candidates, "last_date_in_db": str(last_date)}, status_code=404)

        # Upsert do DB
        d = dt.date.fromisoformat(picked_date)
        row = sess.query(GasStorageDaily).filter(GasStorageDaily.date == d).first()

        # nájdi včerajšok pre deltu
        prev_date = d - dt.timedelta(days=1)
        prev = sess.query(GasStorageDaily).filter(GasStorageDaily.date == prev_date).first()
        prev_percent = _to_float(prev.percent) if prev else None
        delta = None if prev_percent is None else round(picked_full - prev_percent, 2)

        if row:
            row.percent = picked_full
            row.delta = delta
            # Ak komentár chýba, vygenerujeme ho
            if not row.comment or not str(row.comment).strip():
                # Vypočítaj trend7 a yoy_gap pre komentár
                trend7 = 0.0
                yoy_gap = 0.0
                try:
                    week_ago = d - dt.timedelta(days=7)
                    week_ago_row = sess.query(GasStorageDaily).filter(GasStorageDaily.date == week_ago).first()
                    if week_ago_row and week_ago_row.percent is not None:
                        trend7 = round(picked_full - _to_float(week_ago_row.percent), 2)
                    
                    try:
                        prev_year_date = d.replace(year=d.year - 1)
                    except ValueError:
                        prev_year_date = d - dt.timedelta(days=365)
                    prev_year_row = sess.query(GasStorageDaily).filter(GasStorageDaily.date == prev_year_date).first()
                    if prev_year_row and prev_year_row.percent is not None:
                        yoy_gap = round(picked_full - _to_float(prev_year_row.percent), 2)
                except Exception:
                    pass
                
                row.comment = generate_comment_safe(picked_full, delta, yoy_gap, trend7)
        else:
            sess.add(GasStorageDaily(date=d, percent=picked_full, delta=delta, comment=None))

        sess.commit()
        return {"ok": True, "date": picked_date, "percent": picked_full, "delta": delta}
    except Exception as e:
        sess.rollback()
        return JSONUTF8Response({"ok": False, "error": str(e)}, status_code=500)
    finally:
        sess.close()
