#!/usr/bin/env python3
import argparse
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request


def shell_quote(value: str) -> str:
    return shlex.quote(value)


def mode_var(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", name).upper()


def mkdir(path: pathlib.Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write(path: pathlib.Path, content: str, executable: bool = False) -> None:
    mkdir(path.parent)
    path.write_text(content)
    if executable:
        path.chmod(0o755)


def slug_to_title(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-") if part)


def ensure_required(spec: dict, keys: list[str]) -> None:
    missing = [key for key in keys if key not in spec]
    if missing:
        raise SystemExit(f"missing required spec keys: {', '.join(missing)}")


def render_upload_file() -> str:
    return textwrap.dedent(
        """\
        #!/usr/bin/env bash
        set -euo pipefail

        FILE_PATH=""
        OBJECT_NAME=""
        OBJECT_PATH=""
        DOMAIN="${UPLOAD_R2_DOMAIN:-https://skill.vyibc.com}"
        API_URL="${UPLOAD_R2_URL:-https://upload-r2.vyibc.com}"
        API_TOKEN="${UPLOAD_R2_TOKEN:-yt-research-token-2026}"

        while [[ $# -gt 0 ]]; do
          case "$1" in
            --file) FILE_PATH="${2:-}"; shift 2 ;;
            --name) OBJECT_NAME="${2:-}"; shift 2 ;;
            --path) OBJECT_PATH="${2:-}"; shift 2 ;;
            --domain) DOMAIN="${2:-}"; shift 2 ;;
            *) echo "unknown argument: $1" >&2; exit 1 ;;
          esac
        done

        if [[ -z "$FILE_PATH" || -z "$OBJECT_NAME" ]]; then
          echo "usage: upload-file.sh --file <file> --name <name> [--path <path>]" >&2
          exit 1
        fi

        if [[ -n "$OBJECT_PATH" ]]; then
          curl -fsS --location "$API_URL" \\
            --header "Authorization: Bearer $API_TOKEN" \\
            --form "file=@${FILE_PATH}" \\
            --form "domain=${DOMAIN}" \\
            --form "name=${OBJECT_NAME}" \\
            --form "path=${OBJECT_PATH}"
        else
          curl -fsS --location "$API_URL" \\
            --header "Authorization: Bearer $API_TOKEN" \\
            --form "file=@${FILE_PATH}" \\
            --form "domain=${DOMAIN}" \\
            --form "name=${OBJECT_NAME}"
        fi
        """
    )


def render_publish_remote(repo_name: str, subdir: str = "") -> str:
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail

        REPO_OWNER="${{REPO_OWNER:-ChangfengHU}}"
        REPO_NAME="${{REPO_NAME:-{repo_name}}}"
        REPO_REF="${{REPO_REF:-main}}"
        # 当 skill 项目位于 monorepo 子目录时，REPO_SUBDIR 指向该子目录。
        REPO_SUBDIR="${{REPO_SUBDIR:-{subdir}}}"
        TARBALL_URL="${{TARBALL_URL:-https://codeload.github.com/${{REPO_OWNER}}/${{REPO_NAME}}/tar.gz/refs/heads/${{REPO_REF}}}}"

        WORK_DIR="$(mktemp -d /tmp/publish-{repo_name}-XXXXXX)"
        trap 'rm -rf "$WORK_DIR"' EXIT

        # 私有仓库需要 token：设置 GITHUB_TOKEN 或 CHANGFENG_TOKEN 即可（公开仓库可留空）
        GH_AUTH=()
        _GH_TOKEN="${{GITHUB_TOKEN:-${{CHANGFENG_TOKEN:-}}}}"
        [[ -n "$_GH_TOKEN" ]] && GH_AUTH=(-H "Authorization: Bearer $_GH_TOKEN")

        echo "Fetching ${{REPO_OWNER}}/${{REPO_NAME}}@${{REPO_REF}} ..."
        curl -fsSL ${{GH_AUTH[@]+"${{GH_AUTH[@]}}"}} "$TARBALL_URL" -o "$WORK_DIR/repo.tar.gz"
        tar -xzf "$WORK_DIR/repo.tar.gz" -C "$WORK_DIR"

        REPO_DIR="$(find "$WORK_DIR" -mindepth 1 -maxdepth 1 -type d | head -1)"
        [[ -n "$REPO_SUBDIR" ]] && REPO_DIR="$REPO_DIR/$REPO_SUBDIR"
        if [[ -z "$REPO_DIR" || ! -x "$REPO_DIR/scripts/publish-skill.sh" ]]; then
          echo "publish-skill.sh not found in fetched repository" >&2
          exit 1
        fi

        exec "$REPO_DIR/scripts/publish-skill.sh"
        """
    )


def render_publish_local(spec: dict) -> str:
    slug = spec["project_slug"]
    release_path = spec.get("release_path", f"{slug}/release")
    generate_cli = spec.get("generate_cli", True)
    upload_steps = []
    echo_steps = []
    if generate_cli:
        upload_steps.append(
            f'"$ROOT_DIR/scripts/upload-file.sh" --file "$ROOT_DIR/skills/{slug}/scripts/run.sh" --name "${{SKILL_NAME}}.sh" >/dev/null'
        )
        echo_steps.append(
            f'echo "CLI_COMMAND=bash <(curl -fsSL https://skill.vyibc.com/${{SKILL_NAME}}.sh) {spec.get("default_cli_args", "").strip()}"'
        )
    if spec.get("includes_agent"):
        upload_steps.append(
            f'"$ROOT_DIR/scripts/upload-file.sh" --file "$ROOT_DIR/skills/{slug}/agent/agent.js" --name "agent.js" >/dev/null'
        )
    upload_block = "\n".join(upload_steps)
    echo_block = "\n".join(echo_steps)
    return textwrap.dedent(
        f"""\
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)"
SKILL_NAME="{slug}"
WORK_DIR="$(mktemp -d /tmp/{slug}-skill-XXXXXX)"
trap 'rm -rf "$WORK_DIR"' EXIT
TS="$(date +%Y%m%d%H%M%S)"
RELEASE_PATH="{release_path}"
PUBLISH_SKILL_INSTALL_URL="${{PUBLISH_SKILL_INSTALL_URL:-https://skill.vyibc.com/install-publish-skill.sh}}"

cp -R "$ROOT_DIR/skills/$SKILL_NAME" "$WORK_DIR/$SKILL_NAME"

ZIP_FILE="$WORK_DIR/${{SKILL_NAME}}-${{TS}}.zip"
python3 - "$WORK_DIR" "$SKILL_NAME" "$ZIP_FILE" <<'PY'
import os
import sys
import zipfile

root = sys.argv[1]
skill = sys.argv[2]
zip_path = sys.argv[3]
base = os.path.join(root, skill)
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
    for current, _, files in os.walk(base):
        for name in files:
            path = os.path.join(current, name)
            arc = os.path.relpath(path, root)
            z.write(path, arc)
PY

ZIP_JSON="$("$ROOT_DIR/scripts/upload-file.sh" --file "$ZIP_FILE" --name "${{SKILL_NAME}}-${{TS}}.zip" --path "$RELEASE_PATH")"
ZIP_URL="$(printf '%s' "$ZIP_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("image_url",""))')"
ZIP_URL_TS="${{ZIP_URL}}?ts=${{TS}}"

INSTALL_SCRIPT="$WORK_DIR/install-${{SKILL_NAME}}.sh"
PUBLISH_TEMPLATE="$WORK_DIR/install-publish-skill.sh"
curl -fsSL "$PUBLISH_SKILL_INSTALL_URL" -o "$PUBLISH_TEMPLATE"

python3 - "$PUBLISH_TEMPLATE" "$INSTALL_SCRIPT" "$SKILL_NAME" "$ZIP_URL_TS" <<'PY'
import pathlib
import re
import sys

src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])
skill_name = sys.argv[3]
zip_url = sys.argv[4]
text = src.read_text()
text = re.sub(r'^SKILL_NAME="[^"]*"$', f'SKILL_NAME="{{skill_name}}"', text, flags=re.M)
text = re.sub(r'^ZIP_URL="[^"]*"$', f'ZIP_URL="{{zip_url}}"', text, flags=re.M)
text = re.sub(r'^(# Auto-generated one-click install script for: ).*$', rf'\\1{{skill_name}}', text, flags=re.M)
dst.write_text(text)
PY

