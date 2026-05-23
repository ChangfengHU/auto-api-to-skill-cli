# auto-api-to-skill-cli

把任意 API、脚本或本地服务一键封装成可分发的 Claude Code skill。

---

## 初始化配置

首次使用前，将密钥写入 `~/.agent-brain-plugins.env`（参考 [.env.example](.env.example)）：

```bash
cp .env.example ~/.agent-brain-plugins.env
# 编辑文件，填入你自己的 GitHub Token、Cloudflare 密钥
```

| 变量 | 用途 |
|---|---|
| `CHANGFENG_TOKEN` | GitHub Token（推送仓库用） |
| `CF_EMAIL_SKILL` | Cloudflare 邮箱 |
| `CF_API_KEY_SKILL` | Cloudflare Global API Key |
| `CF_ACCOUNT_ID_SKILL` | Cloudflare Account ID |
| `CF_WORKERS_SUBDOMAIN` | workers.dev 子域名（CF 控制台可查） |

---

## 安装 Skill

```bash
bash <(curl -fsSL 'https://skill.vyibc.com/install-auto-api-to-skill.sh')
```

安装后，Claude Code 就具备了生成 skill 项目的能力。对 Claude 说：

- "帮我把这个 API 封装成 skill"
- "把这个本地脚本发布成 skill"
- "生成一个 skill 项目"

---

## CLI 直接执行

```bash
bash <(curl -fsSL https://skill.vyibc.com/auto-api-to-skill.sh) \
  --spec /path/to/spec.json \
  --out /path/to/output
```

带 GitHub 仓库创建：

```bash
bash <(curl -fsSL https://skill.vyibc.com/auto-api-to-skill.sh) \
  --spec /path/to/spec.json \
  --out /path/to/output \
  --create-remote \
  --github-owner ChangfengHU \
  --github-token YOUR_TOKEN
```

---

## 四种来源（source_kind）

### Case 1: `cloudflare_worker` — 轻量逻辑 → CF Worker

逻辑简单、无本地环境依赖。部署到 Cloudflare，全球边缘节点，永远在线。

```
写 CF Worker JS → 生成器创建 wrangler 项目 → deploy-worker.sh 部署 → 公网 URL → skill
```

Worker 命名: `auto-api-{slug}`，URL: `https://auto-api-{slug}.hb67egcim4.workers.dev`

示例 spec: [examples/case1-cloudflare-worker/spec.json](examples/case1-cloudflare-worker/spec.json)

**生成后额外操作**:
```bash
source ~/.agent-brain-plugins.env
cd <output> && ./scripts/deploy-worker.sh
```

---

### Case 2: `script_service` — 重量级本地脚本

脚本强依赖本机环境（nvm、conda、私有工具），只能在特定机器运行。通过 Python HTTP bridge 包装 + auto-domain 打洞到公网。

```
local-script.sh → Python HTTP bridge (本地PORT) → auto-domain → 公网URL → skill
```

示例 spec: [examples/case2-script-service/spec.json](examples/case2-script-service/spec.json)

**服务机上的前置步骤（一次性）**:
```bash
./scripts/start-local-service.sh --daemon
bash <(curl -fsSL https://skill.vyibc.com/auto-domain.sh) --port=PORT --name=DOMAIN --daemon
```

---

### Case 3: `local_port` — 本地 HTTP 服务

本机已有运行中的 HTTP 服务，直接用 auto-domain 打洞即可。

```
本地 HTTP 服务 (PORT) → auto-domain → 公网URL → skill
```

示例 spec: [examples/case3-local-port/spec.json](examples/case3-local-port/spec.json)

**服务机上的前置步骤（一次性）**:
```bash
bash <(curl -fsSL https://skill.vyibc.com/auto-domain.sh) --port=PORT --name=DOMAIN --daemon
```

---

### Case 4: `public_api` — 已有公网 API

接口已在公网，直接包装成 skill，无需任何额外基础设施。

```
公网 HTTP 接口 → skill（直接 curl）
```

示例 spec: [examples/case4-public-api/spec.json](examples/case4-public-api/spec.json)

---

## 生成流程

1. **写 spec.json** — 根据来源类型填写字段（见 examples/）
2. **生成项目**:
   ```bash
   ./scripts/auto-api-to-skill.sh --spec spec.json --out /tmp/my-project
   ```
3. **Case 1 额外**: 部署 CF Worker (`deploy-worker.sh`)
4. **Case 2/3 额外**: 在服务机上启动 bridge + auto-domain tunnel
5. **发布 skill**:
   ```bash
   cd /tmp/my-project && ./scripts/publish-skill.sh
   ```
6. **任意机器安装**:
   ```bash
   bash <(curl -fsSL 'https://skill.vyibc.com/install-my-project.sh')
   ```

---

## spec.json 字段说明

### 所有来源必填

| 字段 | 说明 |
|---|---|
| `project_slug` | 项目标识（小写，连字符），同时作为 skill 名和 CLI 文件名 |
| `repo_name` | GitHub 仓库名 |
| `summary` | 一句话描述 |
| `source_kind` | `cloudflare_worker` / `script_service` / `local_port` / `public_api` |
| `request_modes` | 调用模式列表（见下） |

### request_modes 格式

```json
{
  "request_modes": [
    {
      "name": "run",
      "transport": "json",
      "description": "模式说明",
      "fields": [
        {"name": "input", "description": "输入内容"},
        {"name": "file", "description": "文件", "file": true}
      ]
    }
  ]
}
```

`transport` 支持 `json`（默认）和 `multipart`（文件上传）。

### 可选字段

| 字段 | 说明 |
|---|---|
| `trigger_phrases` | Claude 触发词列表 |
| `examples` | 示例命令（进入 README） |
| `generate_cli` | 是否生成 CLI 脚本（默认 true） |
| `auth.token_env` | token 环境变量名 |
| `auth.default_token` | 默认 token |

---

## 本地开发

克隆后直接运行：

```bash
git clone https://github.com/ChangfengHU/auto-api-to-skill-cli
cd auto-api-to-skill-cli
./scripts/auto-api-to-skill.sh --spec examples/case4-public-api/spec.json --out /tmp/test-out
```

发布本 skill 自身：

```bash
./scripts/publish-skill.sh
```

---

## 已生成的示例项目

| 项目 | source_kind | 仓库 |
|---|---|---|
| greet-cf | `cloudflare_worker` | [auto-greet-cf-skill](https://github.com/ChangfengHU/auto-greet-cf-skill) |
| hello-heavy | `script_service` | [auto-hello-heavy-skill](https://github.com/ChangfengHU/auto-hello-heavy-skill) |
| hello-local | `local_port` | [auto-hello-local-skill](https://github.com/ChangfengHU/auto-hello-local-skill) |
| hello-worker | `public_api` | [auto-hello-worker-skill](https://github.com/ChangfengHU/auto-hello-worker-skill) |
