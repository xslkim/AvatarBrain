# AvatarBrain API

默认端口 **8019**；HTTPS 部署时 WebSocket 使用 **`wss://`**。

---

## `GET /health`

返回服务与 LLM 客户端状态。

**响应示例：**

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

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | 固定为 `"ok"` |
| `ready` | boolean | LLM 客户端是否初始化成功 |
| `model` | string | 当前使用的模型 ID |
| `base_url` | string | LLM 网关地址 |
| `history_items` | integer | 当前历史条数（最大 12） |
| `error` | string \| null | 最近一次错误信息；无错误时为 `null` |

---

## `WebSocket /ws/chat`

全双工流式对话。连接内保留最多 **6 轮**（12 条）历史；**断开时自动清空**历史。

### 客户端 → 服务端

每条消息为一行 UTF-8 JSON 文本帧。

#### `user_input` — 发起对话

```json
{ "type": "user_input", "text": "今天天气怎么样？" }
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | `"user_input"` |
| `text` | string | 用户输入，不能为空 |

服务端依次回复若干 `chunk`，最后回复 `done`。

#### `reset` — 清空历史

```json
{ "type": "reset" }
```

服务端回复 `reset_ok`，不调用模型。

---

### 服务端 → 客户端

#### `chunk` — 模型增量输出

```json
{ "type": "chunk", "text": "今天" }
```

需客户端自行拼接所有 `chunk.text` 以还原完整回复。

#### `done` — 本轮结束

```json
{ "type": "done" }
```

收到 `done` 后可发送下一条 `user_input`。

#### `reset_ok` — 历史已清空

```json
{ "type": "reset_ok" }
```

#### `error` — 错误

```json
{ "type": "error", "message": "empty text" }
```

| 触发场景 | `message` 示例 |
|---------|----------------|
| 非法 JSON | `"invalid json"` |
| `text` 为空 | `"empty text"` |
| 未知 `type` | `"unknown type: foo"` |
| 流式调用异常 | 异常原始描述 |

收到 `error` 后不保证还有 `done`，建议客户端做超时保护。

---

### 交互流程

```
客户端                          服务端
  │── user_input ──────────────►│
  │◄─ chunk ("今") ─────────────│
  │◄─ chunk ("天") ─────────────│
  │◄─ ... ──────────────────────│
  │◄─ done ─────────────────────│
  │
  │── reset ────────────────────►│
  │◄─ reset_ok ─────────────────│
```

### 使用约束

- 收到 `done`（或 `error`）后再发下一条 `user_input`；不支持并发穿插。
- 设计为单连接单会话使用，多连接共享同一历史。
