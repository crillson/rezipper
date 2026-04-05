# Rezipper Docker (v3.0)

Docker-baserad tjänst som optimerar `.zip`, `.7z` och `.rar`-arkiv, verifierar CRC, flyttar original till `.trash`, loggar historik i SQLite och erbjuder lösenordsskyddat webbgränssnitt på port **5063**.

## Funktioner

- ZIP/.7Z-optimering med hög komprimering (`7z -mx=9` om tillgänglig, annars Python fallback för ZIP)
- RAR-stöd via extern `rar`-binär (krävs för att skapa ny RAR)
- Obligatorisk integritetskontroll (CRC-test) innan original ersätts
- Safety net: original flyttas till `/data/.trash`
- Automatisk rensning av `.trash` enligt retention (standard `24h`)
- Schemaläggning via cron-uttryck
- Paus/start/återuppta av kö via webb
- SQLite-historik med sök + pagination
- Realtidslogg i webbgränssnittet (SSE)
- SMTP-notiser vid kritiska fel
- Basic Auth:
  - Antingen via env `AUTH_USER`/`AUTH_PASS`
  - Eller first-run setup på `/setup` (användaren väljer själv)

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
- (valfritt) `AUTH_USER=admin`
- (valfritt) `AUTH_PASS=password123`

## Webbgränssnitt

- **Live status**: nuvarande fil, köstatus, progressbar
- **Kontroll**: Starta, Pausa, Återuppta
- **Historik**: filnamn, originalstorlek, ny storlek, besparing %, ratio, status, tid
- **Sök + pagination**
- **Loggfönster i realtid**
- **Inställningar**: retention, cron, sortering, SMTP

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
