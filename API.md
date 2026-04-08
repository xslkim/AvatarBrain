# AvatarBrain API

流式对话：**WebSocket** 收 JSON，推 `chunk` + `done`。默认端口 **8019**；HTTPS 下 WebSocket 为 **`wss://`**。

| 端点 | 说明 |
|------|------|
| `GET /` 、`GET /test` | 浏览器测试页（详见 [README.md](./README.md)） |
| `GET /health` | 健康与 LLM 状态 |
| `WebSocket /ws/chat` | 对话 |

---

## `GET /health`

示例响应：

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

## `WebSocket /ws/chat`

**连接**：同一连接内保留至多 **6 轮**（12 条 user/assistant）历史；**断开即清空**。客户端宜保持**单连接**串行发送（见下表「约束」）。

### 客户端 → 服务端

| `type` | 体 | 说明 |
|--------|-----|------|
| `user_input` | `text`（非空 string） | 开始流式回复 |
| `reset` | — | 清空历史；服务端回复 `reset_ok` |

非 JSON、未知 `type`、或 `text` 为空会收到 `error`。

### 服务端 → 客户端

| `type` | 体 | 说明 |
|--------|-----|------|
| `chunk` | `text` | LLM 增量，需拼接 |
| `done` | — | 本条 `user_input` 结束 |
| `reset_ok` | — | 历史已清空 |
| `error` | `message` | 错误描述 |

### 约束

- 等待 **`done`** 后再发下一条 `user_input`。
- **流式**：按 token/片段逐条 `chunk`，便于 TTS 侧按标点切句。

### 示例顺序

`user_input` → 若干 `chunk` → `done`；`reset` → `reset_ok`。
