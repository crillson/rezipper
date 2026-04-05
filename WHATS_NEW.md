# v0.7

## Nytt i v0.7

- Rezipper minns nu vilka filer som redan är färdigoptimerade och hoppar över oförändrade filer efter omstart.
- Nytt val i inställningar: välj målformat vid ompackning (`same`, `zip`, `7z`, `rar`).
- Konvertering mellan format stöds nu, t.ex. `.zip` -> `.7z` eller `.rar`.
- Live-status visar nu aktivt steg per körning (queued/preparing/extracting/packing/crc/replace m.fl.).
- Dashboard visar trådaktivitet för kö-tråd och komprimeringstrådar i realtid.
- Debug-scan visar valt output-format och antal filer som skippades som redan bearbetade.
- Versionsinformation uppdaterad till `v0.7` i API/UI.

## Noteringar

- Om målformat skiljer sig från källformat kommer filen att byta filändelse vid slutförd körning.
- Vid konvertering till RAR krävs `rar`-binären installerad i containern/systemet.
- CPU-visning kan visa `sampling...` första uppdateringen innan nästa mätintervall.