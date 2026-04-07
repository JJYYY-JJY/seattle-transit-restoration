# Data Publishing Policy

This repository does not commit downloaded or generated datasets by default.

Do not upload these paths:
- `data/raw/**`: external downloads (GTFS archives, ACS payloads, NOAA payloads)
- `data/processed/**`: regenerated outputs (manifests, intermediate tables)

Reasons:
- File size and repository bloat
- Potential API query leakage in raw payload metadata (for example, URLs that may include query keys)
- Better reproducibility by regenerating from scripts

Regenerate data locally with:
- `bash scripts/download_data.sh all`
- Source-specific scripts under `src/gtfs`, `src/census`, `src/weather`

If you must share data, publish it separately in object storage (or a data release) and keep this repo code-only.
