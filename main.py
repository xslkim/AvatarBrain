from __future__ import annotations

import json
import logging

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from services.llm import LLMService

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

            elif msg_type == "user_input":
                text = str(data.get("text", "")).strip()
                if not text:
                    await websocket.send_text(json.dumps({"type": "error", "message": "empty text"}))
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
