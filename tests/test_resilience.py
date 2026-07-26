import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SITE_PACKAGES = ROOT / ".venv" / "Lib" / "site-packages"
RESERVATIONS_DIR = ROOT / "reservations"
sys.path.insert(0, str(SITE_PACKAGES))
sys.path.insert(0, str(RESERVATIONS_DIR))

import httpx

from circuit_breaker import AsyncCircuitBreaker, CircuitBreakerOpenError
from notification_retry import NotificationRetryPolicy


class CircuitBreakerTests(unittest.IsolatedAsyncioTestCase):
    async def test_opens_after_threshold_and_recovers_with_one_probe(self):
        breaker = AsyncCircuitBreaker(
            name="payments",
            failure_threshold=2,
            recovery_timeout_seconds=0.01,
        )

        await breaker.record_failure()
        await breaker.record_failure()

        with self.assertRaises(CircuitBreakerOpenError):
            await breaker.before_call()

        await asyncio.sleep(0.02)
        await breaker.before_call()

        with self.assertRaises(CircuitBreakerOpenError):
            await breaker.before_call()

        await breaker.record_success()
        snapshot = await breaker.snapshot()
        self.assertEqual(snapshot.state, breaker.CLOSED)
        self.assertEqual(snapshot.failure_count, 0)

    async def test_failed_half_open_probe_reopens_the_circuit(self):
        breaker = AsyncCircuitBreaker(
            name="payments",
            failure_threshold=1,
            recovery_timeout_seconds=0.01,
        )
        await breaker.record_failure()
        await asyncio.sleep(0.02)
        await breaker.before_call()
        await breaker.record_failure()

        snapshot = await breaker.snapshot()
        self.assertEqual(snapshot.state, breaker.OPEN)
        self.assertGreater(snapshot.retry_after_seconds, 0)


class NotificationRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_server_error_and_then_succeeds(self):
        responses = [
            httpx.Response(503, text="temporal"),
            httpx.Response(200, json={"status": "SENT"}),
        ]

        async def handler(request):
            response = responses.pop(0)
            response.request = request
            return response

        transport = httpx.MockTransport(handler)
        original_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            kwargs["transport"] = transport
            return original_client(*args, **kwargs)

        policy = NotificationRetryPolicy(
            timeout_seconds=1,
            max_attempts=3,
            initial_backoff_seconds=0,
            max_backoff_seconds=0,
        )

        with patch("notification_retry.httpx.AsyncClient", client_factory):
            result = await policy.send(
                url="http://notifications.test/send",
                payload={"reservation_id": "r-1"},
                headers={"X-Request-ID": "req-1"},
                request_id="req-1",
            )

        self.assertTrue(result.sent)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.last_status_code, 200)

    async def test_does_not_retry_client_error(self):
        async def handler(request):
            return httpx.Response(400, text="invalid", request=request)

        transport = httpx.MockTransport(handler)
        original_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            kwargs["transport"] = transport
            return original_client(*args, **kwargs)

        policy = NotificationRetryPolicy(
            timeout_seconds=1,
            max_attempts=3,
            initial_backoff_seconds=0,
            max_backoff_seconds=0,
        )

        with patch("notification_retry.httpx.AsyncClient", client_factory):
            result = await policy.send(
                url="http://notifications.test/send",
                payload={"reservation_id": "r-1"},
                headers={"X-Request-ID": "req-1"},
                request_id="req-1",
            )

        self.assertFalse(result.sent)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.last_status_code, 400)


if __name__ == "__main__":
    unittest.main()