chmod +x "$INSTALL_SCRIPT"

"$ROOT_DIR/scripts/upload-file.sh" --file "$INSTALL_SCRIPT" --name "install-${{SKILL_NAME}}.sh" >/dev/null
{upload_block}
echo "SKILL_INSTALL_COMMAND=bash <(curl -fsSL 'https://skill.vyibc.com/install-${{SKILL_NAME}}.sh?ts=${{TS}}')"
{echo_block}
        """
    ).rstrip() + "\n"


def render_skill_md(spec: dict) -> str:
    slug = spec["project_slug"]
    summary = spec["summary"]
    trigger_phrases = spec.get("trigger_phrases", [slug, f"调用 {slug}", f"使用 {slug}"])
    trigger_str = "、".join(f'"{p}"' for p in trigger_phrases)
    skill_description = spec.get("skill_description", f"当用户说{trigger_str} 时自动触发。{summary}")
    cli_example = spec.get("cli_example", f"bash <(curl -fsSL https://skill.vyibc.com/{slug}.sh)")
    default_args = spec.get("default_cli_args", "").strip()

    modes = spec.get("request_modes", [])
    param_rows = ""
    for mode in modes:
        for field in mode.get("fields", []):
            param_rows += f"| `--{field['name'].replace('_', '-')}` | 否 | {mode.get('description', '').strip()} |\n"
    params_section = ""
    if param_rows:
        params_section = f"""\
## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--mode` | 是 | 调用模式，可选值：{', '.join('`' + m['name'] + '`' for m in modes)} |
{param_rows}
"""

    cli_section = ""
    if spec.get("generate_cli", True):
        cli_section = f"""\
## 直接执行

```bash
{cli_example}
```

"""

    return f"""\
---
name: {slug}
description: "{skill_description}"
---

# {spec.get("display_name", slug_to_title(slug))}

## 作用

{summary}

## 执行

```bash
~/.claude/skills/{slug}/scripts/run.sh {default_args}
```

{params_section}{cli_section}"""


def render_readme(spec: dict) -> str:
    slug = spec["project_slug"]
    generate_cli = spec.get("generate_cli", True)
    summary = spec["summary"]
    default_args = spec.get("default_cli_args", "").strip()
    trigger_phrases = spec.get("trigger_phrases", [slug, f"调用 {slug}", f"使用 {slug}"])

    mode_table = "| 模式 | 说明 |\n|------|------|\n"
    mode_table += "\n".join(
        f"| `{mode['name']}` | {mode.get('description', '').strip()} |"
        for mode in spec["request_modes"]
    )

    examples_blocks = []
    for example in spec.get("examples", []):
        examples_blocks.append(f"### {example['label']}\n\n```bash\n{example['command']}\n```")
    examples_text = "\n\n".join(examples_blocks) if examples_blocks else "暂无示例。"

    trigger_list = "\n".join(f"- `{p}`" for p in trigger_phrases)

    cli_section = ""
    if generate_cli:
        cli_section = f"""\

---

## 1. 直接执行 CLI

不需要安装 skill，一条命令直接调用：

```bash
bash <(curl -fsSL https://skill.vyibc.com/{slug}.sh) {default_args}
```
"""

    domain_name = spec.get("domain_name", spec.get("auto_domain_name", spec["project_slug"]))
    source_extra = ""
    if spec["source_kind"] == "local_port":
        source_extra = f"""
---

## 本地服务说明

本 skill 通过 auto-domain 隧道调用本地服务，公网地址固定为：

```
https://{domain_name}.chxyka.ccwu.cc
```

调用前请先在本地启动服务，并运行 auto-domain 将端口打洞到公网：

```bash
bash <(curl -fsSL https://skill.vyibc.com/auto-domain.sh) --port=PORT --name={domain_name} --daemon
```

Skill 本身不需要任何 `--port` 或 `--domain-name` 参数，直接 `--mode=...` 调用即可。
"""
    elif spec["source_kind"] == "script_service":
        source_extra = f"""
---

## 本地脚本服务说明

本 skill 将本地 shell 脚本包装成 HTTP 服务，再通过 auto-domain 暴露到公网。

**在服务所在机器上，按顺序执行：**

```bash
# 1. 启动本地 HTTP bridge（包装 scripts/local-script.sh）
./scripts/start-local-service.sh --port={spec.get('local_port', 18789)} --daemon

# 2. 用 auto-domain 打洞到公网
bash <(curl -fsSL https://skill.vyibc.com/auto-domain.sh) --port={spec.get('local_port', 18789)} --name={domain_name} --daemon
```

之后在任何地方执行 skill，都会调用到这台机器上的本地脚本：

```bash
bash <(curl -fsSL https://skill.vyibc.com/{slug}.sh) --mode=...
```

- `scripts/local-script.sh` — 本地重量级脚本，编辑此文件实现业务逻辑
- `scripts/bridge.py` — Python HTTP bridge，无需修改
- `scripts/start-local-service.sh` — bridge 启动脚本
"""

    struct_extra = ""
    if spec["source_kind"] == "script_service":
        struct_extra = "  start-local-service.sh      # 启动本地脚本服务\n  "

    return f"""\
# {slug}

{summary}
{cli_section}
---

## 2. 安装为 Claude Code Skill

```bash
bash <(curl -fsSL 'https://skill.vyibc.com/install-{slug}.sh')
```

安装后 skill 会写入：

- `~/.claude/skills/{slug}/SKILL.md`
- `~/.claude/skills/{slug}/scripts/run.sh`

