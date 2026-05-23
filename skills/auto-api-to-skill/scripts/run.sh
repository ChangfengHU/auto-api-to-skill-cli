#!/usr/bin/env bash
# auto-api-to-skill skill runner
# Downloads the generator from R2 on first use, then runs it.
set -euo pipefail

GENERATOR_URL="${AUTO_API_SKILL_GENERATOR:-https://skill.vyibc.com/auto-api-to-skill-generate.py}"
CACHE_DIR="$HOME/.auto-api-to-skill"
GENERATOR="$CACHE_DIR/generate-project.py"

UPDATE=0
PASS=()

for arg in "$@"; do
  case "$arg" in
    --update) UPDATE=1 ;;
    *) PASS+=("$arg") ;;
  esac
done

mkdir -p "$CACHE_DIR"

if [[ ! -f "$GENERATOR" || "$UPDATE" == "1" ]]; then
  echo "Fetching auto-api-to-skill generator..."
  curl -fsSL "$GENERATOR_URL" -o "$GENERATOR"
fi

exec python3 "$GENERATOR" "${PASS[@]}"
