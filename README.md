# 大明：危局 (Ming: Crisis)

![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.10+-blue)
![React](https://img.shields.io/badge/react-19-blue)

《大明：危局》是一款 AI 驱动的明末历史治理模拟游戏。玩家扮演崇祯皇帝，通过政令、朝议、奏折与剧情事件，在内忧外患中维持大明国祚。

## 当前实现状态

- AI 政务引擎：支持自由输入政令（`freeform`）解析与执行。
- 剧情事件全 AI 路径：
  - 月推进与新开局时，候选剧情事件由 AI 决定是否触发；
  - 决策持久化到 `state.trigger_decisions`，保证可复现；
  - AI 不可用时自动回退规则触发。
- 剧情事件圣旨输入全 AI 路径：
  - 剧情事件只接受文本输入；
  - 输入由 AI 分类映射到脚本选项；
  - 低置信度返回 `FREEFORM_EMPTY`，事件保持未结案以便重试。
- 政令限制：操作面板政令按类别限频（内政/军事/外交/其他）。
- AI 交互能力：大臣对话、朝议、回合点评、奏折生成等。

## 技术栈

- 后端：FastAPI + Pydantic + aiosqlite
- 前端：React 19 + Vite + TypeScript
- 模型接入：OpenAI / Google / Anthropic / Mock（可切换，含重试与回退）

## 快速开始

### 1) 后端

```bash
pip install -r backend/requirements.txt
cd backend
python -m uvicorn main:app --reload --port 8000
```

健康检查：`GET http://localhost:8000/api/health`

> 如果从仓库根目录启动后端，需要设置 `PYTHONPATH=backend`：
> ```bash
> $env:PYTHONPATH="backend"; uvicorn backend.main:app --reload --port 8000    # PowerShell
> set PYTHONPATH=backend && uvicorn backend.main:app --reload --port 8000     # cmd
> ```

### 2) 前端

```bash
cd frontend
npm install
npm run dev
```

默认地址：`http://localhost:5173`

## 环境变量（核心）

在 `backend/.env` 中配置：

- `AI_PROVIDER`：`mock`（默认）/ `openai` / `google` / `h` / `Z`
- OpenAI 路径常用项：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL_NAME`
- Google 路径常用项：`GOOGLE_API_KEY`、`GOOGLE_BASE_URL`、`GOOGLE_MODEL_NAME`
- Anthropic/自定义供应商通过设置页与对应前缀环境变量管理
- `AI_ENABLE_MOCK_FALLBACK`：控制运行时是否允许回退到 Mock
- `ADMIN_PASSWORD`：访问 `/admin` 管理页面必需，未设置时管理接口不可用

OpenAI-compatible 服务的 `OPENAI_BASE_URL` 应填写到 `/v1`，例如 `https://example.com/v1`。如果在 AI 设置页粘贴完整的 `/v1/chat/completions` 地址，后端会自动规范化为可用的 `/v1`。

> 管理页面：手动启动后端（`cd backend && python -m uvicorn main:app --port 8000`）与前端后访问 `http://localhost:5173/admin`。首次访问需在 `backend/.env` 中设置 `ADMIN_PASSWORD`，然后通过 `/admin` 页面登录。

## 本地健康检查

```bash
openspec validate --all
pip install -r backend/requirements.txt
pytest backend/tests -q
npm --prefix frontend install
npm --prefix frontend run generate-types
npm --prefix frontend run test
npm --prefix frontend run lint
npm --prefix frontend run type-check
```

`npm --prefix frontend run generate-types` 需要后端 OpenAPI 服务可访问；本地可先运行 `cd backend && python -m uvicorn main:app --port 8000`。

## 开源协议

本项目采用 [MIT 协议](LICENSE) 开源。

---
本项目用于学习与技术研究，欢迎提交 Issue 或 Pull Request。