### 安装完成后如何使用

对 Claude 说以下任意一句，skill 会自动触发：

{trigger_list}

---

## 3. 支持的调用模式

{mode_table}
{source_extra}
---

## 4. 调用示例

{examples_text}

---

## 5. 发布

本地发布（需在仓库目录下）：

```bash
./scripts/publish-skill.sh
```

从 GitHub `main` 远程发布：

```bash
bash <(curl -fsSL https://skill.vyibc.com/publish-{slug}.sh)
```

---

## 6. 仓库结构

```text
README.md
scripts/
  {slug}.sh                    # CLI 直接执行入口
  {struct_extra}publish-{slug}.sh             # 远程一键发布
  publish-skill.sh             # 本地发布
  upload-file.sh               # R2 上传工具
skills/
  {slug}/
    SKILL.md                   # Claude Code skill 定义
    scripts/run.sh             # 唯一核心执行逻辑
```

`scripts/{slug}.sh` 和安装后的 `skills/{slug}/scripts/run.sh` 来自同一份脚本。
"""


def render_wrapper(slug: str) -> str:
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail

        ROOT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)"
        exec "$ROOT_DIR/skills/{slug}/scripts/run.sh" "$@"
        """
    )


def render_public_run(spec: dict) -> str:
    return render_http_run(spec, endpoint_expression=shell_quote(spec["endpoint"]), source_header="# public API source")


DEFAULT_AUTO_DOMAIN_TOKEN = "atd-76631b52126234666e0a12c6f45ac6d8"


def render_local_port_run(spec: dict) -> str:
    path = spec.get("path", "")
    domain_name = spec.get("domain_name", spec.get("auto_domain_name", spec["project_slug"]))
    endpoint = f"https://{domain_name}.chxyka.ccwu.cc{path}"
    return render_http_run(spec, endpoint_expression=shell_quote(endpoint), source_header="# local port source (auto-domain tunnel)")


def render_script_service_run(spec: dict) -> str:
    path = spec.get("path", "")
    domain_name = spec.get("domain_name", spec.get("auto_domain_name", spec["project_slug"]))
    endpoint = f"https://{domain_name}.chxyka.ccwu.cc{path}"
    return render_http_run(
        spec,
        endpoint_expression=shell_quote(endpoint),
        source_header="# script service source (auto-domain tunnel)",
        include_mode=True,
    )


