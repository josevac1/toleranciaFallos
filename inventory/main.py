import logging
import os
import time
import uuid

import psycopg
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


# ============================================================
# CONFIGURACIÓN DE LOGS
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | inventory | "
        "%(levelname)s | %(message)s"
    ),
)


# ============================================================
# APLICACIÓN
# ============================================================

app = FastAPI(
    title="Servicio de Inventario",
    version="1.1.0",
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

# Esta variable solo se utiliza para ampliar intencionalmente
# la ventana de concurrencia durante la demostración.
#
# La espera ocurre ANTES de la operación atómica.
RACE_DELAY_MS = int(
    os.getenv(
        "RACE_DELAY_MS",
        "0",
    )
)


# ============================================================
# MODELOS
# ============================================================

class InventoryRequest(BaseModel):
    event_id: int = Field(gt=0)


# ============================================================
# ENDPOINTS DE ESTADO
# ============================================================

@app.get("/")
def root():
    return {
        "service": "inventory-service",
        "status": "running",
        "version": "1.1.0",
        "resilience_patterns": [
            "atomic_inventory_update",
            "database_constraint",
            "kubernetes_redundancy",
        ],
    }


@app.get("/health")
def health():
    return {
        "status": "UP",
        "service": "inventory-service",
    }


@app.get("/resilience/atomic-reservation")
def atomic_reservation_status():
    """
    Muestra la configuración del mecanismo
    de protección contra condiciones de carrera.
    """

    return {
        "pattern": "atomic_database_update",
        "enabled": True,
        "database": "PostgreSQL",
        "race_delay_ms": RACE_DELAY_MS,
        "operation": (
            "UPDATE inventory "
            "SET available_seats = available_seats - 1 "
            "WHERE event_id = ? "
            "AND available_seats > 0 "
            "RETURNING available_seats"
        ),
        "guarantee": (
            "Solo una transacción puede descontar "
            "el último asiento disponible"
        ),
    }


# ============================================================
# CONSULTA DE INVENTARIO
# ============================================================

@app.get("/inventory/{event_id}")
def get_inventory(event_id: int):
    try:
        with psycopg.connect(
            DATABASE_URL
        ) as connection:

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        e.id,
                        e.name,
                        i.available_seats
                    FROM events e
                    INNER JOIN inventory i
                        ON e.id = i.event_id
                    WHERE e.id = %s
                    """,
                    (event_id,),
                )

                result = cursor.fetchone()

        if result is None:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "NOT_FOUND",
                    "detail": "Evento no encontrado",
                },
            )

        return {
            "event_id": result[0],
            "event_name": result[1],
            "available_seats": result[2],
        }

    except psycopg.Error as error:
        logging.error(
            "Error consultando inventario: %s",
            error,
        )

        return JSONResponse(
            status_code=503,
            content={
                "status": "DATABASE_ERROR",
                "detail": (
                    "No se pudo consultar "
                    "el inventario"
                ),
            },
        )


# ============================================================
# RESERVA ATÓMICA DE ASIENTO
# ============================================================

@app.post("/inventory/reserve")
def reserve_seat(
    request: InventoryRequest,
    x_request_id: str | None = Header(
        default=None
    ),
):
    request_id = (
        x_request_id
        or str(uuid.uuid4())
    )

    logging.info(
        "request_id=%s "
        "Solicitud para descontar asiento "
        "event_id=%s "
        "atomic_update=true",
        request_id,
        request.event_id,
    )

    try:
        with psycopg.connect(
            DATABASE_URL
        ) as connection:

            with connection.cursor() as cursor:

                # La espera amplía la posibilidad de que
                # dos clientes lleguen al mismo tiempo.
                #
                # No realiza una lectura previa y no mantiene
                # ningún valor de disponibilidad en memoria.
                if RACE_DELAY_MS > 0:
                    logging.warning(
                        "request_id=%s "
                        "Aplicando retraso de concurrencia "
                        "race_delay_ms=%s",
                        request_id,
                        RACE_DELAY_MS,
                    )

                    time.sleep(
                        RACE_DELAY_MS / 1000
                    )

                # =================================================
                # OPERACIÓN ATÓMICA
                # =================================================
                #
                # PostgreSQL comprueba que exista disponibilidad
                # y descuenta el asiento en una sola instrucción.
                #
                # Cuando dos transacciones compiten por el último
                # asiento, una modifica la fila y la otra obtiene
                # cero filas.
                cursor.execute(
                    """
                    UPDATE inventory
                    SET
                        available_seats =
                            available_seats - 1,
                        updated_at =
                            CURRENT_TIMESTAMP
                    WHERE event_id = %s
                      AND available_seats > 0
                    RETURNING available_seats
                    """,
                    (request.event_id,),
                )

                result = cursor.fetchone()

                if result is None:
                    # La operación no modificó ninguna fila.
                    # Se comprueba si el evento no existe o
                    # si ya no quedan asientos.
                    cursor.execute(
                        """
                        SELECT available_seats
                        FROM inventory
                        WHERE event_id = %s
                        """,
                        (request.event_id,),
                    )

                    current_inventory = (
                        cursor.fetchone()
                    )

                    if current_inventory is None:
                        logging.warning(
                            "request_id=%s "
                            "Evento inexistente "
                            "event_id=%s",
                            request_id,
                            request.event_id,
                        )

                        return JSONResponse(
                            status_code=404,
                            content={
                                "status": "NOT_FOUND",
                                "detail": (
                                    "Evento no encontrado"
                                ),
                                "event_id": (
                                    request.event_id
                                ),
                                "request_id": (
                                    request_id
                                ),
                            },
                        )

                    logging.warning(
                        "request_id=%s "
                        "Reserva rechazada "
                        "por falta de asientos "
                        "event_id=%s "
                        "available_seats=%s",
                        request_id,
                        request.event_id,
                        current_inventory[0],
                    )

                    return JSONResponse(
                        status_code=409,
                        content={
                            "status": "SOLD_OUT",
                            "detail": (
                                "No existen asientos "
                                "disponibles"
                            ),
                            "event_id": (
                                request.event_id
                            ),
                            "available_seats": (
                                current_inventory[0]
                            ),
                            "request_id": request_id,
                        },
                    )

                new_available_seats = result[0]

            connection.commit()

        logging.info(
            "request_id=%s "
            "Asiento reservado mediante "
            "actualización atómica "
            "event_id=%s "
            "available_seats=%s",
            request_id,
            request.event_id,
            new_available_seats,
        )

        return {
            "status": "RESERVED",
            "event_id": request.event_id,
            "available_seats": (
                new_available_seats
            ),
            "atomic_update": True,
            "request_id": request_id,
        }

    except psycopg.Error as error:
        logging.error(
            "request_id=%s "
            "Error de base de datos: %s",
            request_id,
            error,
        )

        return JSONResponse(
            status_code=503,
            content={
                "status": "DATABASE_ERROR",
                "detail": (
                    "No se pudo actualizar "
                    "el inventario"
                ),
                "request_id": request_id,
            },
        )


# ============================================================
# LIBERACIÓN ATÓMICA DEL ASIENTO
# ============================================================

@app.post("/inventory/release")
def release_seat(
    request: InventoryRequest,
    x_request_id: str | None = Header(
        default=None
    ),
):
    request_id = (
        x_request_id
        or str(uuid.uuid4())
    )

    try:
        with psycopg.connect(
            DATABASE_URL
        ) as connection:

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE inventory
                    SET
                        available_seats =
                            available_seats + 1,
                        updated_at =
                            CURRENT_TIMESTAMP
                    WHERE event_id = %s
                    RETURNING available_seats
                    """,
                    (request.event_id,),
                )

                result = cursor.fetchone()

                if result is None:
                    return JSONResponse(
                        status_code=404,
                        content={
                            "status": "NOT_FOUND",
                            "detail": (
                                "Evento no encontrado"
                            ),
                            "event_id": (
                                request.event_id
                            ),
                            "request_id": request_id,
                        },
                    )

            connection.commit()

        logging.info(
            "request_id=%s "
            "Asiento liberado "
            "event_id=%s "
            "available_seats=%s",
            request_id,
            request.event_id,
            result[0],
        )

        return {
            "status": "RELEASED",
            "event_id": request.event_id,
            "available_seats": result[0],
            "request_id": request_id,
        }

    except psycopg.Error as error:
        logging.error(
            "request_id=%s "
            "Error liberando asiento: %s",
            request_id,
            error,
        )

        return JSONResponse(
            status_code=503,
            content={
                "status": "DATABASE_ERROR",
                "detail": (
                    "No se pudo liberar "
                    "el asiento"
                ),
                "request_id": request_id,
            },
        )