# auto-api-to-skill-cli

把任意 API、脚本或本地服务封装成可分发的 Claude Code skill。

这个项目本身就是一个 skill —— 安装到 Claude Code 后，Claude 就具备了"把接口/脚本生成新 skill"的能力。

---

## 安装

```bash
bash <(curl -fsSL 'https://skill.vyibc.com/install-auto-api-to-skill.sh')
```

安装后，对 Claude 说：

- "帮我把这个 API 封装成 skill"
- "把这个本地脚本发布成 skill"
- "生成一个 skill 项目"

Claude 会自动判断来源类型、构建 spec、生成项目并发布。

---

## 四种来源（source_kind）

### Case 1: `cloudflare_worker` — 轻量逻辑 → CF Worker → 全球公网

适用：逻辑简单，无本地环境依赖，可以在 Cloudflare V8 环境运行。

```
CF Worker JS → wrangler 部署 → https://auto-api-{slug}.workers.dev → skill
```

示例 spec: [examples/case1-cloudflare-worker/spec.json](examples/case1-cloudflare-worker/spec.json)

---

### Case 2: `script_service` — 重量级本地脚本 → HTTP bridge → auto-domain

适用：脚本依赖本机私有环境（nvm、conda、本地文件等），无法部署到云端。

```
local-script.sh → Python HTTP bridge → auto-domain → 公网 URL → skill
```

示例 spec: [examples/case2-script-service/spec.json](examples/case2-script-service/spec.json)

---

### Case 3: `local_port` — 本地 HTTP 服务 → auto-domain

适用：本机已有运行中的 HTTP 服务，直接打洞暴露公网。

```
本地 HTTP 服务 → auto-domain → 公网 URL → skill
```

示例 spec: [examples/case3-local-port/spec.json](examples/case3-local-port/spec.json)

---

### Case 4: `public_api` — 已有公网 API

适用：接口已在公网，直接包装成 skill。

```
公网 HTTP 接口 → skill（直接 curl）
```

示例 spec: [examples/case4-public-api/spec.json](examples/case4-public-api/spec.json)

---

## Claude 的生成流程

1. 根据用户描述判断 source_kind
2. 构建 spec.json
3. 调用 skill 的 `run.sh` 生成项目
4. Case 1 额外：部署 CF Worker
5. Case 2/3 额外：服务机启动 bridge + auto-domain
6. 发布 skill 到 R2
7. 输出安装命令

---

## spec.json 字段说明

### 必填

| 字段 | 说明 |
|---|---|
| `project_slug` | 项目标识（小写连字符），同时作为 skill 名 |
| `repo_name` | GitHub 仓库名 |
| `summary` | 一句话描述 |
| `source_kind` | `cloudflare_worker` / `script_service` / `local_port` / `public_api` |
| `request_modes` | 调用模式列表 |

### request_modes 格式

```json
{
  "request_modes": [
    {
      "name": "run",
      "transport": "json",
      "description": "模式说明",
      "fields": [
        {"name": "input", "description": "输入内容"}
      ]
    }
  ]
}
```

### 可选字段

| 字段 | 说明 |
|---|---|
| `trigger_phrases` | Claude 触发词列表 |
| `examples` | 示例命令 |
| `auth.token_env` | token 环境变量名 |
| `auth.default_token` | 默认 token |

---

## 已生成的示例项目

| 项目 | source_kind | 仓库 |
|---|---|---|
| greet-cf | `cloudflare_worker` | [auto-greet-cf-skill](https://github.com/ChangfengHU/auto-greet-cf-skill) |
| hello-heavy | `script_service` | [auto-hello-heavy-skill](https://github.com/ChangfengHU/auto-hello-heavy-skill) |
| hello-local | `local_port` | [auto-hello-local-skill](https://github.com/ChangfengHU/auto-hello-local-skill) |
| hello-worker | `public_api` | [auto-hello-worker-skill](https://github.com/ChangfengHU/auto-hello-worker-skill) |

---

## 本地调试（开发者用）

```bash
git clone https://github.com/ChangfengHU/auto-api-to-skill-cli
cd auto-api-to-skill-cli

# 本地跑生成器
python3 scripts/generate-project.py \
  --spec examples/case4-public-api/spec.json \
  --out /tmp/test-out

# 重新发布 skill 自身
./scripts/publish-skill.sh
```
