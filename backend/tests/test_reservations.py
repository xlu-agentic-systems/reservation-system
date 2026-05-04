from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.reservations import ReservationCreate, ReservationNotAvailableError, ReservationService
from app.storage import ReservationStore


class ReservationServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        store = ReservationStore(Path(self.tempdir.name) / "test.sqlite3")
        self.service = ReservationService(
            store,
            timezone_name="America/New_York",
            open_time="17:00",
            close_time="22:00",
            slot_minutes=15,
            slot_capacity=4,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_online_and_agent_reservations_share_capacity(self) -> None:
        self.service.create_reservation(
            ReservationCreate(
                guest_name="Mina Chen",
                phone="5551112222",
                party_size=2,
                reservation_time="2026-06-12T19:00:00",
                channel="online",
            )
        )
        self.service.create_reservation(
            ReservationCreate(
                guest_name="Noah Park",
                phone="5553334444",
                party_size=2,
                reservation_time="2026-06-12T19:05:00",
                channel="agent",
                source_session_id="call-1",
            )
        )

        with self.assertRaises(ReservationNotAvailableError):
            self.service.create_reservation(
                ReservationCreate(
                    guest_name="Ava Singh",
                    phone="5555556666",
                    party_size=1,
                    reservation_time="2026-06-12T19:10:00",
                    channel="online",
                )
            )

    def test_cancelled_reservation_releases_capacity(self) -> None:
        record = self.service.create_reservation(
            ReservationCreate(
                guest_name="Eli Ramos",
                phone="5557778888",
                party_size=4,
                reservation_time="2026-06-12T20:00:00",
                channel="online",
            )
        )
        self.service.update_status(record.id, "cancelled")

        replacement = self.service.create_reservation(
            ReservationCreate(
                guest_name="Iris Lee",
                phone="5559990000",
                party_size=4,
                reservation_time="2026-06-12T20:00:00",
                channel="agent",
            )
        )
        self.assertEqual(replacement.status, "confirmed")

    def test_availability_reflects_existing_reservations(self) -> None:
        self.service.create_reservation(
            ReservationCreate(
                guest_name="Sam Rivera",
                phone="5552223333",
                party_size=3,
                reservation_time="2026-06-12T18:00:00",
                channel="online",
            )
        )

        slots = self.service.availability(date(2026, 6, 12), party_size=2)
        slot = next(item for item in slots if item.reservation_time.endswith("22:00:00Z"))
        self.assertEqual(slot.seats_remaining, 1)
        self.assertFalse(slot.available)


if __name__ == "__main__":
    unittest.main()
