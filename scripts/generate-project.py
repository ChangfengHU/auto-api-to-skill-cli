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
        API_TOKEN="${UPLOAD_R2_TOKEN:-123456}"

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


def render_publish_remote(repo_name: str) -> str:
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail

        REPO_OWNER="${{REPO_OWNER:-ChangfengHU}}"
        REPO_NAME="${{REPO_NAME:-{repo_name}}}"
        REPO_REF="${{REPO_REF:-main}}"
        TARBALL_URL="${{TARBALL_URL:-https://codeload.github.com/${{REPO_OWNER}}/${{REPO_NAME}}/tar.gz/refs/heads/${{REPO_REF}}}}"

        WORK_DIR="$(mktemp -d /tmp/publish-{repo_name}-XXXXXX)"
        trap 'rm -rf "$WORK_DIR"' EXIT

        echo "Fetching ${{REPO_OWNER}}/${{REPO_NAME}}@${{REPO_REF}} ..."
        curl -fsSL "$TARBALL_URL" -o "$WORK_DIR/repo.tar.gz"
        tar -xzf "$WORK_DIR/repo.tar.gz" -C "$WORK_DIR"

        REPO_DIR="$(find "$WORK_DIR" -mindepth 1 -maxdepth 1 -type d | head -1)"
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
    maybe_cli_upload = ""
    maybe_cli_echo = ""
    maybe_agent_upload = ""
    if generate_cli:
        maybe_cli_upload = f"\"$ROOT_DIR/scripts/upload-file.sh\" --file \"$ROOT_DIR/skills/{slug}/scripts/run.sh\" --name \"${{SKILL_NAME}}.sh\" >/dev/null\n"
        maybe_cli_echo = (
            f'echo "CLI_COMMAND=bash <(curl -fsSL https://skill.vyibc.com/${{SKILL_NAME}}.sh) {spec.get("default_cli_args", "").strip()}"\n'
        )
    if spec.get("includes_agent"):
        maybe_agent_upload = (
            f"\"$ROOT_DIR/scripts/upload-file.sh\" --file \"$ROOT_DIR/skills/{slug}/agent/agent.js\" --name \"agent.js\" >/dev/null\n"
        )
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
        {maybe_cli_upload}{maybe_agent_upload}echo "SKILL_INSTALL_COMMAND=bash <(curl -fsSL 'https://skill.vyibc.com/install-${{SKILL_NAME}}.sh?ts=${{TS}}')"
        {maybe_cli_echo}".rstrip()
        """
    )


def render_skill_md(spec: dict) -> str:
    slug = spec["project_slug"]
    description = spec["summary"]
    cli_example = spec.get("cli_example", f"bash <(curl -fsSL https://skill.vyibc.com/{slug}.sh)")
    cli_block = ""
    if spec.get("generate_cli", True):
        cli_block = textwrap.dedent(
            f"""\
            ## 直接执行

            ```bash
            {cli_example}
            ```
            """
        )
    return textwrap.dedent(
        f"""\
        ---
        name: {slug}
        description: "{description}"
        ---

        # {spec.get("display_name", slug_to_title(slug))}

        ## 作用

        当用户希望把 `{slug}` 作为一个真正的 skill 安装到 agent 环境里，并通过统一参数调用它时，使用这个 skill。

        ## 安装

        ```bash
        bash <(curl -fsSL 'https://skill.vyibc.com/install-{slug}.sh?ts=...')
        ```

        ## 核心执行入口

        ```text
        skills/{slug}/scripts/run.sh
        ```

        安装后的 skill 和对外发布的 CLI 都来自这一个脚本。
        
        {cli_block.rstrip()}
        """
    )


def render_readme(spec: dict) -> str:
    slug = spec["project_slug"]
    generate_cli = spec.get("generate_cli", True)
    mode_lines = "\n".join(
        f"- `{mode['name']}`: {mode.get('description', '').strip()}" for mode in spec["request_modes"]
    )
    examples = []
    for example in spec.get("examples", []):
        examples.append(f"### {example['label']}\n\n```bash\n{example['command']}\n```")
    examples_text = "\n\n".join(examples) if examples else "No examples provided yet."
    extra = ""
    if spec["source_kind"] == "local_port":
        extra = textwrap.dedent(
            f"""
            ## Local Port Source

            This project targets a local HTTP service. It supports:

            - `--base-url=http://127.0.0.1:PORT`
            - or `--port=PORT` to expose the service through `auto-domain` first
            """
        )
    if spec["source_kind"] == "script_service":
        extra = textwrap.dedent(
            f"""
            ## Script Source

            This project wraps a local script-backed service. The generated repository includes:

            - `scripts/start-local-service.sh`
            - `skills/{slug}/scripts/run.sh`

            The runtime can start the local service, call it directly, or expose it through `auto-domain`.
            """
        )

    direct_cli_section = ""
    if generate_cli:
        direct_cli_section = textwrap.dedent(
            f"""\
            ## 1. 直接执行 CLI

            ```bash
            bash <(curl -fsSL https://skill.vyibc.com/{slug}.sh) {spec.get("default_cli_args", "").strip()}
            ```
            """
        )

    return textwrap.dedent(
        f"""\
        # {slug}

        `{slug}` 用来封装 `{spec.get("endpoint", slug)}` 这个能力，对外提供两个主要入口：

