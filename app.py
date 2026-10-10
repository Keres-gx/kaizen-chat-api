import asyncio
import os
import time
import uuid
from collections import deque
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator

APP_NAME = "Kaizen Chat API"
MAX_REQUEST_BYTES = 8 * 1024
RATE_LIMIT_PER_MINUTE = 30  # Simple in-memory limit for the small demo deployment.
UPSTREAM_TIMEOUT_SECONDS = 95

app = FastAPI(title=APP_NAME, docs_url=None, redoc_url=None, openapi_url=None)

allowed_origins = [
    origin.strip().rstrip("/")
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    max_age=600,
)

class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    message: str = Field(min_length=1, max_length=500)
    session_id: Optional[str] = Field(default=None, alias="sessionId", min_length=1, max_length=128)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message cannot be blank")
        return value

    @field_validator("session_id")
    @classmethod
    def session_id_must_not_be_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("sessionId cannot be blank")
        return value.strip() if value is not None else value

# Basic process-local brake for a low-traffic demo. For production/multiple instances,
# replace with a shared rate limiter and provider-level abuse protection.
_request_times = deque()
_rate_lock = asyncio.Lock()

async def enforce_global_rate_limit() -> None:
    now = time.monotonic()
    async with _rate_lock:
        while _request_times and now - _request_times[0] >= 60:
            _request_times.popleft()
        if len(_request_times) >= RATE_LIMIT_PER_MINUTE:
            raise HTTPException(status_code=429, detail="Muitas mensagens em pouco tempo. Tente novamente em instantes.")
        _request_times.append(now)

@app.middleware("http")
async def limit_declared_body_size(request: Request, call_next):
    if request.method == "POST" and request.url.path == "/chat":
        length = request.headers.get("content-length")
        if length:
            try:
                if int(length) > MAX_REQUEST_BYTES:
                    return await _json_error(413, "Requisição muito grande.")
            except ValueError:
                return await _json_error(400, "Content-Length inválido.")
    return await call_next(request)

async def _json_error(status_code: int, message: str):
    from starlette.responses import JSONResponse
    return JSONResponse(status_code=status_code, content={"detail": message})

@app.get("/health")
async def health():
    return {"status": "ok", "service": "kaizen-chat-api"}

@app.post("/chat")
async def chat(payload: ChatRequest, request: Request):
    await enforce_global_rate_limit()

    gateway_url = os.getenv("N8N_GATEWAY_URL", "").strip().rstrip("/")
    gateway_token = os.getenv("GATEWAY_TOKEN", "").strip()
    if not gateway_url or not gateway_token:
        raise HTTPException(status_code=503, detail="A integração do chatbot ainda não está configurada.")

    parsed = urlparse(gateway_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise HTTPException(status_code=503, detail="N8N_GATEWAY_URL deve ser somente a origem HTTPS do túnel, sem caminho.")

    session_id = payload.session_id or str(uuid.uuid4())
    upstream_url = f"{gateway_url}/webhook/chatMNB"
    upstream_payload = {"message": payload.message, "sessionId": session_id}

    try:
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT_SECONDS, follow_redirects=False) as client:
            upstream = await client.post(
                upstream_url,
                json=upstream_payload,
                headers={
                    "X-Gateway-Token": gateway_token,
                    "Accept": "application/json",
                },
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="O chatbot demorou demais para responder. Tente novamente.")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Não foi possível alcançar o gateway do chatbot.")

    if upstream.status_code != 200:
        # Do not expose upstream response bodies, which may contain internal details.
        raise HTTPException(status_code=502, detail=f"O workflow não respondeu corretamente (HTTP {upstream.status_code}).")

    try:
        result = upstream.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="O workflow devolveu uma resposta inválida.")

    if not isinstance(result, dict) or not isinstance(result.get("message"), str):
        raise HTTPException(status_code=502, detail="A resposta do workflow não contém uma mensagem válida.")

    returned_session = result.get("sessionId")
    if not isinstance(returned_session, str) or not returned_session.strip():
        returned_session = session_id

    reply = result["message"].strip()
    if not reply or len(reply) > 6000:
        raise HTTPException(status_code=502, detail="A resposta do workflow está vazia ou é muito grande.")

    return {"message": reply, "sessionId": returned_session}
