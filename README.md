# AvatarBrain

面向数字人 / 语音助手的 **LLM 大脑服务**。上行接收文本，下行通过 **WebSocket JSON 文本帧**流式推送模型输出，便于与上游 ASR、下游 TTS 低延迟串联。会话内保留多轮历史，系统提示词针对中文口语和语音播报优化。

**默认端口**：`8019`　　**API 文档**：[API.md](./API.md)　　**使用教程**：[USAGE_GUIDE.md](./USAGE_GUIDE.md)

---

## 技术栈

| 层级 | 选型 |
|------|------|
| HTTP / ASGI | FastAPI + Uvicorn |
| WebSocket | Starlette（FastAPI 内置），文本帧，载荷为单行 JSON |
| 配置 | pydantic-settings，从环境变量 / `.env` 加载，启动时校验必填项 |
| LLM | 双通道：本地 `transformers` + 线上 OpenAI 兼容 Chat Completions（`AsyncOpenAI`） |

依赖见 [requirements.txt](./requirements.txt)。

---

## 架构

```
AvatarBackend / 浏览器测试页
        │  WebSocket JSON 文本帧
        ▼
┌──────────────────────────────────┐
│          AvatarBrain 进程         │
│                                  │
│  /ws/chat ──────► LLMService     │
│  /health  ──────►  (单例)         │
│                      │           │
│                       ▼          │
│   本地 transformers / AsyncOpenAI │
└───────────────────────┼──────────┘
                        ▼
      本地模型 或 OpenAI 兼容 Chat Completions API
```

**关键约定：**

- 进程内只有**一个 `LLMService` 实例**，所有 WebSocket 连接共享同一段历史。生产上应保证同一时刻只有一路逻辑会话使用该实例。
- **WebSocket 断开时**（`WebSocketDisconnect` 或未捕获异常）自动调用 `clear_history()`；**新连接建立时不会主动清空**历史，多客户端误连同一实例时可能串话。
- HTTP 与 WebSocket 同属一个 Uvicorn worker，LLM 压力直接反映在请求延迟上。

---

## LLM 调用与历史

- **流式接口**：
  - 本地模式：`TextIteratorStreamer` 真流式逐 token 推送
  - 线上模式：`chat.completions.create(..., stream=True)`
- **消息拼装**：`[system] + history + 当前 user`，system 来自 `LLM_SYSTEM_PROMPT`。
- **历史容量**：`deque(maxlen=12)`，即最多 **6 轮**（每轮 user + assistant 各 1 条）；超出时自动丢弃最旧项。
- **历史写入时机**：整段流结束后对 assistant 回复做归一化，归一化结果非空才将当前 user 与归一化后的 assistant 文本写入历史。流式推送给客户端的 `chunk` 是模型原始 delta，与入库文本略有差异。
- **本地生成默认**：低延时档（`do_sample=False`），减少首包和总耗时。
- **温度**：配置值在发送前被限制在 `0.1`～`1.2`（线上模式生效）。
- **客户端未就绪**：`AsyncOpenAI` 初始化失败时，`stream_reply` 不产生任何 `chunk`，外层仍会发送 `done`；`/health` 的 `ready` / `error` 字段可用于诊断。

### Assistant 文本归一化

流结束后对完整回复做后处理再写入历史，目的是减少 TTS 读出 Markdown 符号的概率：

- 去除围栏代码块和行内反引号
- 去除粗体 / 斜体标记（`**`、`*`）
- 压缩标点两侧空格、合并相邻汉字间空格
- 合并换行与多余空白

实现见 `services/llm.py` 中的 `_normalize_reply_text`。

---

## HTTP 端点

| 路径 | 说明 |
|------|------|
| `GET /`、`GET /test` | 返回 `static/chat-test.html`，浏览器内测 WebSocket |
| `GET /health` | JSON 健康状态，含 `provider`、`ready`、`model`、`base_url`、`history_items`、`error` |
| `GET /docs` | FastAPI 自动生成的 Swagger UI |
| `WebSocket /ws/chat` | 流式对话，详见 [API.md](./API.md) |

---

## 配置（`.env`）

按 provider 生效的必填项：

| 变量 | 说明 |
|------|------|
| `LLM_PROVIDER` | `local` 或 `openai` |
| `LLM_LOCAL_MODEL_PATH` | `local` 模式必填，本地模型目录 |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | `openai` 模式必填；运行时切到 `openai` 也需要 |

可选项：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_TIMEOUT` | `20` | 客户端超时（秒） |
| `LLM_DEVICE` | `auto` | 本地模式设备；可设 `cpu` / `cuda` |
| `LLM_MAX_TOKENS` | `96` | 最大输出 token 数（越小通常越快） |
| `LLM_TEMPERATURE` | `0.3` | 温度，运行时限制在 0.1～1.2 |
| `LLM_SYSTEM_PROMPT` | 内置中文口语提示词 | 覆盖默认系统提示词 |
| `HTTP_HOST` | `0.0.0.0` | 监听地址；`127.0.0.1` / `localhost` / `::1` 会被自动改为 `0.0.0.0` |
| `HTTP_PORT` | `8019` | 监听端口 |
| `SSL_CERTFILE` / `SSL_KEYFILE` | — | 同时设置则启用 HTTPS；支持相对路径（相对项目根目录） |
| `CORS_ORIGINS` | `*` | 允许的跨域来源，多个用英文逗号分隔 |

模板见 [.env.example](./.env.example)。

> **CORS 注意**：`allow_credentials=True` 与通配符 `*` 组合会被浏览器拒绝，需要跨域带 Cookie 时应显式列出 Origin。

---

## 快速开始

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env：
# - 本地模式至少配置 LLM_PROVIDER=local + LLM_LOCAL_MODEL_PATH
# - 若需要运行时切换到 openai，同时填写 LLM_API_KEY、LLM_BASE_URL、LLM_MODEL
python main.py
```

浏览器访问 `http://127.0.0.1:8019/` 打开测试页。启用 HTTPS 后测试页会自动切换至 `wss://`。

---

## 集成要点

1. **串行发送**：发出 `user_input` 后等到收到 `done`（或 `error`）再发下一条，不要并发穿插。
2. **单会话**：设计为一路 Backend 长连接使用；多连接或多租户场景需进程级 / 实例级隔离。
3. **TTS 集成**：可按 `chunk` 增量累积，结合标点分句；收到 `done` 后冲刷剩余缓冲。
4. **通道切换**：测试页支持 local / openai 一键切换；协议见 `API.md` 的 `switch_provider`。

---

## 常见问题

| 现象 | 排查方向 |
|------|---------|
| `/health` 返回 `ready: false` | 查看 `error` 字段，通常是 API Key 错误、网络不通或 `base_url` 无效 |
| WebSocket 立刻断开 | 检查反向代理是否透传 `Upgrade` / `Connection` 头 |
| `wss://` 连接失败 | 浏览器需先信任自签名证书 |
