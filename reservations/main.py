import logging
import math
import os
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

import httpx
import psycopg
from circuit_breaker import (
    AsyncCircuitBreaker,
    CircuitBreakerOpenError,
)
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from notification_retry import (
    NotificationRetryPolicy,
)
from pydantic import BaseModel, Field


# ============================================================
# CONFIGURACIÓN DE LOGS
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | reservations | "
        "%(levelname)s | %(message)s"
    ),
)


# ============================================================
# APLICACIÓN
# ============================================================

app = FastAPI(
    title="Servicio de Reservas",
    version="1.2.0",
)


# ============================================================
# VARIABLES DE ENTORNO
# ============================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    (
        "postgresql://tickets_user:tickets_password"
        "@postgres-service:5432/tickets_db"
    ),
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


# ============================================================
# CONFIGURACIÓN DEL CIRCUIT BREAKER DE PAGOS
# ============================================================

PAYMENT_TIMEOUT_SECONDS = float(
    os.getenv(
        "PAYMENT_TIMEOUT_SECONDS",
        "3",
    )
)

PAYMENT_CB_FAILURE_THRESHOLD = int(
    os.getenv(
        "PAYMENT_CB_FAILURE_THRESHOLD",
        "2",
    )
)

PAYMENT_CB_RECOVERY_SECONDS = float(
    os.getenv(
        "PAYMENT_CB_RECOVERY_SECONDS",
        "15",
    )
)


# ============================================================
# CONFIGURACIÓN DE RETRIES DE NOTIFICACIONES
# ============================================================

NOTIFICATION_TIMEOUT_SECONDS = float(
    os.getenv(
        "NOTIFICATION_TIMEOUT_SECONDS",
        "2",
    )
)

NOTIFICATION_MAX_ATTEMPTS = int(
    os.getenv(
        "NOTIFICATION_MAX_ATTEMPTS",
        "3",
    )
)

NOTIFICATION_INITIAL_BACKOFF_SECONDS = float(
    os.getenv(
        "NOTIFICATION_INITIAL_BACKOFF_SECONDS",
        "1",
    )
)

NOTIFICATION_MAX_BACKOFF_SECONDS = float(
    os.getenv(
        "NOTIFICATION_MAX_BACKOFF_SECONDS",
        "4",
    )
)


# ============================================================
# MECANISMOS DE RESILIENCIA
# ============================================================

payment_circuit_breaker = AsyncCircuitBreaker(
    name="payments-service",
    failure_threshold=(
        PAYMENT_CB_FAILURE_THRESHOLD
    ),
    recovery_timeout_seconds=(
        PAYMENT_CB_RECOVERY_SECONDS
    ),
)

notification_retry_policy = NotificationRetryPolicy(
    timeout_seconds=(
        NOTIFICATION_TIMEOUT_SECONDS
    ),
    max_attempts=(
        NOTIFICATION_MAX_ATTEMPTS
    ),
    initial_backoff_seconds=(
        NOTIFICATION_INITIAL_BACKOFF_SECONDS
    ),
    max_backoff_seconds=(
        NOTIFICATION_MAX_BACKOFF_SECONDS
    ),
)


# ============================================================
# MODELOS
# ============================================================

class ReservationRequest(BaseModel):
    user_id: str = Field(
        min_length=1,
        max_length=100,
    )

    event_id: int = Field(
        gt=0,
    )

    email: str = Field(
        min_length=3,
        max_length=150,
    )

    amount: float = Field(
        gt=0,
    )


# ============================================================
# ENDPOINTS DE ESTADO
# ============================================================

@app.get("/")
def root():
    return {
        "service": "reservations-service",
        "status": "running",
        "version": "1.2.0",
        "resilience_patterns": [
            "payment_circuit_breaker",
            "notification_retry_with_backoff",
            "notification_fallback",
        ],
    }


@app.get("/health")
def health():
    return {
        "status": "UP",
        "service": "reservations-service",
    }


