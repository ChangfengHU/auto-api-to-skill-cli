# auto-api-to-skill-cli

`auto-api-to-skill-cli` is a generator project. It turns an interface spec into a new repository that ships:

- a skill
- an optional direct CLI entry
- a publish script
- a README

It supports three source kinds:

1. `public_api`
2. `local_port`
3. `script_service`

## Generator CLI

Generate a project from a JSON spec:

```bash
./scripts/auto-api-to-skill.sh \
  --spec ./examples/content-recognize/public-api-spec.json \
  --out /root/auto-content-recognize-cli
```

Optional GitHub repo creation and push:

```bash
./scripts/auto-api-to-skill.sh \
  --spec ./examples/content-recognize/public-api-spec.json \
  --out /root/auto-content-recognize-cli \
  --github-owner ChangfengHU \
  --github-token YOUR_GITHUB_TOKEN \
  --create-remote
```

## Source Kinds

### `public_api`

Use when the user already provides a public HTTP endpoint. No `auto-domain` step is needed.

- the generated project always includes a skill
- CLI generation is optional when curl is already simple enough

### `local_port`

Use when the user provides a local service and port. The generated project supports:

- calling the service through `--base-url`
- or exposing a local port through `auto-domain` first

This mode is still service-oriented: the point is to turn a local service into a remote callable capability.

### `script_service`

Use when the user provides a local script instead of an HTTP endpoint. The generated project can include a local bootstrap script, then call the local HTTP bridge and optionally expose it through `auto-domain`.

This mode is execution-oriented: it treats shell logic as the source capability, then gives that capability a standard remote execution path and a skill wrapper.

## Skill

The generator also ships as a skill:

```text
skills/auto-api-to-skill/SKILL.md
```

The intended workflow is:

1. normalize a free-form interface document into a structured spec
2. run the generator CLI
3. validate the generated repository
4. optionally create and push a GitHub repo

## What Gets Tested

The generator is meant to validate three concrete paths:

1. `public_api`: call a real public endpoint
2. `local_port`: call a temporary local HTTP service through the generated runner
3. `script_service`: start a local script-backed service and call it through the generated runner