def render_http_run(spec: dict, endpoint_expression: str, source_header: str, extra_setup: str = "", extra_parse: str = "", pre_call: str = "", include_mode: bool = False) -> str:
    slug = spec["project_slug"]
    auth = spec.get("auth", {})
    token_env = auth.get("token_env", f"{mode_var(slug)}_TOKEN")
    default_token = auth.get("default_token", "")
    modes = spec["request_modes"]

    unique_fields: list[str] = []
    for mode in modes:
        for field in mode.get("fields", []):
            if field["name"] not in unique_fields:
                unique_fields.append(field["name"])

    # auto-detect mode blocks — skip modes with no fields (can't infer them)
    auto_mode_lines: list[str] = []
    for mode in modes:
        field_names = [f["name"] for f in mode.get("fields", [])]
        if not field_names:
            continue
        cond = " && ".join(f'[[ -n "${{{mode_var(n)}}}" ]]' for n in field_names)
        auto_mode_lines += [
            f'if [[ -z "$MODE" ]] && {cond}; then',
            f'  MODE="{mode["name"]}"',
            "fi",
        ]

    # payload builder (flat JSON from --field flags), shared by json/async modes
    def _payload_line(field_names, data_init):
        env_assign = " ".join(f'{mode_var(n)}="${{{mode_var(n)}}}"' for n in field_names)
        keys_expr = json.dumps(field_names)
        return (
            f"  PAYLOAD=$({env_assign} python3 -c 'import json, os; keys = {keys_expr}; "
            f"data = {data_init}; [data.__setitem__(key, os.environ.get(key.upper().replace(\"-\", \"_\").replace(\".\", \"_\")) "
            f"or os.environ.get(key.upper().replace(\"-\", \"_\"))) for key in keys "
            f"if (os.environ.get(key.upper().replace(\"-\", \"_\").replace(\".\", \"_\")) "
            f"or os.environ.get(key.upper().replace(\"-\", \"_\")))]; print(json.dumps(data))')"
        )

    # mode case blocks — each mode may carry its own `path` (multi-path workers)
    # and may use transport "async" (POST -> poll GET until done).
    mode_case_lines: list[str] = []
    for mode in modes:
        field_names = [f["name"] for f in mode.get("fields", [])]
        mode_path = mode.get("path", "")
        mode_url = '"$ENDPOINT"' if not mode_path else f'"${{ENDPOINT}}{mode_path}"'
        transport = mode.get("transport", "json")
        data_init = f'{{"mode": "{mode["name"]}"}}' if include_mode else '{}'
        mode_case_lines.append(f'{mode["name"]})')
        if transport == "async":
            poll_path = mode.get("poll_path", "/{id}")
            id_field = mode.get("id_field", "id")
            status_field = mode.get("status_field", "status")
            output_field = mode.get("output_field", "output")
            done_values = mode.get("done_values", ["complete", "completed", "success", "succeeded"])
            error_values = mode.get("error_values", ["errored", "terminated", "failed", "error"])
            interval = int(mode.get("poll_interval", 3))
            max_polls = int(mode.get("max_polls", 80))
            poll_url = f'"${{ENDPOINT}}{poll_path.replace("{id}", "$ASYNC_ID")}"'
            done_pat = "|".join(done_values)
            err_pat = "|".join(error_values)
            mode_case_lines.append(_payload_line(field_names, data_init))
            mode_case_lines.append(
                f'  SUBMIT=$(curl --connect-timeout 10 --max-time 60 --fail-with-body -sS -L {mode_url}'
                ' ${COMMON_HEADERS[@]+"${COMMON_HEADERS[@]}"}'
                ' -H "Content-Type: application/json" -d "$PAYLOAD")'
            )
            mode_case_lines.append(
                "  ASYNC_ID=$(printf '%s' \"$SUBMIT\" | python3 -c "
                f"\"import json,sys; print(json.load(sys.stdin).get('{id_field}',''))\" 2>/dev/null)"
            )
            mode_case_lines.append('  if [[ -z "$ASYNC_ID" ]]; then echo "submit failed: $SUBMIT" >&2; exit 1; fi')
            mode_case_lines.append('  echo "submitted id=$ASYNC_ID, polling..." >&2')
            mode_case_lines.append(f'  for _i in $(seq 1 {max_polls}); do')
            mode_case_lines.append(f'    sleep {interval}')
            mode_case_lines.append(
                f'    RESP=$(curl --connect-timeout 10 --max-time 60 -sS -L {poll_url}'
                ' ${COMMON_HEADERS[@]+"${COMMON_HEADERS[@]}"})'
            )
            mode_case_lines.append(
                "    ST=$(printf '%s' \"$RESP\" | python3 -c "
                f"\"import json,sys; print(json.load(sys.stdin).get('{status_field}',''))\" 2>/dev/null)"
            )
            mode_case_lines.append('    echo "  status=$ST" >&2')
            mode_case_lines.append('    case "$ST" in')
            mode_case_lines.append(
                f"      {done_pat}) printf '%s' \"$RESP\" | python3 -c "
                f"\"import json,sys; d=json.load(sys.stdin); o=d.get('{output_field}'); "
                "print(json.dumps(o,ensure_ascii=False,indent=2) if o is not None else json.dumps(d,ensure_ascii=False,indent=2))\""
                "; exit 0 ;;"
            )
            mode_case_lines.append(f'      {err_pat}) echo "task failed: $RESP" >&2; exit 1 ;;')
            mode_case_lines.append('    esac')
            mode_case_lines.append('  done')
            mode_case_lines.append('  echo "timeout waiting for $ASYNC_ID" >&2; exit 1')
        elif transport == "json":
            mode_case_lines.append(_payload_line(field_names, data_init))
            mode_case_lines.append(
                f'  curl --connect-timeout 10 --max-time 60 --fail-with-body -sS -L {mode_url}'
                ' ${COMMON_HEADERS[@]+"${COMMON_HEADERS[@]}"}'
                ' -H "Content-Type: application/json" -d "$PAYLOAD"'
            )
        else:
            mode_case_lines.append(
                f'  curl --connect-timeout 10 --max-time 60 --fail-with-body -sS -L {mode_url}'
                ' ${COMMON_HEADERS[@]+"${COMMON_HEADERS[@]}"} \\'
            )
            for field in mode.get("fields", []):
                vname = mode_var(field["name"])
                if field.get("file"):
                    mode_case_lines.append(f'    -F "{field["name"]}=@${{{vname}}}" \\')
                else:
                    mode_case_lines.append(f'    -F "{field["name"]}=${{{vname}}}" \\')
            mode_case_lines.append("    | cat")
        mode_case_lines.append("  ;;")

    lines: list[str] = [
        "#!/usr/bin/env bash",
        source_header,
        "set -euo pipefail",
        "",
        'MODE=""',
        f'TOKEN="${{{token_env}:-{default_token}}}"',
        'ENDPOINT_OVERRIDE=""',
    ]
    for name in unique_fields:
        lines.append(f'{mode_var(name)}=""')
    if extra_setup.strip():
        lines.extend(extra_setup.strip().splitlines())
    lines += [
        "",
        'for arg in "$@"; do',
        '  case "$arg" in',
        '    --mode=*) MODE="${arg#--mode=}" ;;',
        '    --token=*) TOKEN="${arg#--token=}" ;;',
        '    --endpoint=*) ENDPOINT_OVERRIDE="${arg#--endpoint=}" ;;',
    ]
    if extra_parse.strip():
        for ln in extra_parse.strip().splitlines():
            lines.append("    " + ln.strip())
    for name in unique_fields:
        flag = name.replace("_", "-")
        lines.append(f'    --{flag}=*) {mode_var(name)}="${{arg#--{flag}=}}" ;;')
    lines += [
        '    -h|--help)',
        '      echo "Usage: $0 --mode=<mode> [--token=TOKEN] [--endpoint=URL]"',
        "      exit 0",
        "      ;;",
        "  esac",
        "done",
        "",
    ]
    if auto_mode_lines:
        lines.extend(auto_mode_lines)
        lines.append("")
    lines += [
        'if [[ -z "$MODE" ]]; then',
        '  echo "Provide --mode or enough fields to infer one" >&2',
        "  exit 1",
        "fi",
        "",
    ]
    if pre_call.strip():
        lines.extend(pre_call.strip().splitlines())
        lines.append("")
    lines += [
        'TOKEN="${TOKEN#Bearer }"',
        'TOKEN="${TOKEN#bearer }"',
        "",
        f"ENDPOINT={endpoint_expression}",
        'if [[ -n "$ENDPOINT_OVERRIDE" ]]; then',
        '  ENDPOINT="$ENDPOINT_OVERRIDE"',
        "fi",
        "",
        "COMMON_HEADERS=()",
        'if [[ -n "$TOKEN" ]]; then',
        '  COMMON_HEADERS+=(-H "Authorization: Bearer $TOKEN")',
        "fi",
        "",
        f'echo "Calling {slug}..." >&2',
        "",
        'case "$MODE" in',
    ]
    lines.extend(mode_case_lines)
    lines += [
        '  *)',
        '    echo "Unsupported mode: $MODE" >&2',
        "    exit 1",
        "    ;;",
        "esac",
    ]
    return "\n".join(lines) + "\n"


