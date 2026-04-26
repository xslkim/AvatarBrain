from __future__ import annotations

import json
import logging
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from config import settings
from services.llm import LLMService

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="AvatarBrain")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")] if settings.cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

llm_service = LLMService()


@app.get("/health")
async def health():
    return {"status": "ok", **llm_service.health}


@app.get("/")
@app.get("/test")
async def chat_test_page():
    """浏览器对话测试页（静态 HTML）。"""
    return FileResponse(STATIC_DIR / "chat-test.html", media_type="text/html; charset=utf-8")


@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    logger.info("AvatarBackend connected")
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "message": "invalid json"}))
                continue

            msg_type = str(data.get("type", ""))

            if msg_type == "reset":
                llm_service.clear_history()
                await websocket.send_text(json.dumps({"type": "reset_ok"}))
                logger.info("History cleared")

            elif msg_type == "switch_provider":
                provider = str(data.get("provider", "")).strip().lower()
                ok, message = llm_service.switch_provider(provider)
                payload = {"type": "provider_switched", "provider": llm_service.health["provider"]}
                if ok:
                    payload["message"] = message
                    payload["ready"] = llm_service.health["ready"]
                    await websocket.send_text(json.dumps(payload))
                    logger.info("Provider switched: %s", llm_service.health["provider"])
                else:
                    payload["type"] = "error"
                    payload["message"] = message
                    await websocket.send_text(json.dumps(payload))

            elif msg_type == "user_input":
                text = str(data.get("text", "")).strip()
                if not text:
                    await websocket.send_text(json.dumps({"type": "error", "message": "empty text"}))
                    continue
                requested_provider = str(data.get("provider", "")).strip().lower()
                if requested_provider:
                    ok, message = llm_service.switch_provider(requested_provider)
                    if not ok:
                        await websocket.send_text(json.dumps({"type": "error", "message": message}))
                        continue
                logger.info("LLM input: %.60s", text)
                try:
                    async for token in llm_service.stream_reply(text):
                        await websocket.send_text(json.dumps({"type": "chunk", "text": token}))
                    await websocket.send_text(json.dumps({"type": "done"}))
                except Exception as exc:
                    logger.warning("Stream error: %s", exc)
                    await websocket.send_text(json.dumps({"type": "error", "message": str(exc)}))

            else:
                await websocket.send_text(json.dumps({"type": "error", "message": f"unknown type: {msg_type}"}))

    except WebSocketDisconnect:
        logger.info("AvatarBackend disconnected, clearing history")
        llm_service.clear_history()
    except Exception as exc:
        logger.warning("ws_chat error: %s", exc)
        llm_service.clear_history()


if __name__ == "__main__":
    import uvicorn

    uvicorn_kwargs: dict = {
        "app": "main:app",
        "host": settings.http_host,
        "port": settings.http_port,
    }
    if settings.ssl_certfile and settings.ssl_keyfile:
        uvicorn_kwargs["ssl_certfile"] = settings.ssl_certfile
        uvicorn_kwargs["ssl_keyfile"] = settings.ssl_keyfile
    uvicorn.run(**uvicorn_kwargs)
