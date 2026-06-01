---
name: auto-api-to-skill
description: "当用户想把一个 API、本地脚本、本地服务 或 Cloudflare Worker 封装成可分发的 Claude Code skill 时触发。支持四种来源：cloudflare_worker（轻量逻辑部署到CF）、script_service（重量级本地脚本通过HTTP bridge暴露）、local_port（本地HTTP服务通过auto-domain暴露）、public_api（已有公网接口直接包装）。用户说'帮我做一个skill'、'把这个接口封装成skill'、'生成skill项目'、'发布这个脚本'时触发。"
---

# Auto API To Skill

## 作用

把任意 API 或脚本封装成完整的 Claude Code skill，一键发布到 R2，任何机器都能安装使用。

## 四种来源（source_kind）

### Case 1: `cloudflare_worker` — 轻量逻辑 → CF Worker → 全球公网

**适用场景**: 逻辑简单、无本地环境依赖，可以在 Cloudflare V8 环境运行的代码。

**生成产物**: CF Worker JS 代码 + wrangler 项目 + skill（调用 CF Worker 公网 URL）

**spec 字段**:
```json
{
  "project_slug": "my-skill",
  "repo_name": "auto-my-skill",
  "source_kind": "cloudflare_worker",
  "summary": "一句话描述",
  "worker_code": "export default { async fetch(request) { ... } };",
  "request_modes": [{ "name": "run", "transport": "json", "fields": [...] }]
}
```

**生成后部署 CF Worker**:
```bash
source ~/.agent-brain-plugins.env
cd <output>/  && ./scripts/deploy-worker.sh
```

Worker 名称格式: `auto-api-{slug}`，URL: `https://auto-api-{slug}.hb67egcim4.workers.dev`

