# AvatarBrain 高级部署与 LLM 扩展指南

本文收纳 `USAGE_GUIDE.md` 之外的内容，包括本地模型部署、服务器常驻运行、反向代理、HTTPS、自定义 provider，以及修改 LLM 接入代码的方法。

如果只需要接入线上 OpenAI 兼容接口，请先看 [AvatarBrain 使用教程：接入线上 OpenAI 兼容接口](./USAGE_GUIDE.md)。

## 1. 使用本地 transformers 模型

本地模式会在 `services/llm.py` 中加载：

- `AutoTokenizer`
- `AutoModelForCausalLM`
- `TextIteratorStreamer`

当前 `requirements.txt` 没有声明 `torch` 和 `transformers`。如果使用本地模式，需要按机器环境额外安装。

CPU 功能测试可参考：

```bash
pip install torch transformers
```

如果使用 CUDA，请按 PyTorch 官网与你的 CUDA 版本选择安装命令。

`.env` 示例：

```env
LLM_PROVIDER=local

LLM_LOCAL_MODEL_PATH=/home/ubuntu/models/Qwen/Qwen3-0___6B
LLM_DEVICE=auto

LLM_MAX_TOKENS=96
LLM_SYSTEM_PROMPT=你是一个自然、友好的中文语音助手。

HTTP_HOST=0.0.0.0
HTTP_PORT=8019
```

说明：

- `LLM_LOCAL_MODEL_PATH` 必须指向本地模型目录。
- `LLM_DEVICE=auto` 时，代码会优先使用 CUDA，否则使用 CPU。
- CPU 可以用于功能验证，但真实低延迟语音场景通常建议使用 GPU。

启动：

```bash
cd /home/ubuntu/AvatarBrain
source .venv/bin/activate
python main.py
```

## 2. 服务器常驻部署

### 2.1 使用 systemd

可以创建 `/etc/systemd/system/avatarbrain.service`：

```ini
[Unit]
Description=AvatarBrain LLM Brain Service
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/ubuntu/AvatarBrain
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/ubuntu/AvatarBrain/.venv/bin/python /home/ubuntu/AvatarBrain/main.py
Restart=always
RestartSec=3
User=ubuntu

[Install]
WantedBy=multi-user.target
```

启用服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable avatarbrain
sudo systemctl start avatarbrain
sudo systemctl status avatarbrain
```

查看日志：

```bash
journalctl -u avatarbrain -f
```

### 2.2 使用 Nginx 反向代理

如果前面有 Nginx，需要确保 WebSocket 升级头被透传：

```nginx
server {
    listen 80;
    server_name your-domain.example;

    location / {
        proxy_pass http://127.0.0.1:8019;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;
    }
}
```

如果网页通过 HTTPS 打开，浏览器端 WebSocket 应使用 `wss://`。可以让 Nginx 负责 HTTPS 证书，后端 AvatarBrain 继续监听本机 HTTP。

### 2.3 直接启用 HTTPS

项目也支持直接让 Uvicorn 启用 HTTPS，只要在 `.env` 同时配置：

```env
SSL_CERTFILE=certs/dev-cert.pem
SSL_KEYFILE=certs/dev-key.pem
```

相对路径会按项目根目录解析。生产环境通常更推荐由 Nginx/Caddy 等网关负责 HTTPS。

## 3. 重要运行约束

当前实现中，`main.py` 只创建一个进程级 `LLMService` 实例：

```python
llm_service = LLMService()
```

因此需要注意：

- 多个 WebSocket 连接会共享同一段历史。
- 断开连接时会清空历史。
- 设计上更适合一个 AvatarBackend 长连接对应一个 AvatarBrain 实例。
- 如果要支持多用户、多会话或多租户，需要把历史从全局单例拆到会话级存储。

## 4. 修改 LLM 接入代码

LLM 接入集中在 `services/llm.py`。修改时优先判断你属于哪一种需求。

### 4.1 修改 prompt、历史和生成参数

常见调整点：

- 系统提示词：优先改 `.env` 的 `LLM_SYSTEM_PROMPT`。
- 最大输出长度：改 `.env` 的 `LLM_MAX_TOKENS`。
- 温度：改 `.env` 的 `LLM_TEMPERATURE`。
- 历史轮数：改 `services/llm.py` 中 `deque(maxlen=12)`，当前等于 6 轮 user/assistant。
- 消息拼装方式：改 `stream_reply()` 和 `_stream_reply_local()` 中的 `messages`。
- TTS 友好清洗：改 `_normalize_reply_text()`。

### 4.2 接入非 OpenAI 协议的线上 LLM

