#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_NAME="auto-api-to-skill"
WORK_DIR="$(mktemp -d /tmp/${SKILL_NAME}-publish-XXXXXX)"
trap 'rm -rf "$WORK_DIR"' EXIT

TS="$(date +%Y%m%d%H%M%S)"
PUBLISH_SKILL_INSTALL_URL="${PUBLISH_SKILL_INSTALL_URL:-https://skill.vyibc.com/install-publish-skill.sh}"

echo "Publishing $SKILL_NAME..."

# 1. Upload the Python generator to R2
echo "  Uploading generator..."
"$ROOT_DIR/scripts/upload-file.sh" \
  --file "$ROOT_DIR/scripts/generate-project.py" \
  --name "auto-api-to-skill-generate.py" >/dev/null
echo "  Generator: https://skill.vyibc.com/auto-api-to-skill-generate.py"

# 2. Upload run.sh as the CLI entry point
echo "  Uploading CLI..."
"$ROOT_DIR/scripts/upload-file.sh" \
  --file "$ROOT_DIR/skills/$SKILL_NAME/scripts/run.sh" \
  --name "${SKILL_NAME}.sh" >/dev/null
echo "  CLI: https://skill.vyibc.com/${SKILL_NAME}.sh"

# 3. Package the skill directory
cp -R "$ROOT_DIR/skills/$SKILL_NAME" "$WORK_DIR/$SKILL_NAME"
ZIP_FILE="$WORK_DIR/${SKILL_NAME}-${TS}.zip"

python3 - "$WORK_DIR" "$SKILL_NAME" "$ZIP_FILE" <<'PY'
import os, sys, zipfile
root, skill, dst = sys.argv[1], sys.argv[2], sys.argv[3]
base = os.path.join(root, skill)
with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
    for cur, _, files in os.walk(base):
        for f in files:
            path = os.path.join(cur, f)
            z.write(path, os.path.relpath(path, root))
PY

ZIP_JSON="$("$ROOT_DIR/scripts/upload-file.sh" --file "$ZIP_FILE" --name "${SKILL_NAME}-${TS}.zip" --path "${SKILL_NAME}/release")"
ZIP_URL="$(printf '%s' "$ZIP_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("image_url",""))')"
ZIP_URL_TS="${ZIP_URL}?ts=${TS}"

# 4. Create and upload install script
INSTALL_SCRIPT="$WORK_DIR/install-${SKILL_NAME}.sh"
PUBLISH_TEMPLATE="$WORK_DIR/install-publish-skill.sh"
curl -fsSL "$PUBLISH_SKILL_INSTALL_URL" -o "$PUBLISH_TEMPLATE"

python3 - "$PUBLISH_TEMPLATE" "$INSTALL_SCRIPT" "$SKILL_NAME" "$ZIP_URL_TS" <<'PY'
import pathlib, re, sys
src, dst, skill_name, zip_url = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3], sys.argv[4]
text = src.read_text()
text = re.sub(r'^SKILL_NAME="[^"]*"$', f'SKILL_NAME="{skill_name}"', text, flags=re.M)
text = re.sub(r'^ZIP_URL="[^"]*"$', f'ZIP_URL="{zip_url}"', text, flags=re.M)
text = re.sub(r'^(# Auto-generated one-click install script for: ).*$', rf'\1{skill_name}', text, flags=re.M)
dst.write_text(text)
PY

chmod +x "$INSTALL_SCRIPT"
"$ROOT_DIR/scripts/upload-file.sh" --file "$INSTALL_SCRIPT" --name "install-${SKILL_NAME}.sh" >/dev/null

echo ""
echo "Published successfully!"
echo ""
echo "SKILL_INSTALL_COMMAND=bash <(curl -fsSL 'https://skill.vyibc.com/install-${SKILL_NAME}.sh?ts=${TS}')"
echo "CLI_COMMAND=bash <(curl -fsSL https://skill.vyibc.com/${SKILL_NAME}.sh) --spec /path/to/spec.json --out /path/to/output"
