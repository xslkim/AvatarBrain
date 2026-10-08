# 数字人语音系统部署指南

本文说明如何在新机器上部署完整链路：**AvatarFront（前端） → AvatarBackend（管线） → AvatarBrain（LLM）**。  
推理模型与 3D 模型已通过 **Git LFS** 纳入对应仓库，clone 后即可使用，无需再从 ModelScope / HuggingFace 单独下载。

---

## 1. 系统架构

```
浏览器 (麦克风 + Three.js/VRM)
        │  HTTPS :8181
        ▼
┌───────────────────┐
│   AvatarFront     │  静态页 + VRM 渲染 + 口型驱动
│   端口 8181       │
└─────────┬─────────┘
          │  HTTP/WS → :8018
          │  /ws/audio  /ws/subtitles  /ws/animation  /ws/chart
          │  /chat/text  /health  /events
          ▼
┌───────────────────┐
│  AvatarBackend    │  VAD → ASR → Brain → TTS → ARKit blendshape
│  端口 8018        │
└─────────┬─────────┘
          │  WebSocket BRAIN_URL
          │  默认 ws://<brain-host>:8019/ws/chat
          ▼
┌───────────────────┐
│   AvatarBrain     │  本地 transformers 或 OpenAI 兼容 API
│  端口 8019        │
└───────────────────┘
```

| 组件 | 仓库 | 默认端口 | 职责 |
|------|------|----------|------|
| AvatarFront | `xslkim/AvatarFront` | **8181** HTTPS | 页面、麦克风、VRM 播报 |
| AvatarBackend | `xslkim/AvatarBackend` | **8018** | ASR / VAD / TTS / 动画 / 编排 |
| AvatarBrain | `xslkim/AvatarBrain` | **8019** | LLM 流式对话 |

前端 `config.js` 会按当前页面的 host 自动拼接后端 `:8018`，一般**不用改**。

---

## 2. 机器要求

### 2.1 硬件

| 场景 | 建议 |
|------|------|
| 完整本地推理（ASR + 可选本地 TTS + 本地 LLM） | **NVIDIA GPU**（有 CUDA 时 ASR 走 `cuda:0`，更稳更快） |
| 仅文本 + 云端 LLM + Edge TTS | 可无 GPU；ASR 会降级到 CPU（慢） |
| 磁盘 | 至少 **约 5 GB** 空闲（三仓 LFS 合计约 3.1 GB + 依赖） |
| 内存 | 建议 ≥ 8 GB；本地 Qwen + ASR 同时加载时建议 ≥ 16 GB |

本仓库在无 GPU 机器上**可以启动**，但 FunASR 会警告并回退 CPU；有 GPU 时按设计正常部署运行。

### 2.2 软件

- Linux（推荐 Ubuntu 20.04+）
- Python **3.10+**
- Git + **Git LFS**
- （可选）NVIDIA Driver + CUDA，供本地 ASR / 本地 LLM 使用

```bash
# 安装 Git LFS（Debian/Ubuntu）
sudo apt-get update && sudo apt-get install -y git-lfs
git lfs install
```

---

## 3. 拉取代码与模型（Git LFS）

三个仓库均需拉取；LFS 对象在 clone 时自动下载。若工作区里大文件只有几十字节的指针，再执行 `git lfs pull`。

```bash
export WORKDIR=~/avatar   # 按需修改
mkdir -p "$WORKDIR" && cd "$WORKDIR"

git lfs install

git clone git@github.com:xslkim/AvatarBackend.git
git clone git@github.com:xslkim/AvatarBrain.git
git clone git@github.com:xslkim/AvatarFront.git

# 确认大文件不是 LFS 指针（应看到几百 MB～GB 级）
ls -lh AvatarBackend/models/asr/SenseVoiceSmall/model.pt
ls -lh AvatarBackend/models/tts/Kokoro-82M/kokoro-v1_1-zh.pth
ls -lh AvatarBrain/models/Qwen/Qwen3-0___6B/model.safetensors
ls -lh AvatarFront/models/Sakurada_Fumiriya.vrm
```

HTTPS clone 亦可：

```bash
git clone https://github.com/xslkim/AvatarBackend.git
git clone https://github.com/xslkim/AvatarBrain.git
git clone https://github.com/xslkim/AvatarFront.git
```

