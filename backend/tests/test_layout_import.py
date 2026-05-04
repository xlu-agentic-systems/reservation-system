from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.layout_import import LayoutImportService, StaticLayoutProvider, TableSpec
from app.reservations import ReservationCreate, ReservationService
from app.storage import ReservationStore


class LayoutImportServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = ReservationStore(Path(self.tempdir.name) / "layout.sqlite3")
        self.service = LayoutImportService(self.store)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_dry_run_validates_without_writing_tables(self) -> None:
        result = self.service.import_layout(
            provider=StaticLayoutProvider(
                [
                    TableSpec(id="patio-1", name="P1", capacity=2, zone="Patio", x=1, y=2),
                    TableSpec(id="patio-2", name="P2", capacity=4, zone="Patio", x=2, y=2),
                ]
            ),
            mode="replace",
            dry_run=True,
        )

        self.assertEqual(result.errors, ())
        self.assertEqual(result.imported_tables, 0)
        self.assertEqual(self.store.list_tables(include_inactive=True), [])

    def test_upsert_import_adds_and_updates_tables(self) -> None:
        self.service.import_layout(
            provider=StaticLayoutProvider([TableSpec(id="bar-1", name="B1", capacity=2, zone="Bar")]),
            mode="upsert",
        )
        self.service.import_layout(
            provider=StaticLayoutProvider([TableSpec(id="bar-1", name="B1", capacity=3, zone="Bar")]),
            mode="upsert",
        )

        tables = self.store.list_tables()
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].capacity, 3)

    def test_replace_deactivates_tables_not_in_import(self) -> None:
        self.service.import_layout(
            provider=StaticLayoutProvider(
                [
                    TableSpec(id="main-1", name="M1", capacity=2),
                    TableSpec(id="main-2", name="M2", capacity=2),
                ]
            ),
            mode="upsert",
        )
        self.service.import_layout(
            provider=StaticLayoutProvider([TableSpec(id="main-2", name="M2", capacity=4)]),
            mode="replace",
        )

        active_ids = {table.id for table in self.store.list_tables()}
        inactive_ids = {table.id for table in self.store.list_tables(include_inactive=True) if not table.is_active}
        self.assertEqual(active_ids, {"main-2"})
        self.assertEqual(inactive_ids, {"main-1"})

    def test_replace_rejects_deactivating_assigned_table(self) -> None:
        self.service.import_layout(
            provider=StaticLayoutProvider([TableSpec(id="main-1", name="M1", capacity=2)]),
            mode="upsert",
        )
        reservation_service = ReservationService(
            self.store,
            timezone_name="America/New_York",
            open_time="17:00",
            close_time="22:00",
            slot_minutes=15,
            slot_capacity=2,
            default_duration_minutes=90,
        )
        reservation_service.create_reservation(
            ReservationCreate(
                guest_name="Assigned Guest",
                phone="5556667777",
                party_size=2,
                reservation_time="2026-06-12T18:00:00",
                channel="online",
            )
        )

        result = self.service.import_layout(
            provider=StaticLayoutProvider([TableSpec(id="main-2", name="M2", capacity=2)]),
            mode="replace",
        )

        self.assertIn("active reservations", result.errors[0])
        self.assertEqual({table.id for table in self.store.list_tables()}, {"main-1"})

    def test_dry_run_replace_reports_active_assignment_conflict(self) -> None:
        self.service.import_layout(
            provider=StaticLayoutProvider([TableSpec(id="main-1", name="M1", capacity=2)]),
            mode="upsert",
        )
        reservation_service = ReservationService(
            self.store,
            timezone_name="America/New_York",
            open_time="17:00",
            close_time="22:00",
            slot_minutes=15,
            slot_capacity=2,
            default_duration_minutes=90,
        )
        reservation_service.create_reservation(
            ReservationCreate(
                guest_name="Preview Guest",
                phone="5556661111",
                party_size=2,
                reservation_time="2026-06-12T18:00:00",
                channel="online",
            )
        )

        result = self.service.import_layout(
            provider=StaticLayoutProvider([TableSpec(id="main-2", name="M2", capacity=2)]),
            mode="replace",
            dry_run=True,
        )

        self.assertIn("active reservations", result.errors[0])

    def test_upsert_rejects_deactivating_assigned_table(self) -> None:
        self.service.import_layout(
            provider=StaticLayoutProvider([TableSpec(id="main-1", name="M1", capacity=2)]),
            mode="upsert",
        )
        reservation_service = ReservationService(
            self.store,
            timezone_name="America/New_York",
            open_time="17:00",
            close_time="22:00",
            slot_minutes=15,
            slot_capacity=2,
            default_duration_minutes=90,
        )
        reservation_service.create_reservation(
            ReservationCreate(
                guest_name="Upsert Guest",
                phone="5556662222",
                party_size=2,
                reservation_time="2026-06-12T18:00:00",
                channel="online",
            )
        )

        result = self.service.import_layout(
            provider=StaticLayoutProvider([TableSpec(id="main-1", name="M1", capacity=2, is_active=False)]),
            mode="upsert",
        )

        self.assertIn("deactivate tables", result.errors[0])
        self.assertTrue(self.store.get_table("main-1").is_active)

    def test_validation_reports_duplicate_ids(self) -> None:
        result = self.service.import_layout(
            provider=StaticLayoutProvider(
                [
                    TableSpec(id="dup", name="A", capacity=2),
                    TableSpec(id="dup", name="B", capacity=2),
                ]
            ),
            mode="upsert",
        )

        self.assertIn("duplicates dup", result.errors[0])


if __name__ == "__main__":
    unittest.main()
