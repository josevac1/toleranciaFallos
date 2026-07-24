import asyncio
import math
import time
from dataclasses import dataclass


class CircuitBreakerOpenError(Exception):
    """Se produce cuando el Circuit Breaker no permite una llamada."""

    def __init__(self, retry_after_seconds: float):
        self.retry_after_seconds = max(0.0, retry_after_seconds)

        super().__init__(
            "Circuit Breaker abierto. Reintentar en "
            f"{math.ceil(self.retry_after_seconds)} segundos."
        )


@dataclass(frozen=True)
class CircuitBreakerSnapshot:
    name: str
    state: str
    failure_count: int
    failure_threshold: int
    recovery_timeout_seconds: float
    retry_after_seconds: float
    half_open_probe_in_flight: bool


class AsyncCircuitBreaker:
    """Circuit Breaker asíncrono con estados CLOSED, OPEN y HALF_OPEN."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def __init__(
        self,
        name: str,
        failure_threshold: int,
        recovery_timeout_seconds: float,
    ) -> None:

        if failure_threshold < 1:
            raise ValueError("failure_threshold debe ser al menos 1")

        if recovery_timeout_seconds <= 0:
            raise ValueError(
                "recovery_timeout_seconds debe ser mayor que 0"
            )

        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds

        self._state = self.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None
        self._half_open_probe_in_flight = False
        self._lock = asyncio.Lock()

    async def before_call(self) -> None:
        """Comprueba si la llamada puede ejecutarse."""

        async with self._lock:
            now = time.monotonic()

            if self._state == self.OPEN:
                elapsed = now - (self._opened_at or now)
                remaining = self.recovery_timeout_seconds - elapsed

                if remaining > 0:
                    raise CircuitBreakerOpenError(remaining)

                # Ya pasó el tiempo de recuperación.
                # Permitimos una sola solicitud de prueba.
                self._state = self.HALF_OPEN
                self._half_open_probe_in_flight = True
                return

            if self._state == self.HALF_OPEN:
                if self._half_open_probe_in_flight:
                    raise CircuitBreakerOpenError(1.0)

                self._half_open_probe_in_flight = True

    async def record_success(self) -> None:
        """Cierra el circuito después de una llamada exitosa."""

        async with self._lock:
            self._state = self.CLOSED
            self._failure_count = 0
            self._opened_at = None
            self._half_open_probe_in_flight = False

    async def record_failure(self) -> None:
        """Registra un fallo y abre el circuito al llegar al límite."""

        async with self._lock:

            if self._state == self.HALF_OPEN:
                self._open_locked()
                return

            self._failure_count += 1

            if self._failure_count >= self.failure_threshold:
                self._open_locked()

    async def snapshot(self) -> CircuitBreakerSnapshot:
        """Devuelve el estado actual del Circuit Breaker."""

        async with self._lock:
            retry_after = 0.0

            if self._state == self.OPEN and self._opened_at is not None:
                elapsed = time.monotonic() - self._opened_at

                retry_after = max(
                    0.0,
                    self.recovery_timeout_seconds - elapsed,
                )

            return CircuitBreakerSnapshot(
                name=self.name,
                state=self._state,
                failure_count=self._failure_count,
                failure_threshold=self.failure_threshold,
                recovery_timeout_seconds=self.recovery_timeout_seconds,
                retry_after_seconds=round(retry_after, 3),
                half_open_probe_in_flight=(
                    self._half_open_probe_in_flight
                ),
            )

    def _open_locked(self) -> None:
        self._state = self.OPEN
        self._opened_at = time.monotonic()
        self._half_open_probe_in_flight = False