**标准参考项目**: `auto-greet-cf-skill` (如 https://github.com/ChangfengHU/auto-xhs-parse-skill)

---

### Case 2: `script_service` — 重量级本地脚本 → HTTP bridge → auto-domain

**适用场景**: 脚本强依赖本机环境（nvm、conda、私有工具、本地文件），无法部署到 CF。

**生成产物**: `scripts/local-script.sh`（本地脚本）+ `scripts/bridge.py`（Python HTTP bridge）+ `scripts/start-local-service.sh` + skill

**spec 字段**:
```json
{
  "project_slug": "my-skill",
  "repo_name": "auto-my-skill",
  "source_kind": "script_service",
  "domain_name": "my-skill",
  "local_port": 18092,
  "summary": "一句话描述",
  "bootstrap": {
    "shell": "echo \"Hello from $(hostname)! Mode=$MODE\""
  },
  "request_modes": [{ "name": "run", "transport": "json", "fields": [...] }]
}
```

**服务机上的前置步骤（一次性）**:
```bash
./scripts/start-local-service.sh --daemon
METADATA='{"cli":"bash <(curl -fsSL https://skill.vyibc.com/{slug}.sh)","install":"bash <(curl -fsSL https://skill.vyibc.com/install-{slug}.sh)"}'
bash <(curl -fsSL https://skill.vyibc.com/auto-domain.sh) --port=<local_port> --name=<domain_name> --metadata="$METADATA" --daemon
```

**标准参考项目**: `auto-hello-heavy-skill` (https://github.com/ChangfengHU/auto-hello-heavy-skill)

---

### Case 3: `local_port` — 本地已有 HTTP 服务 → auto-domain

**适用场景**: 本机已有运行中的 HTTP 服务（任意语言），只需暴露到公网。

**spec 字段**:
```json
{
  "project_slug": "my-skill",
  "repo_name": "auto-my-skill",
  "source_kind": "local_port",
  "domain_name": "my-skill",
  "path": "/",
  "summary": "一句话描述",
  "request_modes": [{ "name": "run", "transport": "json", "fields": [...] }]
}
```

**服务机上的前置步骤（一次性）**:
```bash
METADATA='{"cli":"bash <(curl -fsSL https://skill.vyibc.com/{slug}.sh)","install":"bash <(curl -fsSL https://skill.vyibc.com/install-{slug}.sh)"}'
bash <(curl -fsSL https://skill.vyibc.com/auto-domain.sh) --port=<port> --name=<domain_name> --metadata="$METADATA" --daemon
```

**标准参考项目**: `auto-hello-local-skill` (https://github.com/ChangfengHU/auto-hello-local-skill)

---

### Case 4: `public_api` — 已有公网 API → 直接包装

**适用场景**: 接口已在公网，直接调用即可。

**spec 字段**:
```json
{
  "project_slug": "my-skill",
  "repo_name": "auto-my-skill",
  "source_kind": "public_api",
  "endpoint": "https://api.example.com/v1/run",
  "summary": "一句话描述",
  "auth": { "token_env": "MY_TOKEN", "default_token": "" },
  "request_modes": [{ "name": "run", "transport": "json", "fields": [...] }]
}
```

**标准参考项目**: `auto-hello-worker-skill` (https://github.com/ChangfengHU/auto-hello-worker-skill)

---

## 通用 spec 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `project_slug` | ✅ | 项目标识，也是 skill 名和 CLI 文件名（小写，连字符） |
| `repo_name` | ✅ | GitHub 仓库名 |
| `summary` | ✅ | 一句话描述 |
| `source_kind` | ✅ | 四选一（见上） |
| `request_modes` | ✅ | 调用模式列表 |
| `trigger_phrases` | 否 | Claude 触发词列表 |
| `examples` | 否 | 示例命令列表 |
| `generate_cli` | 否 | 是否生成 CLI 脚本（默认 true） |

---

## 执行流程

### Step 1: 构建 spec.json

根据用户需求确定 source_kind，构建完整 spec.json，保存到 `/tmp/{slug}-spec.json`。

### Step 2: 生成项目

```bash
~/.claude/skills/auto-api-to-skill/scripts/run.sh \
  --spec /tmp/{slug}-spec.json \
  --out /tmp/{slug}-project
```

带 GitHub 仓库创建（使用 ChangfengHU 账号）：

```bash
source ~/.agent-brain-plugins.env
~/.claude/skills/auto-api-to-skill/scripts/run.sh \
  --spec /tmp/{slug}-spec.json \
  --out /tmp/{slug}-project \
  --create-remote \
  --github-owner ChangfengHU \
  --github-token "$CHANGFENG_TOKEN"
```

### Step 3: 发布 skill 到 R2

```bash
cd /tmp/{slug}-project && ./scripts/publish-skill.sh
```

### Step 4（仅 Case 1）: 部署 CF Worker

```bash
source ~/.agent-brain-plugins.env
cd /tmp/{slug}-project && ./scripts/deploy-worker.sh
```

### Step 5（仅 Case 2/3）: 服务机启动 bridge + tunnel

在拥有本地服务的机器上执行：
```bash
# Case 2 only
./scripts/start-local-service.sh --daemon
# Case 2 & 3
METADATA='{"cli":"bash <(curl -fsSL https://skill.vyibc.com/{slug}.sh)","install":"bash <(curl -fsSL https://skill.vyibc.com/install-{slug}.sh)"}'
bash <(curl -fsSL https://skill.vyibc.com/auto-domain.sh) --port=PORT --name=DOMAIN --metadata="$METADATA" --daemon
```

### Step 6: 输出最终结果

发布完成后，必须向用户输出以下两项成果：
1. **Skill 安装命令**（供 AI 安装使用）：
   ```bash
   bash <(curl -fsSL 'https://skill.vyibc.com/install-{slug}.sh?ts=...')
   ```
2. **CLI 执行命令**（供终端直接调用）：
   ```bash
   bash <(curl -fsSL https://skill.vyibc.com/{slug}.sh) --mode=...
   ```

---

## 环境变量（从 ~/.agent-brain-plugins.env 读取）

| 变量 | 用途 |
|------|------|
| `CHANGFENG_TOKEN` | GitHub 推送 token（ChangfengHU 账号） |
| `CF_EMAIL_SKILL` | Cloudflare 账号邮箱（Case 1 部署用） |
| `CF_API_KEY_SKILL` | Cloudflare Global API Key（Case 1 部署用） |
| `CF_ACCOUNT_ID_SKILL` | Cloudflare Account ID |

---

## 更新生成器

```bash
~/.claude/skills/auto-api-to-skill/scripts/run.sh --update
```
