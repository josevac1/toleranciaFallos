import asyncio
import logging
import os
import random
import uuid

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | payments | %(levelname)s | %(message)s",
)

app = FastAPI(
    title="Servicio de Pagos Simulado",
    version="1.0.0",
)

MIN_DELAY_MS = int(os.getenv("MIN_DELAY_MS", "500"))
MAX_DELAY_MS = int(os.getenv("MAX_DELAY_MS", "2500"))
FAILURE_RATE = float(os.getenv("FAILURE_RATE", "0.15"))


class PaymentRequest(BaseModel):
    reservation_id: str
    user_id: str
    amount: float = Field(gt=0)


@app.get("/")
def root():
    return {
        "service": "payments-service",
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
        "service": "payments-service",
    }


@app.post("/payments/charge")
async def charge(
    request: PaymentRequest,
    x_request_id: str | None = Header(default=None),
):
    request_id = x_request_id or str(uuid.uuid4())

    delay_ms = random.randint(MIN_DELAY_MS, MAX_DELAY_MS)

    logging.info(
        "request_id=%s Procesando pago de %.2f con latencia=%sms",
        request_id,
        request.amount,
        delay_ms,
    )

    await asyncio.sleep(delay_ms / 1000)

    if random.random() < FAILURE_RATE:
        logging.warning(
            "request_id=%s Pago rechazado por fallo simulado",
            request_id,
        )

        return JSONResponse(
            status_code=503,
            content={
                "status": "PAYMENT_FAILED",
                "detail": "La pasarela simuló un fallo temporal",
                "request_id": request_id,
            },
        )

    payment_id = str(uuid.uuid4())

    logging.info(
        "request_id=%s Pago aprobado payment_id=%s",
        request_id,
        payment_id,
    )

    return {
        "status": "APPROVED",
        "payment_id": payment_id,
        "reservation_id": request.reservation_id,
        "amount": request.amount,
        "delay_ms": delay_ms,
        "request_id": request_id,
    }