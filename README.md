# AvatarBrain

面向「数字人 / 语音助手」的 **LLM 大脑服务**：上行只收**文本**，下行用 **WebSocket JSON 文本帧**按模型输出**流式**推送，便于上游 ASR、下游 TTS 以低延迟串起来。会话内带 **多轮历史**（有上限），系统提示词偏向**中文口语、短句、适合播报**。

**默认端口**：`8019`。  
**接口约定（消息类型表）**：[API.md](./API.md)

---

## 技术栈

| 层级 | 选型 | 说明 |
|------|------|------|
| HTTP / ASGI | [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) | 路由、`/health`、静态测试页 |
| WebSocket | Starlette（FastAPI 内置） | `receive_text` / `send_text`，载荷为一行 JSON |
| 配置 | [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) | 从环境变量与 `.env` 加载；启动前校验 LLM 必填项 |
| LLM 访问 | [OpenAI Python SDK](https://github.com/openai/openai-python) 的 `AsyncOpenAI` | 使用 `base_url` 指向任意兼容 **Chat Completions** 的网关（DeepSeek、OpenAI、自建等） |

依赖列表见 [requirements.txt](./requirements.txt)（版本未锁定时，以安装时解析为准）。

---

## 架构与进程模型

`mermaid` 围栏块**不是内嵌图片**：只有支持 Mermaid 的渲染器才会画成图（例如 GitHub 仓库主页的 README；多数 IDE 自带 Markdown 预览**不会**渲染）。为在任意阅读环境里都能直接看懂，这里用 **ASCII 示意图**：

```
  AvatarBackend / 浏览器测试页
            │  WebSocket：JSON 文本帧
            ▼
  ┌─────────────────────────────────────────┐
  │           AvatarBrain 进程               │
  │                                         │
  │   /ws/chat ──────────► LLMService 单例   │
  │                            │            │
  │   GET /health ─────────►  │            │
  │                            ▼            │
  │                    AsyncOpenAI（流式）  │
  └────────────────────────────┼───────────┘
                               ▼
                    兼容 OpenAI 的 Chat Completions API
```

要点（与当前实现一致）：

1. **全局一个 `LLMService` 实例**，内部一块 **`deque` 历史**，因此**同一进程内所有 WebSocket 连接共享同一段历史**。生产上应保证**只有一个逻辑会话**同时使用该实例（或自行做进程/实例隔离）。
2. **`WebSocketDisconnect` 或 `ws_chat` 未捕获异常**时，会调用 `llm_service.clear_history()`；**新连接建立时不会主动清空**上一轮连接留下的历史——若在多客户端误连同一实例时可能出现串话。
3. **HTTP** 与 **WebSocket** 同属一个 Uvicorn worker；无单独消息队列，LLM 压力直接反映在请求延迟上。

---

## WebSocket 协议（实现细节）

- **URL**：`ws://<host>:<port>/ws/chat`；若服务器以 HTTPS 提供页面，浏览器端应使用 **`wss://`**（同源页面测试脚本会自动切换）。
- **帧类型**：仅用**文本帧**；每条消息是一行 **UTF-8 JSON**，`Content-Type` 概念上为 `application/json` 字符串。
- **下行顺序**：对一次 `user_input`，正常情况下依次为若干 `{"type":"chunk","text":"..."}`，最后 **`{"type":"done"}`**。若向客户端 **`send_text` 失败**等外层异常，会发 `{"type":"error",...}` 且**不一定**再发 `done`。
- **`reset`**：清空 `deque`，回复 `reset_ok`，不调用模型。

完整类型表见 [API.md](./API.md)。

---

## LLM 调用与历史

- **接口**：`client.chat.completions.create(..., stream=True)`，即 **Chat Completions 流式**。
- **消息拼装**：`[system] + history（user/assistant 交替，最多 12 条） + 当前 user`。`system` 来自 `LLM_SYSTEM_PROMPT`（代码内另有默认长提示，可用环境变量覆盖）。
- **历史容量**：`deque(maxlen=12)` → **6 轮**对话（每轮 user + assistant 各占 1 条）。超出时最旧项被丢弃。
- **何时写入历史**：**整段流结束且成功归一化后**，若归一化正文非空，才 `append` **当前 user 原文**与 **assistant 归一化全文**。流式过程中发出去的 `chunk` 仍是模型**原始 delta**（未归一化），与入库的 assistant 文本可能略有差异（归一化见下）。
- **温度**：配置值会夹在 **`0.1`～`1.2`** 再发给 API。
- **未就绪的客户端**：若 `AsyncOpenAI` 初始化失败（`ready == false`），`stream_reply` 立即结束、**不产生任何 `chunk`**，但外层循环仍会发送 **`done`**；`/health` 里 `ready`/`error` 可用来区分。

---

## Assistant 文本归一化（入库与「语音友好」）

对**完整回复**做后处理后再写入历史，主要目的：弱化 Markdown、代码块和多余空白，减少 TTS 读符号、读星号的概率。包括：去掉围栏代码块与行内反引号、粗体/斜体标记、合并换行与空白、压缩中英文标点两侧空格、收紧相邻汉字之间的空格等（实现见 `services/llm.py` 中 `_normalize_reply_text`）。

---

## HTTP 层

| 路径 | 行为 |
|------|------|
| `GET /` 、`GET /test` | 返回 [static/chat-test.html](./static/chat-test.html)，浏览器内测 WebSocket |
| `GET /health` | JSON：`status`、`ready`、`model`、`base_url`、`history_items`、`error` |
| `GET /docs` 、`GET /openapi.json` | FastAPI 自带 Swagger / OpenAPI（默认开启） |

**CORS**：`CORSMiddleware`，`allow_origins` 为 `CORS_ORIGINS` 按逗号拆分并 `strip`；为 `*` 或未配置时的回退逻辑以 `main.py` 为准。需要跨域带 Cookie 时当前为 `allow_credentials=True`，若使用通配 `*` 浏览器可能拒绝，此时应显式列出 Origin。

**HTTPS**：同时设置 `SSL_CERTFILE` 与 `SSL_KEYFILE` 时，Uvicorn 加载证书启动 TLS。路径可为相对路径，相对 **项目根目录** 解析（`config.py` 中 `resolve_ssl_path`）。

**监听地址**：若 `.env` 把 `HTTP_HOST` 设为 `127.0.0.1`、`localhost` 或 `::1`，会 **归一成 `0.0.0.0`**，避免只能本机访问的问题。

---

## 配置（`.env`）

启动时 **必须** 提供非空的 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`，否则 `Settings` 校验失败、进程无法启动。

| 变量 | 必填 | 说明 |
|------|------|------|
| `LLM_API_KEY` | 是 | 网关 API Key |
| `LLM_BASE_URL` | 是 | 如 `https://api.deepseek.com/v1` |
| `LLM_MODEL` | 是 | 模型 id |
| `LLM_TIMEOUT` | 否 | 客户端超时（秒），默认 20 |
| `LLM_MAX_TOKENS` | 否 | 默认 300 |
| `LLM_TEMPERATURE` | 否 | 默认 0.55，发送前限制在 0.1～1.2 |
| `LLM_SYSTEM_PROMPT` | 否 | 系统提示词 |
| `HTTP_HOST` | 否 | 默认 `0.0.0.0`；本地回环名会被改成 `0.0.0.0` |
| `HTTP_PORT` | 否 | 默认 `8019` |
| `SSL_CERTFILE` / `SSL_KEYFILE` | 否 | 同时设置则启用 HTTPS |
| `CORS_ORIGINS` | 否 | 默认 `*`；多来源用英文逗号分隔 |

模板见 [.env.example](./.env.example)。

---

## 本地运行

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env（至少三项 LLM_*）
python main.py
```

浏览器访问 **http://127.0.0.1:8019/** 打开测试页；HTTPS 部署时用 **https://**，测试页会走 **wss://**。

---

## 集成与并发约定

1. **串行轮次**：发完 `user_input` 后应收到 **`done`**（或 **`error`**）再发下一轮；不要并行穿插多路 `user_input`。
2. **单会话**：设计上按「一路 Backend 长连接」使用；多连接共享单例历史是当前实现的代价，扩缩或多租户时应用进程级或连接级隔离。
3. **TTS**：可按 `chunk` 增量累积，结合标点做分句；`done` 表示可冲刷剩余缓冲。

---

## 故障与排错

- **`/health` 中 `ready: false`**：看 `error` 字段；多为密钥、网络或 `base_url` 不可达。
- **WebSocket 立刻断**：检查反向代理是否支持 **WebSocket 升级**（`Upgrade`、`Connection`）。
- **自签名证书**：浏览器需信任证书后，`wss` 才能连上。
