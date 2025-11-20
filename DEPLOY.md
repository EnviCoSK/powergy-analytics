# Návod na nasadenie oprav na web

## Rýchly postup (ak už máte git repozitár)

1. **Commitnite zmeny:**
   ```bash
   git add .
   git commit -m "Oprava chýb: duplicitné definície, OpenAI API, signatúry funkcií"
   ```

2. **Pushnite do repozitára:**
   ```bash
   git push origin main  # alebo master, podľa vašej vetvy
   ```

3. **Render.com automaticky nasadí** (ak máte `autoDeploy: true` v `render.yaml`)

## Detailný postup

### 1. Inicializácia gitu (ak ešte nie je)

```bash
cd /Users/bruno_lipnicka/powergy-analytics
git init
git add .
git commit -m "Initial commit s opravami"
```

### 2. Pripojenie k existujúcemu repozitáru

Ak už máte repozitár na GitHub/GitLab:

```bash
git remote add origin <URL_VAŠEHO_REPOZITÁRA>
git branch -M main
git push -u origin main
```

### 3. Vytvorenie nového repozitára na GitHub

1. Choďte na https://github.com/new
2. Vytvorte nový repozitár (napr. `powergy-analytics`)
3. Potom spustite:

```bash
git remote add origin https://github.com/VASE_USERNAME/powergy-analytics.git
git branch -M main
git push -u origin main
```

### 4. Nasadenie na Render.com

#### A) Ak už máte službu na Render.com:

1. Choďte na https://dashboard.render.com
2. Nájdite vašu službu "powergy-analytics"
3. Render automaticky deteguje nový commit a začne nasadenie
4. Môžete sledovať logy v sekcii "Events" alebo "Logs"

#### B) Ak vytvárate novú službu:

1. Choďte na https://dashboard.render.com
2. Kliknite na "New +" → "Web Service"
3. Pripojte váš GitHub repozitár
4. Render automaticky deteguje `render.yaml` a použije konfiguráciu
5. Nastavte environment variables:
   - `DATABASE_URL` - URL k PostgreSQL databáze
   - `OPENAI_API_KEY` - váš OpenAI API kľúč
   - `AGSI_API_KEY` - (voliteľné) AGSI API kľúč
   - `KYOS_URL` - (už je v render.yaml)
   - `APP_BASE_URL` - (už je v render.yaml)

### 5. Overenie nasadenia

Po nasadení skontrolujte:

1. **Health check:**
   ```
   https://spravy.powergy.sk/api/health
   ```
   Mala by vrátiť: `{"ok": true}`

2. **Hlavná stránka:**
   ```
   https://spravy.powergy.sk/
   ```

3. **API endpoint:**
   ```
   https://spravy.powergy.sk/api/today
   ```

## Manuálne nasadenie (ak nepoužívate git)

Ak chcete nasadiť bez gitu, môžete:

1. **Nahrať súbory cez Render Dashboard:**
   - V Render Dashboard → vaša služba → Settings
   - Môžete nahrať súbory manuálne (ale to nie je odporúčané)

2. **Použiť Render CLI:**
   ```bash
   npm install -g render-cli
   render login
   render deploy
   ```

## Opravy, ktoré boli aplikované

✅ Odstránená duplicitná definícia `_agsi_fetch_all` v `scraper.py`
✅ Odstránené duplicitné importy v `scraper.py`
✅ Opravené volanie `generate_comment` - pridaný výpočet `trend7` a `yoy_gap`
✅ Opravené OpenAI API volanie v `gpt.py` (z `client.responses.create` na `client.chat.completions.create`)
✅ Zmenený model z "gpt-5" na "gpt-4o-mini"
✅ Opravená signatúra `generate_comment_safe` v `main.py`
✅ Pridaný výpočet `trend7` v `backfill_comments` a `api_refresh_comment`

## Poznámky

- Render.com automaticky rebuildne Docker image pri každom pushi
- Cron job (`powergy-scraper-daily`) sa spúšťa každý deň o 5:00
- Ak chcete manuálne spustiť scraper, použite:
  ```bash
  python -c "from app.scraper import run_daily; run_daily()"
  ```

## Riešenie problémov

**Problém:** Render nezačína build
- Skontrolujte, či máte `render.yaml` v root adresári
- Skontrolujte, či sú všetky environment variables nastavené

**Problém:** Aplikácia sa nespustí
- Skontrolujte logy v Render Dashboard → Logs
- Skontrolujte, či je `DATABASE_URL` správne nastavený

**Problém:** OpenAI API nefunguje
- Skontrolujte, či je `OPENAI_API_KEY` nastavený
- Skontrolujte, či máte kredit na OpenAI účte

