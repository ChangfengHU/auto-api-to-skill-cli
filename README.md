# auto-api-to-skill-cli

把一份接口描述（spec.json）生成一个完整的新仓库，产物永远是：

- `skills/<slug>/SKILL.md` — 可安装的 skill
- `skills/<slug>/scripts/run.sh` — 统一执行入口
- `scripts/publish-skill.sh` — 本地发布
- `scripts/publish-<slug>.sh` — 远程一键发布
- `README.md` — 面向使用者的文档
- （可选）`scripts/<slug>.sh` — 直接 CLI 入口

支持三种来源：`public_api` / `local_port` / `script_service`。

---

## 快速开始

```bash
./scripts/auto-api-to-skill.sh \
  --spec ./examples/content-recognize/public-api-spec.json \
  --out /tmp/auto-content-recognize-skill
```

带 GitHub 仓库创建和推送：

```bash
./scripts/auto-api-to-skill.sh \
  --spec ./examples/content-recognize/public-api-spec.json \
  --out /tmp/auto-content-recognize-skill \
  --github-owner ChangfengHU \
  --github-token YOUR_GITHUB_TOKEN \
  --create-remote
```

---

## spec.json 字段说明

所有来源都必须有这几个字段：

| 字段 | 说明 |
|---|---|
| `project_slug` | 项目唯一标识，也是 skill 名和 CLI 文件名 |
| `repo_name` | 生成的 GitHub 仓库名 |
| `display_name` | 对外展示名 |
| `summary` | 一句话描述，进入 SKILL.md 的 description |
| `source_kind` | `public_api` / `local_port` / `script_service` |
| `request_modes` | 支持的调用模式列表 |
| `generate_cli` | 是否生成独立 CLI 脚本（默认 `true`） |

---

## 三种来源

### 1. `public_api`

已有公网 HTTP 接口，直接包装。无需 auto-domain。

额外字段：

| 字段 | 说明 |
|---|---|
| `endpoint` | 公网接口地址 |
| `auth.type` | `bearer` |
| `auth.token_env` | 读取 token 的环境变量名 |
| `auth.default_token` | 默认 token |

示例 spec：[examples/content-recognize/public-api-spec.json](examples/content-recognize/public-api-spec.json)

生成的 `run.sh` 支持：

- `--mode=<mode>` 指定调用模式，或根据已提供字段自动推断
- `--token=TOKEN`（自动去掉 `Bearer ` 前缀）
- `--endpoint=URL` 覆盖默认地址
- curl 连接超时 10s，读取超时 60s
- 调用时打印 `Calling <slug>...` 进度提示

---

### 2. `local_port`

本地已有一个正在运行的 HTTP 服务，需要包装成 skill。

额外字段：

| 字段 | 说明 |
|---|---|
| `path` | 接口路径，如 `/echo` |

示例 spec：[examples/local-echo/local-port-spec.json](examples/local-echo/local-port-spec.json)

生成的 `run.sh` 通过 auto-domain 将本地服务暴露为公网能力，必须提供：

- `--port=PORT` 本地服务监听的端口
- `--domain-name=NAME` 分配的公网子域名
- `--auto-domain-token=TOKEN` auto-domain 认证 token

---

### 3. `script_service`

本地有一段重脚本逻辑，需要先包成本地 HTTP 服务，再按需暴露公网。

额外字段：

| 字段 | 说明 |
|---|---|
| `path` | 接口路径，如 `/run` |
| `local_port` | 本地监听端口 |
| `bootstrap.shell` | 启动本地服务的 shell 代码 |

示例 spec：[examples/script-json/script-service-spec.json](examples/script-json/script-service-spec.json)

额外生成文件：

- `scripts/start-local-service.sh` — 启动本地 HTTP bridge（支持 `--daemon` 后台运行）

生成的 `run.sh` 支持：

- `--base-url=URL` 直接调用（跳过启动步骤）
- 默认自动启动本地服务（`start-local-service.sh --daemon`），调用 `127.0.0.1:<local_port>`
- `--public` + `--domain-name=NAME` + `--auto-domain-token=TOKEN` 同时通过 auto-domain 暴露公网

---

## request_modes 字段说明

每个 mode 可以有多个 fields，transport 支持 `json` 和 `multipart`：

```json
{
  "request_modes": [
    {
      "name": "url",
      "transport": "json",
      "description": "...",
      "fields": [{ "name": "url" }]
    },
    {
      "name": "file",
      "transport": "multipart",
      "fields": [{ "name": "file", "file": true }]
    }
  ]
}
```

生成的 `run.sh` 支持自动推断 mode：不传 `--mode` 时，根据已提供的字段名自动匹配第一个满足条件的 mode。

---

## 内置能力（所有来源通用）

| 能力 | 说明 |
|---|---|
| Bearer 规范化 | `--token='Bearer xxx'` 和 `--token='xxx'` 效果相同 |
| 自动推断 mode | 字段齐了就不用显式传 `--mode` |
| curl 超时 | 连接超时 10s，读取超时 60s，防止卡死 |
| 进度提示 | 调用前打印 `Calling <slug>...` 到 stderr |
| 发布链路 | 本地 `publish-skill.sh` + 远程一键 `publish-<slug>.sh` |

---

## 已有示例

| 示例 | source_kind | spec 文件 |
|---|---|---|
| content-recognize | `public_api` | [examples/content-recognize/public-api-spec.json](examples/content-recognize/public-api-spec.json) |
| local-echo | `local_port` | [examples/local-echo/local-port-spec.json](examples/local-echo/local-port-spec.json) |
| script-json | `script_service` | [examples/script-json/script-service-spec.json](examples/script-json/script-service-spec.json) |

---

## 作为 skill 使用

```text
skills/auto-api-to-skill/SKILL.md
```

workflow：

1. 读取用户提供的接口文档或 curl 示例
2. 归一化成 spec.json
3. 运行生成器 CLI
4. 验证生成结果
5. 可选创建并推送 GitHub 仓库
