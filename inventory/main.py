import logging
import os
import time
import uuid

import psycopg
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | inventory | %(levelname)s | %(message)s",
)

app = FastAPI(
    title="Servicio de Inventario",
    version="1.0.0",
)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://tickets_user:tickets_password@postgres-service:5432/tickets_db",
)

# Permite ampliar intencionalmente la ventana de una condición de carrera.
RACE_DELAY_MS = int(os.getenv("RACE_DELAY_MS", "0"))


class InventoryRequest(BaseModel):
    event_id: int = Field(gt=0)


@app.get("/")
def root():
    return {
        "service": "inventory-service",
        "status": "running",
    }


@app.get("/health")
def health():
    return {
        "status": "UP",
        "service": "inventory-service",
    }


@app.get("/inventory/{event_id}")
def get_inventory(event_id: int):
    try:
        with psycopg.connect(DATABASE_URL) as connection:
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
        logging.error("Error consultando inventario: %s", error)

        return JSONResponse(
            status_code=503,
            content={
                "status": "DATABASE_ERROR",
                "detail": "No se pudo consultar el inventario",
            },
        )


@app.post("/inventory/reserve")
def reserve_seat(
    request: InventoryRequest,
    x_request_id: str | None = Header(default=None),
):
    request_id = x_request_id or str(uuid.uuid4())

    logging.info(
        "request_id=%s Solicitud para descontar asiento event_id=%s",
        request_id,
        request.event_id,
    )

    try:
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT available_seats
                    FROM inventory
                    WHERE event_id = %s
                    """,
                    (request.event_id,),
                )

                result = cursor.fetchone()

                if result is None:
                    return JSONResponse(
                        status_code=404,
                        content={
                            "status": "NOT_FOUND",
                            "detail": "Evento no encontrado",
                            "request_id": request_id,
                        },
                    )

                available_seats = result[0]

                if available_seats <= 0:
                    return JSONResponse(
                        status_code=409,
                        content={
                            "status": "SOLD_OUT",
                            "detail": "No existen asientos disponibles",
                            "request_id": request_id,
                        },
                    )

                if RACE_DELAY_MS > 0:
                    time.sleep(RACE_DELAY_MS / 1000)

                new_available_seats = available_seats - 1

                # Implementación inicial deliberadamente sencilla.
                # En producción deberá protegerse contra concurrencia.
                cursor.execute(
                    """
                    UPDATE inventory
                    SET available_seats = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE event_id = %s
                    """,
                    (
                        new_available_seats,
                        request.event_id,
                    ),
                )

            connection.commit()

        logging.info(
            "request_id=%s Asiento reservado. Disponibles=%s",
            request_id,
            new_available_seats,
        )

        return {
            "status": "RESERVED",
            "event_id": request.event_id,
            "available_seats": new_available_seats,
            "request_id": request_id,
        }

    except psycopg.Error as error:
        logging.error(
            "request_id=%s Error de base de datos: %s",
            request_id,
            error,
        )

        return JSONResponse(
            status_code=503,
            content={
                "status": "DATABASE_ERROR",
                "detail": "No se pudo actualizar el inventario",
                "request_id": request_id,
            },
        )


@app.post("/inventory/release")
def release_seat(request: InventoryRequest):
    try:
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE inventory
                    SET available_seats = available_seats + 1,
                        updated_at = CURRENT_TIMESTAMP
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
                            "detail": "Evento no encontrado",
                        },
                    )

            connection.commit()

        return {
            "status": "RELEASED",
            "event_id": request.event_id,
            "available_seats": result[0],
        }

    except psycopg.Error as error:
        logging.error("Error liberando asiento: %s", error)

        return JSONResponse(
            status_code=503,
            content={
                "status": "DATABASE_ERROR",
                "detail": "No se pudo liberar el asiento",
            },
        )