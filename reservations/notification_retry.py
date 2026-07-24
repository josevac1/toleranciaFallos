import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx


logger = logging.getLogger(
    "reservations.notification_retry"
)


@dataclass(frozen=True)
class NotificationDeliveryResult:
    """
    Resultado final del envío de una notificación.
    """

    sent: bool
    attempts: int
    last_error: str | None
    last_status_code: int | None


class NotificationRetryPolicy:
    """
    Política de reintentos para el Servicio de Notificaciones.

    Aplica:

    - Timeout por intento.
    - Cantidad máxima de intentos.
    - Backoff exponencial.
    - Límite máximo de espera.
    """

    def __init__(
        self,
        timeout_seconds: float,
        max_attempts: int,
        initial_backoff_seconds: float,
        max_backoff_seconds: float,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds debe ser mayor que cero"
            )

        if max_attempts < 1:
            raise ValueError(
                "max_attempts debe ser al menos uno"
            )

        if initial_backoff_seconds < 0:
            raise ValueError(
                "initial_backoff_seconds no puede ser negativo"
            )

        if max_backoff_seconds < initial_backoff_seconds:
            raise ValueError(
                "max_backoff_seconds no puede ser menor "
                "que initial_backoff_seconds"
            )

        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.initial_backoff_seconds = (
            initial_backoff_seconds
        )
        self.max_backoff_seconds = (
            max_backoff_seconds
        )

    def configuration(self) -> dict[str, Any]:
        """
        Devuelve la configuración actual de la política.
        """

        return {
            "pattern": "retry_with_exponential_backoff_and_fallback",
            "timeout_seconds": self.timeout_seconds,
            "max_attempts": self.max_attempts,
            "initial_backoff_seconds": (
                self.initial_backoff_seconds
            ),
            "max_backoff_seconds": (
                self.max_backoff_seconds
            ),
            "retry_status_codes": [
                500,
                502,
                503,
                504,
            ],
        }

    async def send(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        request_id: str,
    ) -> NotificationDeliveryResult:
        """
        Envía una notificación aplicando reintentos.

        Se reintenta cuando ocurre:

        - Timeout.
        - Error de conexión.
        - Respuesta HTTP 5xx.

        No se reintenta cuando ocurre un error HTTP 4xx,
        porque normalmente representa una solicitud inválida.
        """

        last_error: str | None = None
        last_status_code: int | None = None

        timeout = httpx.Timeout(
            self.timeout_seconds
        )

        async with httpx.AsyncClient(
            timeout=timeout
        ) as client:

            for attempt in range(
                1,
                self.max_attempts + 1,
            ):
                logger.info(
                    "request_id=%s "
                    "notification_retry "
                    "attempt=%s/%s "
                    "url=%s",
                    request_id,
                    attempt,
                    self.max_attempts,
                    url,
                )

                try:
                    response = await client.post(
                        url,
                        json=payload,
                        headers=headers,
                    )

                    last_status_code = (
                        response.status_code
                    )

                    if 200 <= response.status_code < 300:
                        logger.info(
                            "request_id=%s "
                            "notification_retry "
                            "attempt=%s/%s "
                            "result=success "
                            "status_code=%s",
                            request_id,
                            attempt,
                            self.max_attempts,
                            response.status_code,
                        )

                        return NotificationDeliveryResult(
                            sent=True,
                            attempts=attempt,
                            last_error=None,
                            last_status_code=(
                                response.status_code
                            ),
                        )

                    if 400 <= response.status_code < 500:
                        last_error = (
                            "Notificaciones rechazó la solicitud "
                            f"con HTTP {response.status_code}: "
                            f"{response.text[:200]}"
                        )

                        logger.error(
                            "request_id=%s "
                            "notification_retry "
                            "attempt=%s/%s "
                            "result=non_retryable_error "
                            "status_code=%s",
                            request_id,
                            attempt,
                            self.max_attempts,
                            response.status_code,
                        )

                        return NotificationDeliveryResult(
                            sent=False,
                            attempts=attempt,
                            last_error=last_error,
                            last_status_code=(
                                response.status_code
                            ),
                        )

                    last_error = (
                        "Notificaciones devolvió "
                        f"HTTP {response.status_code}: "
                        f"{response.text[:200]}"
                    )

                    logger.warning(
                        "request_id=%s "
                        "notification_retry "
                        "attempt=%s/%s "
                        "result=retryable_http_error "
                        "status_code=%s",
                        request_id,
                        attempt,
                        self.max_attempts,
                        response.status_code,
                    )

                except httpx.TimeoutException as error:
                    last_error = (
                        "Timeout al llamar a Notificaciones: "
                        f"{error}"
                    )

                    logger.warning(
                        "request_id=%s "
                        "notification_retry "
                        "attempt=%s/%s "
                        "result=timeout",
                        request_id,
                        attempt,
                        self.max_attempts,
                    )

                except httpx.RequestError as error:
                    last_error = (
                        "Error de conexión con Notificaciones: "
                        f"{error}"
                    )

                    logger.warning(
                        "request_id=%s "
                        "notification_retry "
                        "attempt=%s/%s "
                        "result=connection_error "
                        "error=%s",
                        request_id,
                        attempt,
                        self.max_attempts,
                        error,
                    )

                if attempt < self.max_attempts:
                    backoff_seconds = min(
                        self.initial_backoff_seconds
                        * (2 ** (attempt - 1)),
                        self.max_backoff_seconds,
                    )

                    logger.warning(
                        "request_id=%s "
                        "notification_retry "
                        "next_attempt=%s "
                        "backoff_seconds=%.2f",
                        request_id,
                        attempt + 1,
                        backoff_seconds,
                    )

                    await asyncio.sleep(
                        backoff_seconds
                    )

        logger.error(
            "request_id=%s "
            "notification_retry "
            "result=exhausted "
            "attempts=%s "
            "fallback=CONFIRMED_NOTIFICATION_PENDING",
            request_id,
            self.max_attempts,
        )

        return NotificationDeliveryResult(
            sent=False,
            attempts=self.max_attempts,
            last_error=last_error,
            last_status_code=last_status_code,
        )