### 3.1 各仓 LFS 内含资产

**AvatarBackend（约 1.3 GB）**

| 路径 | 用途 |
|------|------|
| `models/asr/SenseVoiceSmall/` | 中文 ASR（FunASR） |
| `models/tts/Kokoro-82M/` | 本地 TTS 权重 + `voices/*.pt` |
| `models/vad/silero_vad.jit` | 语音活动检测 |

**AvatarBrain（约 1.5 GB）**

| 路径 | 用途 |
|------|------|
| `models/Qwen/Qwen3-0___6B/` | 本地 LLM（`LLM_PROVIDER=local`） |

**AvatarFront（约 19 MB）**

| 路径 | 用途 |
|------|------|
| `models/Sakurada_Fumiriya.vrm` | 当前唯一内置 3D 角色（默认） |

> 额外角色可放到 `models/` 后在页面「模型 URL」加载，或改 `app.js` 的 `BUILTIN_AVATAR_CHOICES`。

### 3.2 LFS 拉取失败时的最小文件清单

若 GitHub LFS 配额不足或网络中断，可从已有机器用 `scp`/`rsync` 拷贝：

```bash
# Backend 推理（必拷，语音链路）
rsync -avP AvatarBackend/models/asr/SenseVoiceSmall/  NEW:/path/AvatarBackend/models/asr/SenseVoiceSmall/
rsync -avP AvatarBackend/models/vad/silero_vad.jit     NEW:/path/AvatarBackend/models/vad/
# 本地 Kokoro TTS（若用 edge: 云端音色可暂缓）
rsync -avP AvatarBackend/models/tts/Kokoro-82M/        NEW:/path/AvatarBackend/models/tts/Kokoro-82M/

# Brain 本地 LLM（仅 LLM_PROVIDER=local 时需要）
rsync -avP AvatarBrain/models/Qwen/Qwen3-0___6B/       NEW:/path/AvatarBrain/models/Qwen/Qwen3-0___6B/

# Front 默认 3D
rsync -avP AvatarFront/models/Sakurada_Fumiriya.vrm \
  NEW:/path/AvatarFront/models/
```

必检文件大小（约值）：

- `SenseVoiceSmall/model.pt` ≈ **893 MB**
- `Kokoro-82M/kokoro-v1_1-zh.pth` ≈ **313 MB**
- `Qwen3-0___6B/model.safetensors` ≈ **1.5 GB**
- `models/Sakurada_Fumiriya.vrm` ≈ **19 MB**

---

## 4. 安装 Python 依赖

### 4.1 AvatarBrain

```bash
cd "$WORKDIR/AvatarBrain"
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
# 本地 LLM 另需：
pip install torch transformers accelerate sentencepiece
# 有 GPU 时安装对应 CUDA 版 torch，参见 https://pytorch.org
deactivate
```

### 4.2 AvatarBackend

```bash
cd "$WORKDIR/AvatarBackend"
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
# FunASR / Kokoro 会拉取较多依赖；有 GPU 时确保 torch 带 CUDA
deactivate
```

### 4.3 AvatarFront

前端为静态资源，仅需系统 Python（跑 `https_server.py`），**无需** venv / npm。

---

## 5. 配置环境变量

### 5.1 AvatarBrain（`.env`）

```bash
cd "$WORKDIR/AvatarBrain"
cp .env.example .env
```

**模式 A：本地 Qwen（仓库内模型）**

```env
LLM_PROVIDER=local
LLM_LOCAL_MODEL_PATH=models/Qwen/Qwen3-0___6B
LLM_DEVICE=cuda
# 无 GPU 时改为：
# LLM_DEVICE=cpu
LLM_MAX_TOKENS=96
HTTP_HOST=0.0.0.0
HTTP_PORT=8019
```

**模式 B：云端 OpenAI 兼容 API（如 DeepSeek）**

```env
LLM_PROVIDER=openai
LLM_API_KEY=sk-xxxx
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
HTTP_HOST=0.0.0.0
HTTP_PORT=8019
```

跨机 HTTPS 时取消注释并指向证书：

```env
SSL_CERTFILE=certs/cert.pem
SSL_KEYFILE=certs/key.pem
```

