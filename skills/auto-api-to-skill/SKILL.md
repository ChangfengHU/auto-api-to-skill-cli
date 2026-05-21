---
name: auto-api-to-skill
description: "把接口说明转换成一个新的 skill+cli 项目；支持公网 API、本地端口服务、脚本服务三种来源，并可选创建 GitHub 仓库。"
---

# Auto API To Skill

## Purpose

Use this skill when the user provides an interface document or curl example and wants a new repository that ships:

- a skill
- an optional direct CLI command
- publish scripts
- a README
- optional GitHub repo creation and push

## Workflow

1. Read the interface document.
2. Normalize it into a structured JSON spec.
3. Try a real request if the user provided an endpoint and token.
4. Run the generator CLI.
5. Validate the generated repository.
6. Optionally create and push a GitHub repo.

## Input Kinds

### Public API

Use when the user already provides a public endpoint. No `auto-domain` step is needed. Always generate a skill; only generate a CLI when the wrapper adds real value.

### Local Port

Use when the user provides a local service and port. The generated project should support exposing the local service through `auto-domain`.

### Script Service

Use when the user provides a local script. The generated project should treat the script as the source capability, optionally wrap it in a local service, and expose it through `auto-domain` when remote access is needed.

## Generator CLI

```bash
./scripts/auto-api-to-skill.sh --spec /path/to/spec.json --out /path/to/output
```

With GitHub repo creation:

```bash
./scripts/auto-api-to-skill.sh \
  --spec /path/to/spec.json \
  --out /path/to/output \
  --github-owner USER \
  --github-token TOKEN \
  --create-remote
```
