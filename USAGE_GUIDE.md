# AvatarBrain 使用教程：接入线上 OpenAI 兼容接口

本文只说明一种最常用的部署方式：把 AvatarBrain 接入线上 OpenAI 兼容 Chat Completions 接口，例如 DeepSeek、OpenAI、SiliconFlow、通义千问兼容网关或其他兼容 `/v1/chat/completions` 的服务。

本地模型、systemd 常驻部署、Nginx 反向代理、自定义 provider 和修改 LLM 接入代码等内容，见 [高级部署与 LLM 扩展指南](./ADVANCED_USAGE_GUIDE.md)。

## 1. 项目说明

AvatarBrain 是一个面向数字人 / 语音助手的 LLM 大脑服务。

调用链路是：

```text
上游客户端 / AvatarBackend
        │
        │ WebSocket JSON 文本帧
        ▼
AvatarBrain /ws/chat
        │
        │ OpenAI 兼容 Chat Completions stream
        ▼
线上 LLM 服务
```

默认端口是 `8019`。启动后可以访问：

- `GET /health`：查看服务和 LLM 客户端状态。
- `GET /` 或 `GET /test`：打开浏览器静态测试页。
- `WebSocket /ws/chat`：发送用户文本并流式接收模型回复。

## 2. 环境准备

建议使用 Linux 服务器或本地 Linux 环境，准备：

- Python 3.10 或更新版本。
- 可访问线上 LLM 服务的网络。
- 线上模型服务的 `API Key`。
- 线上模型服务的 `Base URL`。
- 要调用的模型名。

以下命令假设项目目录为 `/home/ubuntu/AvatarBrain`。

```bash
cd /home/ubuntu/AvatarBrain
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

不要把真实 `.env` 提交到代码仓库。`LLM_API_KEY` 泄露后应立即在模型服务商后台轮换。

## 3. 配置线上 LLM

编辑 `.env`，使用 `openai` provider。

示例：

```env
LLM_PROVIDER=openai

LLM_API_KEY=你的真实 API Key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

LLM_TIMEOUT=20
LLM_MAX_TOKENS=96
LLM_TEMPERATURE=0.3
LLM_SYSTEM_PROMPT=你是一个自然、友好的中文语音助手。

HTTP_HOST=0.0.0.0
HTTP_PORT=8019
```

关键配置说明：

- `LLM_PROVIDER=openai`：启用线上 OpenAI 兼容接口。
- `LLM_API_KEY`：模型服务商提供的密钥。
- `LLM_BASE_URL`：OpenAI 兼容接口基址，通常以 `/v1` 结尾。
- `LLM_MODEL`：模型名，例如 `deepseek-chat`。
- `LLM_TIMEOUT`：调用 LLM 的超时时间，单位为秒。
- `LLM_MAX_TOKENS`：单次最大输出 token 数，数字人播报场景建议不要太大。
- `LLM_TEMPERATURE`：温度参数，代码中会限制在 `0.1` 到 `1.2`。
- `LLM_SYSTEM_PROMPT`：系统提示词，用来控制语气、人格和回复长度。
- `HTTP_HOST=0.0.0.0`：允许外部机器访问服务。
- `HTTP_PORT=8019`：服务监听端口。

常见服务商配置示例：

```env
# DeepSeek
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

```env
# 本地或内网 OpenAI 兼容网关
LLM_BASE_URL=http://127.0.0.1:8000/v1
LLM_MODEL=your-model-name
```

只要服务商兼容 OpenAI Chat Completions，并支持 `stream=True`，通常只需要改 `.env`，不用改代码。

## 4. 启动服务

在项目目录执行：

```bash
cd /home/ubuntu/AvatarBrain
source .venv/bin/activate
python main.py
```

启动成功后，服务默认监听：

```text
http://127.0.0.1:8019
```

如果部署在服务器上，外部访问地址通常是：

```text
http://服务器IP:8019
```

## 5. 验证服务状态

先检查 `/health`：