> 仓库内已有开发用自签证书目录 `certs/`。生产环境请换成正式证书。  
> **不要把含密钥的 `.env` 提交到 Git。**

### 5.2 AvatarBackend（`.env`）

```bash
cd "$WORKDIR/AvatarBackend"
cp .env.example .env
```

本机三件套同机部署示例：

```env
# Brain 在本机且未开 SSL
BRAIN_URL=ws://127.0.0.1:8019/ws/chat
# Brain 开了 HTTPS/WSS 时：
# BRAIN_URL=wss://127.0.0.1:8019/ws/chat

# 本地 Kokoro 音色（需 LFS 中的 voices）
TTS_VOICE=zf_001
# 或云端 Edge TTS（不依赖本地 Kokoro GPU）：
# TTS_VOICE=edge:zh-CN-XiaoxiaoNeural

HTTP_HOST=0.0.0.0
HTTP_PORT=8018
CORS_ORIGINS=*

# 与 Front 共用证书，便于浏览器 wss://
SSL_CERTFILE=../AvatarFront/certs/cert.pem
SSL_KEYFILE=../AvatarFront/certs/key.pem
```

Brain 在另一台机器时，把 `BRAIN_URL` 改成该机可达地址，例如：

```env
BRAIN_URL=ws://192.168.1.50:8019/ws/chat
```

### 5.3 AvatarFront

一般**无需改** `config.js`。它会根据页面域名自动生成：

- `backendHttpUrl` → `https://<当前host>:8018`
- `backendWsUrl` → `wss://<当前host>:8018`

若前后端不同域名，再手工改 `config.js`。

麦克风 API 要求**安全上下文**（HTTPS 或 localhost）。远程访问必须 HTTPS。

证书默认路径：`AvatarFront/certs/cert.pem`、`key.pem`。缺失时 `./start.sh` 会报错。自签证书示例：

```bash
cd "$WORKDIR/AvatarFront/certs"
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout key.pem -out cert.pem -days 365 \
  -subj "/CN=avatar.local"
```

浏览器首次访问需手动信任自签证书（分别打开 Front `:8181` 与 Backend `:8018` 并放行）。

---

## 6. 启动顺序

**务必先 Brain，再 Backend，再 Front。**

### 6.1 启动 AvatarBrain

```bash
cd "$WORKDIR/AvatarBrain"
source .venv/bin/activate
python main.py
# 健康检查
curl -sk https://127.0.0.1:8019/health || curl -s http://127.0.0.1:8019/health
```

浏览器测试页：`http(s)://<host>:8019/test`

### 6.2 启动 AvatarBackend

```bash
cd "$WORKDIR/AvatarBackend"
./start.sh          # 后台；或 foreground: .venv/bin/python main.py
./start.sh status
./start.sh log      # 跟日志
```

健康检查应看到 ASR / TTS / VAD / brain 状态：

```bash
curl -sk https://127.0.0.1:8018/health | python3 -m json.tool
```

关注字段：

- `asr.ready` / `asr.device`（有 GPU 时多为 `cuda:0`）
- `tts.ready`
- `vad.ready`
- `brain.connected`

### 6.3 启动 AvatarFront

```bash
cd "$WORKDIR/AvatarFront"
./start.sh
./start.sh status
```

浏览器打开：`https://<服务器IP或域名>:8181/`

1. 信任证书  
2. 选择 3D 角色（默认 Sakurada）  
3. 点击「连接语音通道」授权麦克风  
4. 也可直接在输入框发文本走 `/chat/text`

---

## 7. 端口与防火墙

| 端口 | 服务 | 对外 |
|------|------|------|
| 8181 | Front HTTPS | 需要（用户浏览器） |
| 8018 | Backend HTTP/WS | 需要（浏览器直连） |
| 8019 | Brain | 通常仅内网；Backend 能访问即可 |

```bash
# 示例（ufw）
sudo ufw allow 8181/tcp
sudo ufw allow 8018/tcp
# Brain 若仅本机 Backend 访问，可不开放 8019
```

---

## 8. 数据流与联调要点

