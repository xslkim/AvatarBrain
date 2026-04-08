# AvatarBrain API 文档

AvatarBrain 是 AI 大脑服务，通过 WebSocket 接收文本，流式返回 LLM 回复。

**默认端口**: `8019`

---

## 端点总览

| 端点 | 协议 | 方向 | 说明 |
|------|------|------|------|
| `/health` | HTTP GET | — | 服务健康状态 |
| `/ws/chat` | WebSocket | 全双工 | LLM 流式对话 |

---

## HTTP 端点

### `GET /health`

返回服务健康状态和 LLM 信息。

**响应示例**:
```json
{
  "status": "ok",
  "ready": true,
  "model": "deepseek-chat",
  "base_url": "https://api.deepseek.com/v1",
  "history_items": 4,
  "error": null
}
```

---

## WebSocket 端点

### `ws://host:8019/ws/chat`

全双工 JSON 消息流。AvatarBackend 作为客户端连接此端点。

**连接生命周期**:
- Backend 启动时建立长连接
- Brain 在同一连接内维护会话历史（deque，最多 6 轮）
- 连接断开时 Brain 自动清空历史
- Backend 重连后从空历史开始

---

### 消息格式：Backend → Brain

#### 1. 发送用户输入

```json
{
  "type": "user_input",
  "text": "今天天气怎么样"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | `"user_input"` | 消息类型 |
| `text` | string | 用户问题（非空） |

Brain 收到后立即开始流式推送 LLM token。

#### 2. 重置会话历史

```json
{
  "type": "reset"
}
```

清空 Brain 侧的对话历史。Brain 返回 `reset_ok`。

---

### 消息格式：Brain → Backend

#### 1. 流式 token 块

```json
{
  "type": "chunk",
  "text": "今天"
}
```

每个 `chunk` 包含一个或几个 LLM 生成的 token 片段，Backend 需要累积后按标点断句送 TTS。

#### 2. 流式完成

```json
{
  "type": "done"
}
```

当前 `user_input` 的 LLM 生成已完成。Backend 收到后处理剩余缓冲文本。

#### 3. 重置确认

```json
{
  "type": "reset_ok"
}
```

历史已清空。

#### 4. 错误

```json
{
  "type": "error",
  "message": "错误描述"
}
```

---

### 完整交互时序

```
Backend                          Brain
  |                                |
  |--- {"type":"user_input",       |
  |     "text":"你好"}  ---------->|
  |                                | [调用 LLM stream API]
  |<-- {"type":"chunk","text":"你好"} |
  |<-- {"type":"chunk","text":"！"} |
  |<-- {"type":"chunk","text":"有什么"}|
  |<-- {"type":"chunk","text":"需要帮助的吗"} |
  |<-- {"type":"done"}             |
  |                                |
  |--- {"type":"reset"} ---------->|
  |<-- {"type":"reset_ok"} --------|
```

---

## 设计约束

- **单会话**：Brain 只为一个 Backend 连接服务，新连接会清空旧历史
- **历史管理**：最多保留 6 轮对话（12 条消息），超出自动滚动
- **流式优先**：LLM 每产生一个 token 立即发送，Backend 无需等待完整回复再 TTS
- **无并发保护**：Backend 不应同时发送多个 `user_input`，需等待 `done` 再发下一个
