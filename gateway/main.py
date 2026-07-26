import asyncio
import logging
import os
import time
import uuid

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | gateway | %(levelname)s | %(message)s",
)

app = FastAPI(
    title="API Gateway - Sistema de Entradas",
    version="1.0.0",
)

RESERVATIONS_URL = os.getenv(
    "RESERVATIONS_URL",
    "http://reservations-service:8000",
)

INVENTORY_URL = os.getenv(
    "INVENTORY_URL",
    "http://inventory-service:8000",
)

RATE_LIMIT_REQUESTS_PER_SECOND = float(
    os.getenv("RATE_LIMIT_REQUESTS_PER_SECOND", "25")
)
RATE_LIMIT_BURST = int(os.getenv("RATE_LIMIT_BURST", "40"))
MAX_CONCURRENT_REQUESTS = int(
    os.getenv("MAX_CONCURRENT_REQUESTS", "20")
)


class TokenBucket:
    def __init__(self, rate: float, capacity: int) -> None:
        if rate <= 0 or capacity < 1:
            raise ValueError("Configuración de rate limit inválida")
        self.rate = rate
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.updated_at = time.monotonic()
        self.lock = asyncio.Lock()

    async def allow(self) -> bool:
        async with self.lock:
            now = time.monotonic()
            elapsed = now - self.updated_at
            self.updated_at = now
            self.tokens = min(
                self.capacity,
                self.tokens + elapsed * self.rate,
            )
            if self.tokens < 1:
                return False
            self.tokens -= 1
            return True


rate_limiter = TokenBucket(
    rate=RATE_LIMIT_REQUESTS_PER_SECOND,
    capacity=RATE_LIMIT_BURST,
)
concurrency_lock = asyncio.Lock()
active_requests = 0


@app.middleware("http")
async def overload_protection(request: Request, call_next):
    global active_requests

    if request.url.path in {"/", "/health", "/resilience/overload"}:
        return await call_next(request)

    if not await rate_limiter.allow():
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": "1"},
            content={
                "status": "RATE_LIMITED",
                "detail": "Capacidad temporal del Gateway agotada",
            },
        )

    async with concurrency_lock:
        if active_requests >= MAX_CONCURRENT_REQUESTS:
            return JSONResponse(
                status_code=503,
                headers={"Retry-After": "1"},
                content={
                    "status": "OVERLOADED",
                    "detail": "Límite de concurrencia alcanzado",
                },
            )
        active_requests += 1

    try:
        return await call_next(request)
    finally:
        async with concurrency_lock:
            active_requests -= 1


class ReservationRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=100)
    event_id: int = Field(gt=0)
    email: str = Field(min_length=3, max_length=150)
    amount: float = Field(gt=0)


@app.get("/")
def root():
    return {
        "service": "api-gateway",
        "status": "running",
        "resilience_patterns": [
            "token_bucket_rate_limit",
            "bounded_concurrency",
            "horizontal_pod_autoscaling",
        ],
    }


@app.get("/health")
def health():
    return {
        "status": "UP",
        "service": "api-gateway",
    }


@app.get("/resilience/overload")
async def overload_status():
    async with concurrency_lock:
        current_active = active_requests
    return {
        "pattern": "rate_limit_and_bulkhead",
        "requests_per_second": RATE_LIMIT_REQUESTS_PER_SECOND,
        "burst": RATE_LIMIT_BURST,
        "max_concurrent_requests": MAX_CONCURRENT_REQUESTS,
        "active_requests": current_active,
    }


@app.post("/api/reservations")
async def create_reservation(
    reservation: ReservationRequest,
    request: Request,
):
    request_id = request.headers.get(
        "X-Request-ID",
        str(uuid.uuid4()),
    )

    payload = reservation.model_dump()

    logging.info(
        "request_id=%s Nueva solicitud de reserva",
        request_id,
    )

    try:
        async with httpx.AsyncClient(timeout=35.0) as client:
            response = await client.post(
                f"{RESERVATIONS_URL}/reservations",
                json=payload,
                headers={"X-Request-ID": request_id},
            )

        try:
            content = response.json()
        except ValueError:
            content = {
                "detail": "El Servicio de Reservas devolvió una respuesta inválida"
            }

        return JSONResponse(
            status_code=response.status_code,
            content=content,
            headers={"X-Request-ID": request_id},
        )

    except httpx.TimeoutException:
        logging.error(
            "request_id=%s Timeout comunicándose con Reservas",
            request_id,
        )

        return JSONResponse(
            status_code=504,
            content={
                "status": "ERROR",
                "detail": "El Servicio de Reservas tardó demasiado en responder",
                "request_id": request_id,
            },
        )

    except httpx.RequestError as error:
        logging.error(
            "request_id=%s Servicio de Reservas no disponible: %s",
            request_id,
            error,
        )

        return JSONResponse(
            status_code=503,
            content={
                "status": "ERROR",
                "detail": "Servicio de Reservas no disponible",
                "request_id": request_id,
            },
        )


@app.get("/api/inventory/{event_id}")
async def get_inventory(event_id: int):
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{INVENTORY_URL}/inventory/{event_id}"
            )

        return JSONResponse(
            status_code=response.status_code,
            content=response.json(),
        )

    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content={
                "status": "ERROR",
                "detail": "Inventario tardó demasiado en responder",
            },
        )

    except httpx.RequestError:
        return JSONResponse(
            status_code=503,
            content={
                "status": "ERROR",
                "detail": "Servicio de Inventario no disponible",
            },
        )