@app.get("/resilience/payment-circuit-breaker")
async def payment_circuit_breaker_status():
    """
    Devuelve el estado del Circuit Breaker de Pagos.
    """

    snapshot = await payment_circuit_breaker.snapshot()

    return asdict(snapshot)


@app.get("/resilience/notification-retry-policy")
def notification_retry_policy_status():
    """
    Devuelve la configuración de retries
    aplicada a Notificaciones.
    """

    return notification_retry_policy.configuration()


# ============================================================
# BASE DE DATOS
# ============================================================

def save_reservation(
    reservation_id: str,
    request: ReservationRequest,
    payment_id: str,
    status: str,
) -> None:
    """
    Guarda una nueva reserva en PostgreSQL.
    """

    with psycopg.connect(
        DATABASE_URL
    ) as connection:

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
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
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


def update_reservation_status(
    reservation_id: str,
    status: str,
) -> None:
    """
    Actualiza el estado de una reserva ya creada.
    """

    with psycopg.connect(
        DATABASE_URL
    ) as connection:

        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE reservations
                SET status = %s
                WHERE id = %s
                """,
                (
                    status,
                    reservation_id,
                ),
            )

        connection.commit()


# ============================================================
# COMPENSACIÓN DEL INVENTARIO
# ============================================================

async def release_inventory(
    event_id: int,
    request_id: str,
) -> None:
    """
    Libera un asiento cuando el pago falla.

    Esta operación funciona como una compensación:
    revierte la reserva temporal realizada previamente.
    """

    try:
        async with httpx.AsyncClient(
            timeout=5.0
        ) as client:

            response = await client.post(
                (
                    f"{INVENTORY_URL}"
                    "/inventory/release"
                ),
                json={
                    "event_id": event_id,
                },
                headers={
                    "X-Request-ID": request_id,
                },
            )

            response.raise_for_status()

        logging.info(
            "request_id=%s "
            "Asiento liberado mediante compensación",
            request_id,
        )

    except (
        httpx.RequestError,
        httpx.HTTPStatusError,
    ) as error:

        logging.error(
            "request_id=%s "
            "No se pudo liberar el asiento: %s",
            request_id,
            error,
        )


# ============================================================
# CIRCUIT BREAKER DE PAGOS
# ============================================================

async def log_payment_breaker_state(
    request_id: str,
    event: str,
) -> None:
    """
    Registra el estado actual del Circuit Breaker.
    """

    snapshot = await payment_circuit_breaker.snapshot()

    logging.warning(
        "request_id=%s "
        "payment_circuit_breaker "
        "event=%s "
        "state=%s "
        "failures=%s/%s "
        "retry_after=%.2f",
        request_id,
        event,
        snapshot.state,
        snapshot.failure_count,
        snapshot.failure_threshold,
        snapshot.retry_after_seconds,
    )


async def call_payment(
    reservation_id: str,
    request: ReservationRequest,
    request_id: str,
) -> httpx.Response:
    """
    Llama al Servicio de Pagos aplicando:

    - Timeout.
    - Circuit Breaker.
    - Registro de fallos.
    """

    await payment_circuit_breaker.before_call()

    try:
        timeout = httpx.Timeout(
            PAYMENT_TIMEOUT_SECONDS
        )

        async with httpx.AsyncClient(
            timeout=timeout
        ) as client:

            payment_response = await client.post(
                (
                    f"{PAYMENTS_URL}"
                    "/payments/charge"
                ),
                json={
                    "reservation_id": reservation_id,
                    "user_id": request.user_id,
                    "amount": request.amount,
                },
                headers={
                    "X-Request-ID": request_id,
                },
            )

    except (
        httpx.TimeoutException,
        httpx.RequestError,
    ):
        await payment_circuit_breaker.record_failure()

        await log_payment_breaker_state(
            request_id=request_id,
            event="technical_failure",
        )

        raise

    if payment_response.status_code >= 500:
        await payment_circuit_breaker.record_failure()

        await log_payment_breaker_state(
            request_id=request_id,
            event="http_5xx",
        )

    else:
        await payment_circuit_breaker.record_success()

        await log_payment_breaker_state(
            request_id=request_id,
            event="success",
        )

    return payment_response


# ============================================================
# CREACIÓN DE RESERVAS
# ============================================================

@app.post("/reservations")
async def create_reservation(
    request: ReservationRequest,
    x_request_id: str | None = Header(
        default=None
    ),
):
    request_id = (
        x_request_id
        or str(uuid.uuid4())
    )

    reservation_id = str(
        uuid.uuid4()
    )

    logging.info(
        "request_id=%s "
        "Iniciando reserva "
        "event_id=%s "
        "user_id=%s",
        request_id,
        request.event_id,
        request.user_id,
    )

    # ========================================================
    # PASO 1: RESERVAR EL ASIENTO
    # ========================================================

    try:
        async with httpx.AsyncClient(
            timeout=5.0
        ) as client:

            inventory_response = await client.post(
                (
                    f"{INVENTORY_URL}"
                    "/inventory/reserve"
                ),
                json={
                    "event_id": request.event_id,
                },
                headers={
                    "X-Request-ID": request_id,
                },
            )

    except httpx.TimeoutException:
        logging.error(
            "request_id=%s "
            "Inventario agotó el tiempo de espera",
            request_id,
        )

        return JSONResponse(
            status_code=504,
            content={
                "status": "REJECTED",
                "detail": (
                    "El Inventario tardó demasiado "
                    "en responder"
                ),
                "request_id": request_id,
            },
        )

    except httpx.RequestError as error:
        logging.error(
            "request_id=%s "
            "Inventario no disponible: %s",
            request_id,
            error,
        )

        return JSONResponse(
            status_code=503,
            content={
                "status": "REJECTED",
                "detail": (
                    "No se pudo verificar "
                    "la disponibilidad"
                ),
                "request_id": request_id,
            },
        )

    if inventory_response.status_code != 200:
        try:
            inventory_error = (
                inventory_response.json()
            )

        except ValueError:
            inventory_error = {
                "status": "INVENTORY_ERROR",
                "detail": (
                    "Inventario devolvió "
                    "una respuesta no válida"
                ),
                "request_id": request_id,
            }

        return JSONResponse(
            status_code=(
                inventory_response.status_code
            ),
            content=inventory_error,
        )

    # ========================================================
    # PASO 2: PROCESAR EL PAGO
    # ========================================================

    try:
        payment_response = await call_payment(
            reservation_id=reservation_id,
            request=request,
            request_id=request_id,
        )

    except CircuitBreakerOpenError as error:
        await release_inventory(
            event_id=request.event_id,
            request_id=request_id,
        )

        logging.warning(
            "request_id=%s "
            "Circuit Breaker de Pagos abierto "
            "retry_after=%.2f",
            request_id,
            error.retry_after_seconds,
        )

        return JSONResponse(
            status_code=503,
            headers={
                "Retry-After": str(
                    max(
                        1,
                        math.ceil(
                            error.retry_after_seconds
                        ),
                    )
                )
            },
            content={
                "status": "PAYMENT_CIRCUIT_OPEN",
                "detail": (
                    "La pasarela de pagos está "
                    "temporalmente bloqueada"
                ),
                "retry_after_seconds": round(
                    error.retry_after_seconds,
                    2,
                ),
                "request_id": request_id,
            },
        )

    except httpx.TimeoutException:
        await release_inventory(
            event_id=request.event_id,
            request_id=request_id,
        )

        logging.error(
            "request_id=%s "
            "El pago agotó el tiempo de espera",
            request_id,
        )

        return JSONResponse(
            status_code=504,
            content={
                "status": "PAYMENT_TIMEOUT",
                "detail": (
                    "La pasarela de pagos "
                    "tardó demasiado"
                ),
                "request_id": request_id,
            },
        )

    except httpx.RequestError as error:
        await release_inventory(
            event_id=request.event_id,
            request_id=request_id,
        )

        logging.error(
            "request_id=%s "
            "Error llamando a Pagos: %s",
            request_id,
            error,
        )

        return JSONResponse(
            status_code=503,
            content={
                "status": "PAYMENT_UNAVAILABLE",
                "detail": (
                    "La pasarela de pagos "
                    "no está disponible"
                ),
                "request_id": request_id,
            },
        )

    if payment_response.status_code != 200:
        await release_inventory(
            event_id=request.event_id,
            request_id=request_id,
        )

        try:
            payment_error = (
                payment_response.json()
            )

        except ValueError:
            payment_error = {
                "status": "PAYMENT_ERROR",
                "detail": (
                    "Pagos devolvió "
                    "una respuesta no válida"
                ),
                "request_id": request_id,
            }

        return JSONResponse(
            status_code=(
                payment_response.status_code
            ),
            content=payment_error,
        )

    payment_data = payment_response.json()
    payment_id = payment_data["payment_id"]

    # ========================================================
    # PASO 3: GUARDAR LA RESERVA
    # ========================================================

    try:
        save_reservation(
            reservation_id=reservation_id,
            request=request,
            payment_id=payment_id,
            status="CONFIRMED",
        )

    except psycopg.Error as error:
        logging.error(
            "request_id=%s "
            "Error guardando la reserva: %s",
            request_id,
            error,
        )

        return JSONResponse(
            status_code=503,
            content={
                "status": "DATABASE_ERROR",
                "detail": (
                    "No se pudo guardar "
                    "la reserva"
                ),
                "request_id": request_id,
            },
        )

    # ========================================================
    # PASO 4: NOTIFICAR CON RETRIES Y BACKOFF
    # ========================================================

    notification_result = (
        await notification_retry_policy.send(
            url=(
                f"{NOTIFICATIONS_URL}"
                "/notifications/send"
            ),
            payload={
                "reservation_id": reservation_id,
                "email": request.email,
                "message": (
                    "Su reserva fue confirmada "
                    "correctamente"
                ),
            },
            headers={
                "X-Request-ID": request_id,
            },
            request_id=request_id,
        )
    )

    notification_sent = (
        notification_result.sent
    )

    notification_fallback_used = (
        not notification_sent
    )

    database_status_updated = True

    if notification_sent:
        final_status = "CONFIRMED"

    else:
        final_status = (
            "CONFIRMED_NOTIFICATION_PENDING"
        )

        try:
            update_reservation_status(
                reservation_id=reservation_id,
                status=final_status,
            )

        except psycopg.Error as error:
            database_status_updated = False

            logging.error(
                "request_id=%s "
                "No se pudo actualizar el estado "
                "de notificación pendiente: %s",
                request_id,
                error,
            )

        logging.warning(
            "request_id=%s "
            "notification_fallback "
            "reservation_id=%s "
            "status=%s "
            "attempts=%s "
            "last_error=%s",
            request_id,
            reservation_id,
            final_status,
            notification_result.attempts,
            notification_result.last_error,
        )

    logging.info(
        "request_id=%s "
        "Reserva completada "
        "reservation_id=%s "
        "status=%s "
        "notification_attempts=%s",
        request_id,
        reservation_id,
        final_status,
        notification_result.attempts,
    )

    return {
        "status": final_status,
        "reservation_id": reservation_id,
        "payment_id": payment_id,
        "event_id": request.event_id,
        "notification_sent": (
            notification_sent
        ),
        "notification_attempts": (
            notification_result.attempts
        ),
        "notification_fallback_used": (
            notification_fallback_used
        ),
        "notification_last_error": (
            notification_result.last_error
        ),
        "notification_last_status_code": (
            notification_result.last_status_code
        ),
        "database_status_updated": (
            database_status_updated
        ),
        "request_id": request_id,
    }