- 安装一个真正的 skill 到 agent 环境
- 直接执行 CLI 调用这个 HTTP 接口

{spec["summary"]}

        {direct_cli_section.rstrip()}

        ## 2. 安装 skill

        ```bash
        bash <(curl -fsSL 'https://skill.vyibc.com/install-{slug}.sh?ts=...')
        ```

        这个命令会把 `{slug}` 安装到目标 skill 目录，例如：

- `~/.codex/skills/{slug}`
- `~/.claude/skills/{slug}`
- `~/.cursor/skills/{slug}`

安装完成后，skill 内会包含：

- `SKILL.md`
- `scripts/run.sh`

## 3. 支持的调用模式

        {mode_lines}

        {extra}

        ## 4. 调用示例

        {examples_text}

        ## 5. 发布

        本地发布：

        ```bash
        ./scripts/publish-skill.sh
        ```

        从 GitHub `main` 远程发布：

        ```bash
        bash <(curl -fsSL https://skill.vyibc.com/publish-{slug}.sh)
        ```

        ## 6. 核心执行入口

        ```text
        skills/{slug}/scripts/run.sh
        ```
        """
    )


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


def render_local_port_run(spec: dict) -> str:
    path = spec.get("path", "")
    setup = textwrap.dedent(
        f"""\
        BASE_URL="${{BASE_URL:-}}"
        PORT_OVERRIDE=""
        DOMAIN_NAME="{spec.get('auto_domain_name', spec['project_slug'])}"
        AUTO_DOMAIN_TOKEN="${{AUTO_DOMAIN_TOKEN:-}}"
        """
    )
    parse_extra = textwrap.dedent(
        """\
            --base-url=*) BASE_URL="${arg#--base-url=}" ;;
            --port=*) PORT_OVERRIDE="${arg#--port=}" ;;
            --domain-name=*) DOMAIN_NAME="${arg#--domain-name=}" ;;
            --auto-domain-token=*) AUTO_DOMAIN_TOKEN="${arg#--auto-domain-token=}" ;;
        """
    )
    pre_call = textwrap.dedent(
        f"""\
        if [[ -z "$BASE_URL" ]]; then
          if [[ -z "$PORT_OVERRIDE" ]]; then
            echo "Provide --base-url or --port" >&2
            exit 1
          fi
          AUTO_DOMAIN_CMD=(bash <(curl -fsSL https://skill.vyibc.com/auto-domain.sh) --port="$PORT_OVERRIDE" --name="$DOMAIN_NAME" --daemon)
          if [[ -n "$AUTO_DOMAIN_TOKEN" ]]; then
            AUTO_DOMAIN_CMD+=(--token="$AUTO_DOMAIN_TOKEN")
          fi
          AUTO_DOMAIN_OUTPUT="$("${{AUTO_DOMAIN_CMD[@]}}")"
          echo "$AUTO_DOMAIN_OUTPUT"
          BASE_URL="$(printf '%s\\n' "$AUTO_DOMAIN_OUTPUT" | sed -n 's/.*Public URL : //p' | tail -1)"
          if [[ -z "$BASE_URL" ]]; then
            echo "Failed to allocate public URL through auto-domain" >&2
            exit 1
          fi
        fi

        """
    )
    return render_http_run(spec, endpoint_expression=f'"${{BASE_URL}}{path}"', source_header="# local port source", extra_setup=setup, extra_parse=parse_extra, pre_call=pre_call)


def render_script_service_run(spec: dict) -> str:
    path = spec.get("path", "")
    local_port = str(spec.get("local_port", 18789))
    setup = textwrap.dedent(
        f"""\
        BASE_URL="${{BASE_URL:-}}"
        START_LOCAL=1
        LOCAL_PORT="{local_port}"
        PUBLIC=0
        DOMAIN_NAME="{spec.get('auto_domain_name', spec['project_slug'])}"
        AUTO_DOMAIN_TOKEN="${{AUTO_DOMAIN_TOKEN:-}}"
        SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
        ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
        """
    )
    parse_extra = textwrap.dedent(
        """\
            --base-url=*) BASE_URL="${arg#--base-url=}" ;;
            --local-port=*) LOCAL_PORT="${arg#--local-port=}" ;;
            --public) PUBLIC=1 ;;
            --domain-name=*) DOMAIN_NAME="${arg#--domain-name=}" ;;
            --auto-domain-token=*) AUTO_DOMAIN_TOKEN="${arg#--auto-domain-token=}" ;;
        """
    )
    pre_call = textwrap.dedent(
        f"""\
        if [[ -z "$BASE_URL" ]]; then
          "$ROOT_DIR/scripts/start-local-service.sh" --port="$LOCAL_PORT" --daemon >/dev/null
          sleep 1
          BASE_URL="http://127.0.0.1:${{LOCAL_PORT}}"
        fi

        if [[ "$PUBLIC" == "1" ]]; then
          AUTO_DOMAIN_CMD=(bash <(curl -fsSL https://skill.vyibc.com/auto-domain.sh) --port="$LOCAL_PORT" --name="$DOMAIN_NAME" --daemon)
          if [[ -n "$AUTO_DOMAIN_TOKEN" ]]; then
            AUTO_DOMAIN_CMD+=(--token="$AUTO_DOMAIN_TOKEN")
          fi
          AUTO_DOMAIN_OUTPUT="$("${{AUTO_DOMAIN_CMD[@]}}")"
          echo "$AUTO_DOMAIN_OUTPUT"
          PUBLIC_URL="$(printf '%s\\n' "$AUTO_DOMAIN_OUTPUT" | sed -n 's/.*Public URL : //p' | tail -1)"
          if [[ -n "$PUBLIC_URL" ]]; then
            BASE_URL="$PUBLIC_URL"
          fi
        fi

        """
    )
    return render_http_run(spec, endpoint_expression=f'"${{BASE_URL}}{path}"', source_header="# script service source", extra_setup=setup, extra_parse=parse_extra, pre_call=pre_call)


def render_http_run(spec: dict, endpoint_expression: str, source_header: str, extra_setup: str = "", extra_parse: str = "", pre_call: str = "") -> str:
    slug = spec["project_slug"]
    auth = spec.get("auth", {})
    token_env = auth.get("token_env", f"{mode_var(slug)}_TOKEN")
    default_token = auth.get("default_token", "")
    token_help = auth.get("help", "API token")
    modes = spec["request_modes"]
    unique_fields: list[str] = []
    for mode in modes:
        for field in mode.get("fields", []):
            name = field["name"]
            if name not in unique_fields:
                unique_fields.append(name)

    field_setup = "\n".join(f'{mode_var(name)}=""' for name in unique_fields)
    parse_lines = []
    for name in unique_fields:
        flag = name.replace("_", "-")
        parse_lines.append(f'    --{flag}=*) {mode_var(name)}="${{arg#--{flag}=}}" ;;')
    mode_cases = []
    auto_mode_lines = []
    for mode in modes:
        field_names = [field["name"] for field in mode.get("fields", [])]
        cond = " && ".join(f'[[ -n "${mode_var(name)}" ]]' for name in field_names) or "false"
        auto_mode_lines.append(
            textwrap.dedent(
                f"""\
                if [[ -z "$MODE" ]] && {cond}; then
                  MODE="{mode['name']}"
                fi
                """
            ).rstrip()
        )
        if mode["transport"] == "json":
            env_assign = " ".join(f'{mode_var(name)}="${{{mode_var(name)}}}"' for name in field_names)
            keys_expr = json.dumps(field_names)
            payload = textwrap.dedent(
                f"""\
                PAYLOAD=$({env_assign} python3 -c 'import json, os; keys = {keys_expr}; data = {{}}; [data.__setitem__(key, os.environ.get(key.upper().replace("-", "_").replace(".", "_")) or os.environ.get(key.upper().replace("-", "_"))) for key in keys if (os.environ.get(key.upper().replace("-", "_").replace(".", "_")) or os.environ.get(key.upper().replace("-", "_")))]; print(json.dumps(data))')
                curl -fsSL "$ENDPOINT" "${{COMMON_HEADERS[@]}}" -H "Content-Type: application/json" -d "$PAYLOAD"
                """
            )
        else:
            form_lines = "\n".join(f'      -F "{name}=@${{{mode_var(name)}}}" \\' if field.get("file") else f'      -F "{name}=${{{mode_var(name)}}}" \\' for name, field in [(f["name"], f) for f in mode.get("fields", [])])
            payload = textwrap.dedent(
                f"""\
                  curl -fsSL "$ENDPOINT" "${{COMMON_HEADERS[@]}}" \\
                {form_lines}
                      | cat
                """
            )
        mode_cases.append(
            textwrap.dedent(
                f"""\
                {mode['name']})
                {payload.rstrip()}
                  ;;
                """
            )
        )

    auto_mode_block = "\n".join(auto_mode_lines)

    return textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        {source_header}
        set -euo pipefail

        MODE=""
        TOKEN="${{{token_env}:-{default_token}}}"
        ENDPOINT_OVERRIDE=""
        {field_setup}
        {extra_setup.rstrip()}

        for arg in "$@"; do
          case "$arg" in
            --mode=*) MODE="${{arg#--mode=}}" ;;
            --token=*) TOKEN="${{arg#--token=}}" ;;
            --endpoint=*) ENDPOINT_OVERRIDE="${{arg#--endpoint=}}" ;;
        {textwrap.indent(extra_parse.rstrip(), '    ')}
        {textwrap.indent(chr(10).join(parse_lines), '    ')}
            -h|--help)
              echo "Usage: $0 --mode=<mode> [--token=TOKEN] [--endpoint=URL]"
              exit 0
              ;;
          esac
        done

        {auto_mode_block}

        if [[ -z "$MODE" ]]; then
          echo "Provide --mode or enough fields to infer one" >&2
          exit 1
        fi

        {pre_call.rstrip()}

        ENDPOINT={endpoint_expression}
        if [[ -n "$ENDPOINT_OVERRIDE" ]]; then
          ENDPOINT="$ENDPOINT_OVERRIDE"
        fi

        COMMON_HEADERS=()
        if [[ -n "$TOKEN" ]]; then
          COMMON_HEADERS+=(-H "Authorization: Bearer $TOKEN")
        fi

        case "$MODE" in
        {''.join(mode_cases).rstrip()}
          *)
            echo "Unsupported mode: $MODE" >&2
            exit 1
            ;;
        esac
        """
    )


