# v0.81

## Nytt i v0.81

- Webb-UI förbättrad för **responsiv och mobilvänlig visning**:
  - bättre skalning efter fönsterstorlek
  - förbättrad radbrytning för långa texter/loggar och långa filnamn
  - historiktabellen anpassas till mobil-kort med tydliga fältetiketter
  - förbättrad layout för navigation, knapprader och pagination på små skärmar
- Fix för edge cases där innehåll tidigare kunde hamna utanför viewport på mindre enheter.

## Tidigare i v0.8

- Ny policy för att **behålla/inte behålla nypackad fil** baserat på inställbar tröskel `keep_min_savings_percent`.
  - Om besparing är under tröskeln behålls originalinnehåll, men filen döps ändå om med suffix `_rezipped` för att undvika omkörning.
- `_rezipped`-markering används konsekvent för färdigbehandlade filer och dessa hoppas över vid scanning.
- Ny **Stop-knapp** i UI för att avbryta aktiv körning; arbetskatalogen (`/jobs` eller konfigurerad `work_dir`) rensas efter stopp.
- Cron-körning startar inte om en körning redan är aktiv (överlappsskydd).
- Ny historikhantering:
  - ta bort enskild rad
  - töm all historik (med bekräftelse)
  - summering av totalt sparad datamängd
- Ny inställning för **ljust/mörkt läge** (`theme`).
- Ny funktion för att **byta lösenord** för web UI direkt i Settings (om auth inte är låst via env-variabler).
- API/version uppdaterad till `v0.8`.

## Noteringar

- RAR-konvertering kräver fortsatt `rar`-binär.
- CPU-status kan visa `sampling...` vid första mätningen.
- Om `AUTH_USER`/`AUTH_PASS` används via miljövariabler är lösenordsbyte i UI spärrat av design.