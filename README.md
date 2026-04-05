# Rezipper Docker (v0.81)

Docker-baserad tjänst som optimerar `.zip`, `.7z` och `.rar`-arkiv, verifierar CRC, flyttar original till `.trash`, loggar historik i SQLite och erbjuder lösenordsskyddat webbgränssnitt på port **5063**.

## Funktioner

- ZIP/.7Z-optimering med hög komprimering (`7z -mx=9` om tillgänglig, annars Python fallback för ZIP)
- RAR-stöd via extern `rar`-binär (krävs för att skapa ny RAR)
- Obligatorisk integritetskontroll (CRC-test) innan original ersätts
- Safety net: original flyttas till `/data/.trash`
- Automatisk rensning av `.trash` enligt retention (standard `24h`)
- Schemaläggning via cron-uttryck
- Skydd mot överlappande cron-körningar (ny cron ignoreras om körning redan pågår)
- Start/paus/återuppta/stopp av kö via webb
- SQLite-historik med sök + pagination + radera rad + töm historik
- Summering av totalt sparad datamängd i historikvyn
- Realtidslogg i webbgränssnittet (SSE)
- SMTP-notiser vid kritiska fel
- Inställbart output-format (`same`, `zip`, `7z`, `rar`)
- `_rezipped`-markering för färdigbehandlade filer (skippas i framtida scanning)
- Inställbar policy för att behålla nypackad fil (`keep_min_savings_percent`)
- Mörkt/ljust tema i webbgränssnittet
- Förbättrad responsiv/mobilanpassad UI-layout (bättre skalning, mindre overflow)
- Basic Auth:
  - Antingen via env `AUTH_USER`/`AUTH_PASS`
  - Eller first-run setup på `/setup` (användaren väljer själv)
- Byte av web UI-lösenord i Settings (endast när auth inte är låst via env)

## Struktur

- `/data` – arkivfiler att optimera
- `/config` – `jobs.db`, `system.log`, `auth.json`

## Start med Docker Compose

```bash
docker compose up --build -d
```

> Docker-imagen installerar nu även `rar`/`unrar` (från RARLAB) så att `.rar` kan ompackas i containern.

Öppna:

- `http://localhost:5063`

Vid första körning utan `AUTH_USER`/`AUTH_PASS`:

1. Gå till `/setup`
2. Skapa användarnamn/lösenord
3. Logga in via browserns Basic Auth-dialog

## Konfiguration (miljövariabler)

Exempel:

- `TRASH_RETENTION=24h`
- `CRON_SCHEDULE=0 0 * * *`
- `DATA_DIR=/data`
- `CONFIG_DIR=/config`
- `PORT=5063`
- `OUTPUT_FORMAT=same`
- `KEEP_MIN_SAVINGS_PERCENT=0`
- `THEME=dark`
- (valfritt) `AUTH_USER=admin`
- (valfritt) `AUTH_PASS=password123`

## Webbgränssnitt

- **Live status**: nuvarande fil, steg/status per tråd, köstatus, progressbar
- **Kontroll**: Starta, Pausa, Återuppta, Stoppa
- **Historik**: filnamn, originalstorlek, ny storlek, besparing %, ratio, status, tid, radera rad
- **Mobilvänlig historikvy**: tabell anpassas till kort med fältetiketter på små skärmar
- **Summering**: totalt sparad datamängd
- **Sök + pagination**
- **Loggfönster i realtid**
- **Inställningar**: retention, cron, sortering, work dir, output-format, savings-tröskel, tema, SMTP
- **Lösenordsbyte**: byt lösenord för web UI under Settings

## Sortering av kö

Stödda värden för `scan_sort`:

- `name` (bokstavsordning)
- `size` (filstorlek)
- `date` (datum)

## Formatstöd

- `.zip` (fullt stöd, fallback utan 7z)
- `.7z` (kräver 7z)
- `.rar` (extraktion/test via 7z, ompackning kräver `rar`-binär)

Arkitekturen är fortsatt förberedd för fler format via `SUPPORTED_FORMATS` i `app.py`.

## Keep/discard-policy för nypackad fil

Inställningen `keep_min_savings_percent` styr om nypackad fil ska behållas:

- Om faktisk besparing (%) är **>= tröskel**: nypackad fil behålls.
- Om faktisk besparing (%) är **< tröskel**: originalinnehåll behålls, men filen döps om till `*_rezipped.<ext>` så den inte processas igen.