def render_bridge_py() -> str:
    return """\
import http.server
import json
import os
import subprocess

PORT = int(os.environ.get('BRIDGE_PORT', '18789'))
SCRIPT = os.environ.get('BRIDGE_SCRIPT', '')


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'ok')

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        try:
            data = json.loads(self.rfile.read(length)) if length else {}
        except Exception:
            data = {}

        env = {**os.environ}
        for k, v in data.items():
            env[k.upper().replace('-', '_').replace('.', '_')] = str(v)

        r = subprocess.run(
            ['bash', '-l', SCRIPT],
            env=env,
            capture_output=True,
            text=True,
        )

        out = r.stdout.encode()
        self.send_response(200 if r.returncode == 0 else 500)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *_):
        pass


print(f'[bridge] 127.0.0.1:{PORT}', flush=True)
http.server.HTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
"""


def render_local_script(spec: dict) -> str:
    shell = spec.get("bootstrap", {}).get("shell", 'echo "no script configured"')
    return f"#!/usr/bin/env bash\n# Local heavy script — edit this file to implement your logic\n{shell}\n"


def render_start_local_service(spec: dict) -> str:
    slug = spec["project_slug"]
    local_port = str(spec.get("local_port", 18789))
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        f'PORT="{local_port}"',
        'DAEMON=0',
        f'PID_FILE="$HOME/.{slug}-bridge.pid"',
        f'LOG_FILE="$HOME/.{slug}-bridge.log"',
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        "",
        "while [[ $# -gt 0 ]]; do",
        '  case "$1" in',
        '    --port=*) PORT="${1#--port=}"; shift ;;',
        "    --daemon) DAEMON=1; shift ;;",
        "    --stop)",
        f'      if [[ -f "$HOME/.{slug}-bridge.pid" ]] && kill -0 "$(cat "$HOME/.{slug}-bridge.pid")" 2>/dev/null; then',
        f'        kill "$(cat "$HOME/.{slug}-bridge.pid")"; rm -f "$HOME/.{slug}-bridge.pid"',
        '        echo "Bridge stopped."',
        "      else",
        '        echo "No bridge running."',
        "      fi",
        "      exit 0",
        "      ;;",
        '    *) echo "unknown: $1" >&2; exit 1 ;;',
        "  esac",
        "done",
        "",
        'BRIDGE_PY="$SCRIPT_DIR/bridge.py"',
        'LOCAL_SCRIPT="$SCRIPT_DIR/local-script.sh"',
        "",
        'if [[ ! -f "$BRIDGE_PY" ]]; then',
        '  echo "bridge.py not found at $BRIDGE_PY" >&2; exit 1',
        "fi",
        'if [[ ! -f "$LOCAL_SCRIPT" ]]; then',
        '  echo "local-script.sh not found at $LOCAL_SCRIPT" >&2; exit 1',
        "fi",
        "",
        "export BRIDGE_PORT BRIDGE_SCRIPT BRIDGE_PY_FILE",
        'BRIDGE_PORT="$PORT"',
        'BRIDGE_SCRIPT="$LOCAL_SCRIPT"',
        'BRIDGE_PY_FILE="$BRIDGE_PY"',
        "",
        'if [[ "$DAEMON" == "1" ]]; then',
        '  > "$LOG_FILE"',
        "  nohup bash -lc 'python3 \"$BRIDGE_PY_FILE\"' >> \"$LOG_FILE\" 2>&1 &",
        '  echo $! > "$PID_FILE"',
        '  echo "Bridge started on port $PORT (PID: $(cat "$PID_FILE"))"',
        '  echo "  Logs : tail -f $LOG_FILE"',
        "  for i in $(seq 1 20); do",
        '    if curl -sf -X GET "http://127.0.0.1:$PORT" -o /dev/null 2>&1; then',
        '      echo "  Ready: http://127.0.0.1:$PORT"',
        "      break",
        "    fi",
        "    sleep 0.5",
        "  done",
        "else",
        "  exec bash -lc 'python3 \"$BRIDGE_PY_FILE\"'",
        "fi",
    ]
    return "\n".join(lines) + "\n"


