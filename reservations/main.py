import logging
import os
import uuid
from datetime import datetime, timezone

import httpx
import psycopg
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | reservations | %(levelname)s | %(message)s",
)

app = FastAPI(
    title="Servicio de Reservas",
    version="1.0.0",
)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://tickets_user:tickets_password@postgres-service:5432/tickets_db",
)

INVENTORY_URL = os.getenv(
    "INVENTORY_URL",
    "http://inventory-service:8000",
)

PAYMENTS_URL = os.getenv(
    "PAYMENTS_URL",
    "http://payments-service:8000",
)

NOTIFICATIONS_URL = os.getenv(
    "NOTIFICATIONS_URL",
    "http://notifications-service:8000",
)


class ReservationRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=100)
    event_id: int = Field(gt=0)
    email: str = Field(min_length=3, max_length=150)
    amount: float = Field(gt=0)


@app.get("/")
def root():
    return {
        "service": "reservations-service",
        "status": "running",
    }


@app.get("/health")
def health():
    return {
        "status": "UP",
        "service": "reservations-service",
    }


def save_reservation(
    reservation_id: str,
    request: ReservationRequest,
    payment_id: str,
    status: str,
):
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO reservations (
                    id,
                    user_id,
                    event_id,
                    email,
                    amount,
                    payment_id,
                    status,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    reservation_id,
                    request.user_id,
                    request.event_id,
                    request.email,
                    request.amount,
                    payment_id,
                    status,
                    datetime.now(timezone.utc),
                ),
            )

        connection.commit()


async def release_inventory(
    event_id: int,
    request_id: str,
):
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{INVENTORY_URL}/inventory/release",
                json={"event_id": event_id},
                headers={"X-Request-ID": request_id},
            )

        logging.info(
            "request_id=%s Asiento liberado",
            request_id,
        )

    except httpx.RequestError as error:
        logging.error(
            "request_id=%s No se pudo liberar el asiento: %s",
            request_id,
            error,
        )


@app.post("/reservations")
async def create_reservation(
    request: ReservationRequest,
    x_request_id: str | None = Header(default=None),
):
    request_id = x_request_id or str(uuid.uuid4())
    reservation_id = str(uuid.uuid4())

    logging.info(
        "request_id=%s Iniciando reserva event_id=%s user_id=%s",
        request_id,
        request.event_id,
        request.user_id,
    )

    # ---------------------------------------------------------
    # PASO 1: reservar asiento en Inventario
    # ---------------------------------------------------------
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            inventory_response = await client.post(
                f"{INVENTORY_URL}/inventory/reserve",
                json={"event_id": request.event_id},
                headers={"X-Request-ID": request_id},
            )

    except httpx.TimeoutException:
        logging.error(
            "request_id=%s Inventario agotó el tiempo de espera",
            request_id,
        )

        return JSONResponse(
            status_code=504,
            content={
                "status": "REJECTED",
                "detail": "El Inventario tardó demasiado en responder",
                "request_id": request_id,
            },
        )

    except httpx.RequestError:
        logging.error(
            "request_id=%s Inventario no disponible",
            request_id,
        )

        return JSONResponse(
            status_code=503,
            content={
                "status": "REJECTED",
                "detail": "No se pudo verificar la disponibilidad",
                "request_id": request_id,
            },
        )

    if inventory_response.status_code != 200:
        return JSONResponse(
            status_code=inventory_response.status_code,
            content=inventory_response.json(),
        )

    # ---------------------------------------------------------
    # PASO 2: procesar pago
    # ---------------------------------------------------------
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            payment_response = await client.post(
                f"{PAYMENTS_URL}/payments/charge",
                json={
                    "reservation_id": reservation_id,
                    "user_id": request.user_id,
                    "amount": request.amount,
                },
                headers={"X-Request-ID": request_id},
            )

    except httpx.TimeoutException:
        await release_inventory(request.event_id, request_id)

        logging.error(
            "request_id=%s El pago agotó el tiempo de espera",
            request_id,
        )

        return JSONResponse(
            status_code=504,
            content={
                "status": "PAYMENT_TIMEOUT",
                "detail": "La pasarela de pagos tardó demasiado",
                "request_id": request_id,
            },
        )

    except httpx.RequestError:
        await release_inventory(request.event_id, request_id)

        return JSONResponse(
            status_code=503,
            content={
                "status": "PAYMENT_UNAVAILABLE",
                "detail": "La pasarela de pagos no está disponible",
                "request_id": request_id,
            },
        )

    if payment_response.status_code != 200:
        await release_inventory(request.event_id, request_id)

        return JSONResponse(
            status_code=payment_response.status_code,
            content=payment_response.json(),
        )

    payment_data = payment_response.json()
    payment_id = payment_data["payment_id"]

    # ---------------------------------------------------------
    # PASO 3: guardar reserva en PostgreSQL
    # ---------------------------------------------------------
    try:
        save_reservation(
            reservation_id=reservation_id,
            request=request,
            payment_id=payment_id,
            status="CONFIRMED",
        )

    except psycopg.Error as error:
        logging.error(
            "request_id=%s Error guardando la reserva: %s",
            request_id,
            error,
        )

        return JSONResponse(
            status_code=503,
            content={
                "status": "DATABASE_ERROR",
                "detail": "No se pudo guardar la reserva",
                "request_id": request_id,
            },
        )

    # ---------------------------------------------------------
    # PASO 4: enviar notificación
    # La caída de Notificaciones no cancela la compra.
    # ---------------------------------------------------------
    notification_sent = True

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            notification_response = await client.post(
                f"{NOTIFICATIONS_URL}/notifications/send",
                json={
                    "reservation_id": reservation_id,
                    "email": request.email,
                    "message": "Su reserva fue confirmada correctamente",
                },
                headers={"X-Request-ID": request_id},
            )

        if notification_response.status_code != 200:
            notification_sent = False

    except httpx.RequestError:
        notification_sent = False

    final_status = (
        "CONFIRMED"
        if notification_sent
        else "CONFIRMED_NOTIFICATION_PENDING"
    )

    logging.info(
        "request_id=%s Reserva completada reservation_id=%s status=%s",
        request_id,
        reservation_id,
        final_status,
    )

    return {
        "status": final_status,
        "reservation_id": reservation_id,
        "payment_id": payment_id,
        "event_id": request.event_id,
        "notification_sent": notification_sent,
        "request_id": request_id,
    }