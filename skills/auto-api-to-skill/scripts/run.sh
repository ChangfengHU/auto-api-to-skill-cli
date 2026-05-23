#!/usr/bin/env bash
# auto-api-to-skill skill runner
set -euo pipefail

CONFIG_URL="${AUTO_API_SKILL_CONFIG:-https://skill.vyibc.com/private/a7f3k9/auto-api-to-skill-config.json}"
GENERATOR_URL="${AUTO_API_SKILL_GENERATOR:-https://skill.vyibc.com/auto-api-to-skill-generate.py}"
CACHE_DIR="$HOME/.auto-api-to-skill"
CONFIG_CACHE="$CACHE_DIR/config.json"
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

# 下载 config（首次或 --update）
if [[ ! -f "$CONFIG_CACHE" || "$UPDATE" == "1" ]]; then
  echo "Fetching config..."
  curl -fsSL "$CONFIG_URL" -o "$CONFIG_CACHE"
fi

# 将 config.json 所有 key 加载为环境变量（不覆盖已有的）
if [[ -f "$CONFIG_CACHE" ]]; then
  while IFS='=' read -r key value; do
    [[ -z "$key" ]] && continue
    # 只在变量未设置时才赋值
    if [[ -z "${!key:-}" ]]; then
      export "$key"="$value"
    fi
  done < <(python3 -c "
import json, sys
c = json.load(open('$CONFIG_CACHE'))
for k, v in c.items():
    print(f'{k}={v}')
")
fi

# 下载生成器（首次或 --update）
if [[ ! -f "$GENERATOR" || "$UPDATE" == "1" ]]; then
  echo "Fetching generator..."
  curl -fsSL "$GENERATOR_URL" -o "$GENERATOR"
fi

exec python3 "$GENERATOR" "${PASS[@]}"
