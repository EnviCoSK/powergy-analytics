#!/bin/bash
# Automatický deploy skript pre GitHub a Render.com

set -e  # Zastaví sa pri chybe

echo "🚀 Spúšťam automatický deploy..."

# Farba pre výstup
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Skontroluj, či sme v git repozitári
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo -e "${RED}❌ Nie je to git repozitár!${NC}"
    echo "Inicializujem git repozitár..."
    git init
    git branch -M main
fi

# Skontroluj, či existuje remote
if ! git remote get-url origin > /dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  Remote 'origin' neexistuje.${NC}"
    echo "Prosím, nastav remote repozitár:"
    echo "  git remote add origin https://github.com/VASE_USERNAME/powergy-analytics.git"
    exit 1
fi

# Zobraz zmeny
echo -e "${YELLOW}📋 Zmeny v súboroch:${NC}"
git status --short

# Pýtaj sa na commit message, ak nie je zadaný ako argument
if [ -z "$1" ]; then
    echo ""
    read -p "Zadaj commit message (alebo stlač Enter pre default): " COMMIT_MSG
    if [ -z "$COMMIT_MSG" ]; then
        COMMIT_MSG="Aktualizácia: $(date '+%Y-%m-%d %H:%M:%S')"
    fi
else
    COMMIT_MSG="$1"
fi

# Pridaj všetky zmeny
echo -e "${YELLOW}➕ Pridávam zmeny...${NC}"
git add .

# Commit
echo -e "${YELLOW}💾 Vytváram commit...${NC}"
git commit -m "$COMMIT_MSG" || {
    echo -e "${YELLOW}⚠️  Žiadne zmeny na commitovanie.${NC}"
    exit 0
}

# Zisti aktuálnu vetvu
BRANCH=$(git branch --show-current)
echo -e "${YELLOW}🌿 Aktuálna vetva: ${BRANCH}${NC}"

# Push
echo -e "${YELLOW}📤 Pushujem na GitHub...${NC}"
git push origin "$BRANCH" || {
    echo -e "${RED}❌ Chyba pri pushovaní!${NC}"
    echo "Skúste manuálne: git push origin $BRANCH"
    exit 1
}

echo -e "${GREEN}✅ Úspešne pushnuté na GitHub!${NC}"
echo -e "${GREEN}🎉 Render.com by mal automaticky nasadiť zmeny.${NC}"
echo ""
echo "Sleduj nasadenie na: https://dashboard.render.com"

