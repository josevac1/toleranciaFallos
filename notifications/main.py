import asyncio
import logging
import os
import random
import uuid

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | notifications | %(levelname)s | %(message)s",
)

app = FastAPI(
    title="Servicio de Notificaciones Simulado",
    version="1.0.0",
)

MIN_DELAY_MS = int(os.getenv("MIN_DELAY_MS", "200"))
MAX_DELAY_MS = int(os.getenv("MAX_DELAY_MS", "1200"))
FAILURE_RATE = float(os.getenv("FAILURE_RATE", "0.10"))


class NotificationRequest(BaseModel):
    reservation_id: str
    email: str
    message: str


@app.get("/")
def root():
    return {
        "service": "notifications-service",
        "status": "running",
        "simulation": {
            "min_delay_ms": MIN_DELAY_MS,
            "max_delay_ms": MAX_DELAY_MS,
            "failure_rate": FAILURE_RATE,
        },
    }


@app.get("/health")
def health():
    return {
        "status": "UP",
        "service": "notifications-service",
    }


@app.post("/notifications/send")
async def send_notification(
    request: NotificationRequest,
    x_request_id: str | None = Header(default=None),
):
    request_id = x_request_id or str(uuid.uuid4())
    delay_ms = random.randint(MIN_DELAY_MS, MAX_DELAY_MS)

    logging.info(
        "request_id=%s Enviando notificación a %s",
        request_id,
        request.email,
    )

    await asyncio.sleep(delay_ms / 1000)

    if random.random() < FAILURE_RATE:
        logging.warning(
            "request_id=%s Fallo enviando notificación",
            request_id,
        )

        return JSONResponse(
            status_code=503,
            content={
                "status": "NOTIFICATION_FAILED",
                "detail": "No fue posible enviar el correo",
                "reservation_id": request.reservation_id,
                "request_id": request_id,
            },
        )

    notification_id = str(uuid.uuid4())

    logging.info(
        "request_id=%s Notificación enviada notification_id=%s",
        request_id,
        notification_id,
    )

    return {
        "status": "SENT",
        "notification_id": notification_id,
        "reservation_id": request.reservation_id,
        "email": request.email,
        "delay_ms": delay_ms,
        "request_id": request_id,
    }