# Automatické nasadenie zmien na GitHub

## Rýchly spôsob - Použitie deploy skriptu

### 1. Prvé nastavenie (iba raz)

```bash
# Pridaj remote repozitár (nahraď URL svojím GitHub repozitárom)
git remote add origin https://github.com/VASE_USERNAME/powergy-analytics.git

# Alebo ak už máš repozitár, skontroluj:
git remote -v
```

### 2. Automatické pushovanie zmien

Jednoducho spusti skript:

```bash
./deploy.sh
```

Alebo s vlastným commit message:

```bash
./deploy.sh "Oprava chýb v OpenAI API"
```

Skript automaticky:
- ✅ Pridá všetky zmeny
- ✅ Vytvorí commit
- ✅ Pushne na GitHub
- ✅ Render.com automaticky nasadí zmeny

## Alternatívne spôsoby

### Spôsob 1: Git alias (najrýchlejší)

Pridaj do `~/.gitconfig`:

```bash
git config --global alias.deploy '!f() { git add . && git commit -m "${1:-Auto deploy}" && git push; }; f'
```

Potom stačí:
```bash
git deploy "Moja správa"
```

### Spôsob 2: Git hook (automaticky pri každom commite)

Vytvor `.git/hooks/post-commit`:

```bash
#!/bin/bash
git push origin main
```

A nastav spustiteľnosť:
```bash
chmod +x .git/hooks/post-commit
```

⚠️ **Pozor:** Toto pushne automaticky pri každom commite, aj lokálnom!

### Spôsob 3: Manuálne (krok za krokom)

```bash
git add .
git commit -m "Tvoja správa"
git push origin main
```

## GitHub Actions (automatická kontrola)

Ak máš GitHub repozitár, workflow v `.github/workflows/auto-deploy.yml` automaticky:
- Skontroluje syntax Python kódu
- Zobrazí informácie o nasadení

## Render.com automatické nasadenie

Render.com automaticky deteguje nové commity a nasadí ich, ak máš:
- ✅ `autoDeploy: true` v `render.yaml` (už máš)
- ✅ Repozitár pripojený k Render službe

## Riešenie problémov

**Problém:** `git remote add` hovorí, že remote už existuje
```bash
# Skontroluj existujúce remote
git remote -v

# Ak chceš zmeniť URL:
git remote set-url origin NOVY_URL
```

**Problém:** Push vyžaduje autentifikáciu
```bash
# Použi GitHub Personal Access Token alebo SSH
# Pre HTTPS:
git remote set-url origin https://TOKEN@github.com/USERNAME/REPO.git

# Alebo nastav SSH key (odporúčané)
```

**Problém:** Skript nie je spustiteľný
```bash
chmod +x deploy.sh
```

## Bezpečnosť

⚠️ **NIKDY** necommitni:
- `.env` súbory s API kľúčmi
- Databázové súbory
- Osobné údaje

Všetko toto je už v `.gitignore` ✅

