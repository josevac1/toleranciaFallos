import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".venv" / "Lib" / "site-packages"))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gateway = load_module("gateway_main_test", ROOT / "gateway" / "main.py")
inventory = load_module("inventory_main_test", ROOT / "inventory" / "main.py")


class OverloadProtectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_token_bucket_rejects_when_burst_is_exhausted(self):
        bucket = gateway.TokenBucket(rate=1, capacity=2)
        self.assertTrue(await bucket.allow())
        self.assertTrue(await bucket.allow())
        self.assertFalse(await bucket.allow())


class DatabaseRetryTests(unittest.TestCase):
    def test_database_connection_retries_transient_failures(self):
        connection = object()
        effects = [
            inventory.psycopg.OperationalError("flapping"),
            inventory.psycopg.OperationalError("flapping"),
            connection,
        ]

        with (
            patch.object(
                inventory.psycopg,
                "connect",
                side_effect=effects,
            ) as connect,
            patch.object(inventory.time, "sleep") as sleep,
        ):
            result = inventory.connect_database()

        self.assertIs(result, connection)
        self.assertEqual(connect.call_count, 3)
        self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