如果服务商不兼容 OpenAI Chat Completions，需要新增 provider。建议按以下步骤改。

第一步，在 `config.py` 中允许新 provider，例如增加 `custom`：

```python
if text not in {"openai", "local", "custom"}:
    raise ValueError("LLM_PROVIDER must be one of: openai, local, custom")
```

同时按需要增加新环境变量，例如：

```python
llm_custom_endpoint: str = Field(default="", validation_alias="LLM_CUSTOM_ENDPOINT")
```

第二步，在 `.env.example` 中补充配置模板：

```env
LLM_PROVIDER=custom
LLM_CUSTOM_ENDPOINT=https://example.com/chat
LLM_API_KEY=
LLM_MODEL=
```

第三步，在 `services/llm.py` 中增加初始化方法，例如：

```python
def _init_custom_client(self) -> None:
    # 在这里创建自定义 SDK 客户端，或保存 endpoint/api_key/model。
    self._ready = True
    self._error = None
```

第四步，在 `LLMService.__init__()` 中分发：

```python
if self._provider == "local":
    self._init_local_model()
elif self._provider == "custom":
    self._init_custom_client()
else:
    self._init_openai_client()
```

第五步，在 `stream_reply()` 中增加自定义流式分支：

```python
if self._provider == "custom":
    async for delta in self._stream_reply_custom(text):
        yield delta
    return
```

第六步，实现 `_stream_reply_custom()`：

```python
async def _stream_reply_custom(self, text: str):
    messages = [
        {"role": "system", "content": self._system_prompt},
        *list(self._history),
        {"role": "user", "content": text},
    ]

    accumulated = ""

    # 调用你的自定义 LLM 流式接口，把每个增量文本赋值给 delta。
    async for delta in your_custom_stream_call(messages):
        if not delta:
            continue
        accumulated += delta
        yield delta

    normalized = self._normalize_reply_text(accumulated)
    if normalized:
        self._history.append({"role": "user", "content": text})
        self._history.append({"role": "assistant", "content": normalized})
```

第七步，更新 `switch_provider()`。当前只允许 `openai` 和 `local`，新增 provider 后也要让运行时切换逻辑识别它。

第八步，更新 `API.md`、测试页和相关文档，说明新的 provider 名称、配置项和错误排查方法。

### 4.3 接入新的本地推理框架

如果不是使用 transformers，而是接入 vLLM、Ollama、llama.cpp、TGI 等本地推理服务，有两种做法。

方式一：如果它们提供 OpenAI 兼容接口，推荐直接走 `openai` provider：

```env
LLM_PROVIDER=openai
LLM_API_KEY=任意非空值或服务要求的 key
LLM_BASE_URL=http://127.0.0.1:8000/v1
LLM_MODEL=本地服务暴露的模型名
```

方式二：如果接口不兼容 OpenAI，则按上一节新增 provider，并在 `_stream_reply_custom()` 里适配它的流式格式。

## 5. 修改后的检查清单

每次修改部署配置或 LLM 接入代码后，建议按顺序检查：

1. `.env` 是否包含当前 provider 需要的必填项。
2. `python main.py` 是否能正常启动。
3. `/health` 是否返回 `ready: true`。
4. 浏览器测试页是否能连接 WebSocket。
5. `user_input` 是否能收到多个 `chunk` 和最终 `done`。
6. 模型报错时是否能在 `/health.error` 或服务日志中看到清晰错误。
7. 修改 provider 名称后，`switch_provider`、`API.md`、前端测试页是否同步更新。

## 6. 常见问题

### `/health` 返回 `ready: false`

查看返回里的 `error` 字段。常见原因：

- `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` 未配置。
- 服务器无法访问线上模型服务。
- 本地模型路径不存在。
- 本地模式缺少 `torch` 或 `transformers`。
- CUDA、显存或模型格式不匹配。

### WebSocket 能连接但没有回复

检查：

- 当前 provider 是否 `ready: true`。
- 客户端是否发送了合法 JSON。
- `text` 是否为空。
- 是否上一轮还没有收到 `done` 就发送了下一轮。
- 服务日志中是否有 LLM 调用异常。

### 浏览器访问 HTTPS 时 WebSocket 失败

如果页面是 `https://`，WebSocket 必须使用 `wss://`。同时确认反向代理已经透传：

- `Upgrade`
- `Connection`
- `proxy_http_version 1.1`

### 多个用户对话串话

这是当前架构的已知约束：所有连接共享同一个 `LLMService` 和同一段 `_history`。如果要支持多用户，需要把 `_history` 放到连接级、用户级或会话级对象中，而不是放在全局单例里。
