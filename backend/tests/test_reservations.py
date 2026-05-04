from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.reservations import (
    ReservationCreate,
    ReservationError,
    ReservationNotAvailableError,
    ReservationService,
    ReservationUpdate,
)
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
        cancelled = self.service.get_reservation(record.id)
        self.assertEqual(cancelled.table_names, ())

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
        self.assertEqual(slot.seats_remaining, 0)
        self.assertFalse(slot.available)

    def test_reservation_occupies_table_for_duration(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        store = ReservationStore(Path(tempdir.name) / "duration.sqlite3")
        store.create_table(table_id="two-top", name="T1", capacity=2)
        service = ReservationService(
            store,
            timezone_name="America/New_York",
            open_time="17:00",
            close_time="22:00",
            slot_minutes=15,
            slot_capacity=2,
            default_duration_minutes=90,
        )
        first = service.create_reservation(
            ReservationCreate(
                guest_name="Leo Martin",
                phone="5551119999",
                party_size=2,
                reservation_time="2026-06-12T19:00:00",
                channel="online",
            )
        )

        self.assertEqual(first.table_names, ("T1",))
        with self.assertRaises(ReservationNotAvailableError):
            service.create_reservation(
                ReservationCreate(
                    guest_name="Nia Patel",
                    phone="5550001111",
                    party_size=2,
                    reservation_time="2026-06-12T20:15:00",
                    channel="agent",
                )
            )

        second = service.create_reservation(
            ReservationCreate(
                guest_name="Owen Kim",
                phone="5550002222",
                party_size=2,
                reservation_time="2026-06-12T20:30:00",
                channel="online",
            )
        )
        self.assertEqual(second.table_names, ("T1",))

    def test_combines_tables_for_larger_party(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        store = ReservationStore(Path(tempdir.name) / "combine.sqlite3")
        store.create_table(table_id="t1", name="T1", capacity=2, zone="Patio", can_combine=True)
        store.create_table(table_id="t2", name="T2", capacity=2, zone="Patio", can_combine=True)
        service = ReservationService(
            store,
            timezone_name="America/New_York",
            open_time="17:00",
            close_time="22:00",
            slot_minutes=15,
            slot_capacity=4,
            default_duration_minutes=90,
        )

        record = service.create_reservation(
            ReservationCreate(
                guest_name="Uma Davis",
                phone="5551212121",
                party_size=4,
                reservation_time="2026-06-12T18:00:00",
                channel="online",
            )
        )

        self.assertEqual(record.table_names, ("T1", "T2"))

    def test_unassigned_legacy_reservation_blocks_overlapping_inventory(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        store = ReservationStore(Path(tempdir.name) / "legacy.sqlite3")
        store.create_table(table_id="t1", name="T1", capacity=2)
        store.create(
            guest_name="Legacy Guest",
            phone="5554443333",
            party_size=2,
            reservation_time="2026-06-12T23:00:00Z",
            duration_minutes=90,
            ends_at="2026-06-13T00:30:00Z",
            channel="online",
        )
        service = ReservationService(
            store,
            timezone_name="America/New_York",
            open_time="17:00",
            close_time="22:00",
            slot_minutes=15,
            slot_capacity=2,
            default_duration_minutes=90,
        )

        with self.assertRaises(ReservationNotAvailableError):
            service.create_reservation(
                ReservationCreate(
                    guest_name="New Guest",
                    phone="5554442222",
                    party_size=2,
                    reservation_time="2026-06-12T19:30:00",
                    channel="agent",
                )
            )

    def test_confirmation_code_lookup_and_query_search(self) -> None:
        record = self.service.create_reservation(
            ReservationCreate(
                guest_name="Quinn Harper",
                phone="5551012020",
                party_size=2,
                reservation_time="2026-06-12T18:00:00",
                channel="online",
            )
        )

        found = self.service.get_reservation(record.confirmation_code)
        self.assertEqual(found.id, record.id)
        search_results = self.service.list_reservations(query="harper")
        self.assertEqual([item.id for item in search_results], [record.id])

    def test_reschedule_reassigns_and_releases_old_time(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        store = ReservationStore(Path(tempdir.name) / "reschedule.sqlite3")
        store.create_table(table_id="two-top", name="T1", capacity=2)
        service = ReservationService(
            store,
            timezone_name="America/New_York",
            open_time="17:00",
            close_time="22:00",
            slot_minutes=15,
            slot_capacity=2,
            default_duration_minutes=90,
        )
        original = service.create_reservation(
            ReservationCreate(
                guest_name="Riley Moore",
                phone="5553034040",
                party_size=2,
                reservation_time="2026-06-12T19:00:00",
                channel="online",
            )
        )

        updated = service.update_reservation(
            original.id,
            ReservationUpdate(reservation_time="2026-06-12T20:30:00"),
        )

        self.assertTrue(updated.reservation_time.endswith("00:30:00Z"))
        replacement = service.create_reservation(
            ReservationCreate(
                guest_name="Sasha Nguyen",
                phone="5555056060",
                party_size=2,
                reservation_time="2026-06-12T19:00:00",
                channel="walk_in",
            )
        )
        self.assertEqual(replacement.status, "confirmed")

    def test_cancelled_reservation_cannot_be_reactivated(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        store = ReservationStore(Path(tempdir.name) / "reactivate.sqlite3")
        store.create_table(table_id="two-top", name="T1", capacity=2)
        service = ReservationService(
            store,
            timezone_name="America/New_York",
            open_time="17:00",
            close_time="22:00",
            slot_minutes=15,
            slot_capacity=2,
            default_duration_minutes=90,
        )
        cancelled = service.create_reservation(
            ReservationCreate(
                guest_name="Taylor Brooks",
                phone="5557078080",
                party_size=2,
                reservation_time="2026-06-12T19:00:00",
                channel="online",
            )
        )
        service.update_status(cancelled.id, "cancelled")
        service.create_reservation(
            ReservationCreate(
                guest_name="Uma Patel",
                phone="5559091010",
                party_size=2,
                reservation_time="2026-06-12T19:00:00",
                channel="online",
            )
        )

        with self.assertRaises(ReservationError):
            service.update_status(cancelled.id, "confirmed")

    def test_update_rejects_turn_that_runs_past_close(self) -> None:
        record = self.service.create_reservation(
            ReservationCreate(
                guest_name="Vera Hall",
                phone="5551110000",
                party_size=2,
                reservation_time="2026-06-12T20:00:00",
                channel="online",
            )
        )

        with self.assertRaises(ReservationNotAvailableError):
            self.service.update_reservation(record.id, ReservationUpdate(duration_minutes=180))

    def test_terminal_reservation_cannot_be_edited(self) -> None:
        record = self.service.create_reservation(
            ReservationCreate(
                guest_name="Willa Price",
                phone="5552220000",
                party_size=2,
                reservation_time="2026-06-12T18:00:00",
                channel="online",
            )
        )
        self.service.update_status(record.id, "no_show")

        with self.assertRaises(ReservationError):
            self.service.update_reservation(record.id, ReservationUpdate(notes="late arrival"))


if __name__ == "__main__":
    unittest.main()