CF_WORKER_PREFIX = "auto-api-"
# Read from env so different CF accounts work correctly.
# Set CF_WORKERS_SUBDOMAIN in ~/.agent-brain-plugins.env (see .env.example).
CF_WORKERS_SUBDOMAIN = os.environ.get("CF_WORKERS_SUBDOMAIN", "hb67egcim4")


def worker_name(slug: str) -> str:
    return f"{CF_WORKER_PREFIX}{slug}"


def worker_url(slug: str) -> str:
    return f"https://{worker_name(slug)}.{CF_WORKERS_SUBDOMAIN}.workers.dev"


def render_worker_js(spec: dict) -> str:
    code = spec.get("worker_code", "")
    if code:
        return code if code.strip().startswith("export default") else f"export default {{\n  async fetch(request, env) {{\n    {code}\n  }}\n}};\n"
    # default hello worker
    return """\
export default {
  async fetch(request, env) {
    let body = {};
    try { body = await request.json(); } catch (_) {}
    return Response.json({ ok: true, received: body });
  },
};
"""


def render_wrangler_toml(spec: dict) -> str:
    slug = spec["project_slug"]
    name = worker_name(slug)
    lines = [
        f'name = "{name}"',
        'main = "src/worker.js"',
        'compatibility_date = "2024-11-01"',
        'compatibility_flags = ["nodejs_compat"]',
    ]
    return "\n".join(lines) + "\n"


def render_deploy_worker_sh(spec: dict) -> str:
    slug = spec["project_slug"]
    name = worker_name(slug)
    url = worker_url(slug)
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        'WORKER_DIR="$(cd "$SCRIPT_DIR/../worker" && pwd)"',
        "",
        f'CF_EMAIL="${{CF_EMAIL_SKILL:-{spec.get("cf_email", "go20260310@outlook.com")}}}"',
        f'CF_API_KEY="${{CF_API_KEY_SKILL:-}}"',
        "",
        'if [[ -z "$CF_API_KEY" ]]; then',
        '  echo "CF_API_KEY_SKILL env var required" >&2; exit 1',
        "fi",
        "",
        "echo \"Deploying CF Worker: " + name + "...\"",
        'cd "$WORKER_DIR"',
        "",
        "# install wrangler if needed",
        'if ! command -v wrangler >/dev/null 2>&1 && [[ ! -f node_modules/.bin/wrangler ]]; then',
        "  npm install --silent wrangler",
        "fi",
        "",
        'WRANGLER="${{ command -v wrangler >/dev/null 2>&1 && echo wrangler || echo ./node_modules/.bin/wrangler }}"',
        'WRANGLER="$(command -v wrangler 2>/dev/null || echo ./node_modules/.bin/wrangler)"',
        "",
        'CLOUDFLARE_EMAIL="$CF_EMAIL" CLOUDFLARE_API_KEY="$CF_API_KEY" \\',
        '  "$WRANGLER" deploy --config wrangler.toml 2>&1',
        "",
        "echo \"\"",
        f'echo "Worker deployed: {url}"',
    ]
    return "\n".join(lines) + "\n"


