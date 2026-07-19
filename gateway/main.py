import logging
import os
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
    }


@app.get("/health")
def health():
    return {
        "status": "UP",
        "service": "api-gateway",
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