1. **语音**：Front `/ws/audio` 上传 PCM → Backend VAD 切句 → ASR → Brain 流式 token → 按句 TTS → 下行 WAV + `/ws/animation` blendshape → Front 播报并驱动 VRM。  
2. **文本**：`POST /chat/text` 跳过 ASR。  
3. **打断（barge-in）**：Avatar 说话时用户再开口，VAD 触发取消当前播报。  
4. **单会话**：同类型 WebSocket 新连接会顶掉旧连接（一次一个前端会话）。  
5. **Chart**：Brain 若下发 `type=chart`，Backend 经 `/ws/chart` 转发，Front 可 `postMessage` 给图表 iframe。

详细协议见各仓 `API.md`。

---

## 9. 常见问题

### 9.1 clone 后模型只有几 KB

未拉取 LFS 实体：

```bash
git lfs install
git lfs pull
```

### 9.2 ASR `ready: false` 或极慢

- 确认 `models/asr/SenseVoiceSmall/model.pt` 完整（约 893MB）  
- 无 GPU 时会走 CPU，首包很慢属预期  
- 查看 Backend 日志中 `ASR running in degraded mode on cpu`

### 9.3 `brain.connected: false`

- Brain 是否已启动  
- `BRAIN_URL` 协议/端口是否匹配（`ws` vs `wss`）  
- 自签证书时 Backend 对 `wss://` 已关闭校验；HTTP 混用仍会失败

### 9.4 浏览器连不上麦克风 / WebSocket

- 必须用 HTTPS 打开 Front（或 localhost）  
- 分别访问并信任 Front 与 Backend 的证书  
- 检查 `config.js` 拼出的后端地址是否指向正确 host

### 9.5 口型不动 / 无声音

- `/ws/animation`、`/ws/audio` 是否已连接（页面诊断灯）  
- TTS 音色：本地 `zf_*` 需 Kokoro voices；`edge:*` 需出网  
- `/health` 里 `tts.ready`

### 9.6 本地 LLM OOM

- 减小 `LLM_MAX_TOKENS`  
- `LLM_DEVICE=cpu` 或改用 `LLM_PROVIDER=openai`  
- 关闭其它占显存进程

---

## 10. 更新与备份

```bash
cd AvatarBackend && git pull && git lfs pull
cd AvatarBrain   && git pull && git lfs pull
cd AvatarFront   && git pull && git lfs pull
# 再按需重启各服务
```

备份建议保留：各仓 `.env`、自定义证书、自研 VRM（若有）。

---

## 11. 仓库与文档索引

| 仓库 | 说明文档 |
|------|----------|
| AvatarBackend | [API.md](https://github.com/xslkim/AvatarBackend/blob/main/API.md)、[CLAUDE.md](https://github.com/xslkim/AvatarBackend/blob/main/CLAUDE.md)、[COMM_LOGGING.md](https://github.com/xslkim/AvatarBackend/blob/main/COMM_LOGGING.md) |
| AvatarBrain | [README.md](https://github.com/xslkim/AvatarBrain/blob/main/README.md)、[API.md](https://github.com/xslkim/AvatarBrain/blob/main/API.md)、[USAGE_GUIDE.md](https://github.com/xslkim/AvatarBrain/blob/main/USAGE_GUIDE.md) |
| AvatarFront | [API.md](https://github.com/xslkim/AvatarFront/blob/main/API.md)、[MODEL_SPEC.md](https://github.com/xslkim/AvatarFront/blob/main/MODEL_SPEC.md) |

远程地址：

- https://github.com/xslkim/AvatarBackend  
- https://github.com/xslkim/AvatarBrain  
- https://github.com/xslkim/AvatarFront  

本文档在三仓中均有同名副本：`DEPLOY.md`。

---

## 12. 快速检查清单

- [ ] 已安装 `git-lfs`，三大仓 clone 完成且大文件体积正常  
- [ ] Brain / Backend venv 与依赖安装完成  
- [ ] 三仓 `.env`（Front 一般不用）按本机/云端模式填好  
- [ ] 证书存在；浏览器已信任 `:8181` 与 `:8018`  
- [ ] 启动顺序：Brain → Backend → Front  
- [ ] `/health` 中 asr/tts/vad/brain 正常  
- [ ] 页面可连语音通道，文本或语音有回复与口型  