def render_cloudflare_worker_run(spec: dict) -> str:
    url = worker_url(spec["project_slug"])
    return render_http_run(spec, endpoint_expression=shell_quote(url), source_header="# cloudflare worker source")


def render_gitignore() -> str:
    return textwrap.dedent(
        """\
        .DS_Store
        node_modules/
        worker/node_modules/
        .wrangler/
        .auto-domain/
        *.log
        *.pid
        """
    )


def render_generated_project(spec: dict, out_dir: pathlib.Path) -> None:
    slug = spec["project_slug"]
    repo_name = spec["repo_name"]
    write(out_dir / "README.md", render_readme(spec))
    write(out_dir / ".gitignore", render_gitignore())
    if spec.get("generate_cli", True):
        write(out_dir / "scripts" / f"{slug}.sh", render_wrapper(slug), executable=True)
    write(out_dir / "scripts" / f"publish-{slug}.sh", render_publish_remote(repo_name, spec.get("repo_subdir", "")), executable=True)
    write(out_dir / "scripts" / "publish-skill.sh", render_publish_local(spec), executable=True)
    write(out_dir / "scripts" / "upload-file.sh", render_upload_file(), executable=True)
    write(out_dir / "skills" / slug / "SKILL.md", render_skill_md(spec))

    if spec["source_kind"] == "public_api":
        run_script = render_public_run(spec)
    elif spec["source_kind"] == "local_port":
        run_script = render_local_port_run(spec)
    elif spec["source_kind"] == "script_service":
        run_script = render_script_service_run(spec)
        write(out_dir / "scripts" / "start-local-service.sh", render_start_local_service(spec), executable=True)
        write(out_dir / "scripts" / "bridge.py", render_bridge_py())
        write(out_dir / "scripts" / "local-script.sh", render_local_script(spec), executable=True)
    elif spec["source_kind"] == "cloudflare_worker":
        run_script = render_cloudflare_worker_run(spec)
        write(out_dir / "worker" / "src" / "worker.js", render_worker_js(spec))
        write(out_dir / "worker" / "wrangler.toml", render_wrangler_toml(spec))
        write(out_dir / "scripts" / "deploy-worker.sh", render_deploy_worker_sh(spec), executable=True)
    else:
        raise SystemExit(f"unsupported source_kind: {spec['source_kind']}")

    write(out_dir / "skills" / slug / "scripts" / "run.sh", run_script, executable=True)


def create_remote_repo(repo_dir: pathlib.Path, repo_name: str, owner: str, token: str) -> None:
    payload = json.dumps({"name": repo_name, "private": False}).encode()
    request = urllib.request.Request(
        "https://api.github.com/user/repos",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        if exc.code == 422 and "name already exists" in detail:
            body = {"html_url": f"https://github.com/{owner}/{repo_name}"}
        else:
            raise SystemExit(f"failed to create repo: {exc.code} {detail}") from exc

    remote_url = body.get("html_url", f"https://github.com/{owner}/{repo_name}")
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", owner], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "go20260310@outlook.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Initial generated project"], cwd=repo_dir, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", f"https://oauth2:{token}@github.com/{owner}/{repo_name}.git"],
        cwd=repo_dir,
        check=True,
    )
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo_dir, check=True)
    subprocess.run(
        ["git", "remote", "set-url", "origin", f"https://github.com/{owner}/{repo_name}.git"],
        cwd=repo_dir,
        check=True,
    )
    print(f"GITHUB_REPO={remote_url}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--github-owner")
    parser.add_argument("--github-token")
    parser.add_argument("--create-remote", action="store_true")
    args = parser.parse_args()

    spec_path = pathlib.Path(args.spec)
    out_dir = pathlib.Path(args.out)
    spec = json.loads(spec_path.read_text())
    ensure_required(spec, ["project_slug", "repo_name", "summary", "source_kind", "request_modes"])

    if out_dir.exists():
        raise SystemExit(f"output directory already exists: {out_dir}")

    render_generated_project(spec, out_dir)

    print(f"GENERATED_PROJECT={out_dir}")
    print(f"SKILL_NAME={spec['project_slug']}")

    if args.create_remote:
        if not args.github_owner or not args.github_token:
            raise SystemExit("--create-remote requires --github-owner and --github-token")
        create_remote_repo(out_dir, spec["repo_name"], args.github_owner, args.github_token)


if __name__ == "__main__":
    main()
