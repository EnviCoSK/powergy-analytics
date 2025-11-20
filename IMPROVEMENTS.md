# Návrhy na vylepšenie aplikácie

## 🎨 Vizuálne vylepšenia

### 1. **Farbové indikátory pre trend**
- Zelená farba pre pozitívnu deltu (rast zásob)
- Červená farba pre negatívnu deltu (pokles zásob)
- Neutrálna farba pre nulovú zmenu
- Aplikovať v kartách, tabuľke a grafe

### 2. **Vylepšený graf**
- Pridanie Y-osy s percentami (aktuálne chýba)
- Pridanie dátumov na X-osi (napr. každý 7. deň)
- Legenda pre modrú a svetlomodrú čiaru
- Grid lines pre lepšiu čitateľnosť

### 3. **Responsive design**
- Optimalizácia pre mobilné zariadenia
- Lepšie zobrazenie na tabletoch
- Collapsible sekcie na malých obrazovkách

## 📊 Funkčnosť

### 4. **Štatistiky a metriky**
- Min/Max hodnoty za vybrané obdobie
- Priemerná denná zmena
- Celkový trend (rast/pokles za obdobie)
- Porovnanie s minulým rokom (už máme, ale môžeme zlepšiť zobrazenie)

### 5. **Vylepšená tabuľka**
- Možnosť triedenia podľa stĺpcov (kliknutie na hlavičku)
- Filtrovanie/párovanie dát
- Zvýraznenie aktuálneho dňa
- Paginácia pre dlhé tabuľky (365 dní)

### 6. **Export vylepšenia**
- Export grafu ako PNG/SVG
- Export s vlastným dátumovým rozsahom
- Export s komentármi alebo bez

## 🔔 Notifikácie a upozornenia

### 7. **Upozornenia na významné zmeny**
- Upozornenie pri veľkom poklese zásob (>1% za deň)
- Upozornenie pri dosiahnutí kritických úrovní (<50%, >90%)
- Email/Slack notifikácie (voliteľné)

## 📈 Analytika

### 8. **Predpoveď trendu**
- Jednoduchá lineárna predpoveď na základe posledných 7/30 dní
- Zobrazenie predpokladaného dátumu dosiahnutia určitej úrovne

### 9. **Sezónne porovnanie**
- Zobrazenie viacerých rokov naraz v grafe
- Porovnanie s minulými rokmi (2023, 2024, 2025)
- Zvýraznenie sezónnych vzorcov

## 🎯 UX vylepšenia

### 10. **Loading states**
- Loading indikátory pri načítaní dát
- Skeleton screens namiesto prázdneho stavu
- Progress bar pri exporte

### 11. **Interaktívne prvky**
- Kliknutie na dátum v tabuľke = zobrazenie detailu v grafe
- Zoom v grafe (výber časového rozsahu)
- Tooltip s viac informáciami pri hover

### 12. **Accessibility**
- ARIA labels pre screen readery
- Keyboard navigation
- Kontrastné farby pre lepšiu čitateľnosť

## 🔧 Technické vylepšenia

### 13. **Performance**
- Lazy loading pre dlhé tabuľky
- Virtual scrolling
- Debouncing pri zmene časového rozsahu

### 14. **Caching**
- Service Worker pre offline prístup
- Cache pre statické dáta
- Smart refresh (len nové dáta)

### 15. **Monitoring**
- Error tracking (Sentry alebo podobné)
- Performance monitoring
- Analytics (počet návštev, používané funkcie)

## 📱 Mobilná aplikácia (voliteľné)

### 16. **PWA (Progressive Web App)**
- Možnosť nainštalovať ako aplikáciu
- Push notifikácie
- Offline prístup k posledným dátam

---

## 🎯 Prioritné vylepšenia (odporúčané na začiatok)

1. **Farbové indikátory** - rýchle, vizuálne vylepšenie
2. **Y-os v grafe** - lepšia čitateľnosť
3. **Štatistiky** - užitočné informácie
4. **Loading states** - lepšia UX
5. **Responsive design** - podpora mobilných zariadení

Ktoré z týchto vylepšení by si chcel implementovať ako prvé?