```bash
curl http://127.0.0.1:8019/health
```

正常示例：

```json
{
  "status": "ok",
  "provider": "openai",
  "ready": true,
  "model": "deepseek-chat",
  "base_url": "https://api.deepseek.com/v1",
  "device": "cpu",
  "history_items": 0,
  "error": null
}
```

重点看三个字段：

- `provider` 应为 `openai`。
- `ready` 应为 `true`。
- `error` 应为 `null`。

如果 `ready` 是 `false`，优先检查：

- `LLM_API_KEY` 是否为空或错误。
- `LLM_BASE_URL` 是否能从服务器访问。
- `LLM_MODEL` 是否填写了服务商支持的模型名。
- 服务商账号是否欠费、限流或无模型权限。

## 6. 使用网页测试

项目自带一个静态测试页，文件是：

```text
static/chat-test.html
```

启动服务后，在浏览器访问：

```text
http://127.0.0.1:8019/
```

也可以访问：

```text
http://127.0.0.1:8019/test
```

如果服务部署在远程服务器，把 `127.0.0.1` 换成服务器 IP 或域名：

```text
http://服务器IP:8019/
```

网页测试步骤：

1. 点击“请求 /health”，确认页面显示 `ready: true`。
2. 在“模型通道”中选择 `openai`。
3. 点击“连接”，建立 WebSocket 连接。
4. 在输入框输入一句测试文本，例如“你好，简单介绍一下你自己”。
5. 点击“发送 user_input”。
6. 观察聊天区域是否逐步出现模型回复。
7. 在“原始消息日志”里确认服务端先返回多个 `chunk`，最后返回 `done`。

一次正常对话的服务端消息大致是：

```json
{ "type": "chunk", "text": "你好" }
```

```json
{ "type": "chunk", "text": "，我是" }
```

```json
{ "type": "done" }
```

验证通过的标准：

- `/health` 返回 `ready: true`。
- WebSocket 可以连接成功。
- 发送 `user_input` 后能收到增量 `chunk`。
- 每一轮回复结束后能收到 `done`。
- 页面聊天区显示完整回复。

测试时不要在上一轮还没收到 `done` 前继续发送下一条消息。当前服务设计为串行对话，不支持同一连接内多轮并发穿插。

## 7. WebSocket 接入格式

你的上游服务或前端正式接入时，连接：

```text
ws://服务器IP:8019/ws/chat
```

如果外层使用 HTTPS，则 WebSocket 地址应为：

```text
wss://你的域名/ws/chat
```

客户端发送：

```json
{ "type": "user_input", "text": "你好，今天适合做什么？", "provider": "openai" }
```

服务端返回若干增量片段：

```json
{ "type": "chunk", "text": "今天" }
```

最后返回：

```json
{ "type": "done" }
```

需要清空当前会话历史时，发送：

```json
{ "type": "reset" }
```

服务端返回：

```json
{ "type": "reset_ok" }
```

## 8. 常见问题

### `/health` 是 `ready: false`

查看 `error` 字段。OpenAI 兼容模式下，最常见原因是 `LLM_API_KEY`、`LLM_BASE_URL` 或 `LLM_MODEL` 没填对。

### 网页能打开，但 WebSocket 连接失败

确认服务是否仍在运行，浏览器访问的地址和服务监听地址是否一致。如果页面通过 `https://` 打开，WebSocket 必须使用 `wss://`。

### 能连接 WebSocket，但没有模型回复

先请求 `/health`。如果 `ready: false`，说明 LLM 客户端没有初始化成功。如果 `ready: true`，再看服务端日志中是否有模型服务商返回的鉴权、限流、模型不存在或网络错误。

### 回复太长或不适合语音播报

优先调整 `.env`：

```env
LLM_MAX_TOKENS=96
LLM_TEMPERATURE=0.3
LLM_SYSTEM_PROMPT=你是一个自然、友好的中文语音助手。请简短回答，适合直接语音播报。
```

修改 `.env` 后需要重启服务。
