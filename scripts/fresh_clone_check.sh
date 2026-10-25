#!/usr/bin/env bash
# Fresh clone -> install -> detector models -> every sample through the pipeline with the dummy backend. Prints the elapsed time (target: under 10 minutes).
set -euo pipefail
SRC="${1:-$(git rev-parse --show-toplevel)}"
T=$(mktemp -d)
START=$(date +%s)
git clone -q "$SRC" "$T/repo"
cd "$T/repo"
python3 -m venv "$T/venv"
"$T/venv/bin/pip" install -q -e ".[server]"
export UGOKU_MODEL_DIR="$T/models" UGOKU_CACHE="$T/cache"
"$T/venv/bin/ugoku" models fetch ctd bubble
for w in samples/*/; do
  n=$(basename "$w")
  "$T/venv/bin/ugoku" run "$w"pages/*.png --direction "$w"direction.json --out "$T/out/$n" --procs 2
done
END=$(date +%s)
echo "fresh-clone check ok in $((END - START)) s ($T)"
