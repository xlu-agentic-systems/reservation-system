from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


class SecurityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_env = {
            "DATABASE_PATH": os.environ.get("DATABASE_PATH"),
            "ADMIN_API_KEY": os.environ.get("ADMIN_API_KEY"),
        }
        os.environ["DATABASE_PATH"] = str(Path(self.tempdir.name) / "security.sqlite3")
        os.environ["ADMIN_API_KEY"] = "test-admin-key"
        import app.main as main

        self.main = importlib.reload(main)
        self.client = TestClient(self.main.app)

    def tearDown(self) -> None:
        for key, value in self.previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tempdir.cleanup()

    def test_admin_endpoint_requires_api_key(self) -> None:
        response = self.client.get("/reservations")
        self.assertEqual(response.status_code, 401)

        authorized = self.client.get("/reservations", headers={"x-api-key": "test-admin-key"})
        self.assertEqual(authorized.status_code, 200)

    def test_public_booking_is_audited(self) -> None:
        response = self.client.post(
            "/reservations",
            json={
                "guest_name": "Audit Guest",
                "phone": "5551230000",
                "party_size": 2,
                "reservation_time": "2026-06-12T18:00:00",
                "channel": "online",
            },
            headers={"x-actor": "public-widget"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.main.store.audit_event_count(), 1)

    def test_health_checks_database_and_auth_configuration(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["admin_auth_configured"])
        self.assertGreater(payload["table_count"], 0)


if __name__ == "__main__":
    unittest.main()