def render_start_local_service(spec: dict) -> str:
    bootstrap = spec.get("bootstrap", {})
    shell = bootstrap.get("shell", "")
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail

        PORT="{spec.get('local_port', 18789)}"
        DAEMON=0
        PID_FILE="${{HOME}}/.{spec['project_slug']}.pid"
        LOG_FILE="${{HOME}}/.{spec['project_slug']}.log"

        while [[ $# -gt 0 ]]; do
          case "$1" in
            --port=*) PORT="${{1#--port=}}" ; shift ;;
            --daemon) DAEMON=1 ; shift ;;
            *) echo "unknown argument: $1" >&2 ; exit 1 ;;
          esac
        done

      start_service() {{
        export PORT
        {textwrap.indent(shell.rstrip(), '  ')}
      }}

        if [[ "$DAEMON" == "1" ]]; then
          nohup bash -lc "$(declare -f start_service); start_service" >>"$LOG_FILE" 2>&1 &
          echo "$!" > "$PID_FILE"
          echo "Started local service (PID: $(cat "$PID_FILE"))"
          exit 0
        fi

        start_service
        """
    )


def render_gitignore() -> str:
    return textwrap.dedent(
        """\
        .DS_Store
        node_modules/
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
    write(out_dir / "scripts" / f"publish-{slug}.sh", render_publish_remote(repo_name), executable=True)
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
