from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
import tempfile

from app.llm_agent import (
    DeterministicIntentParser,
    ReservationCallAgent,
    extract_confirmation_code,
    extract_datetime,
    extract_name,
    extract_party_size,
    extract_phone,
)
from app.reservations import ReservationService
from app.storage import ReservationStore


class AgentParserTest(unittest.IsolatedAsyncioTestCase):
    async def test_parser_extracts_reservation_details(self) -> None:
        parser = DeterministicIntentParser()
        intent = await parser.parse(
            "I need a table for four tomorrow at 7 pm under Maya Stone, 555-123-4567",
            today=date(2026, 6, 12),
        )

        self.assertEqual(intent.action, "create_reservation")
        self.assertEqual(intent.guest_name, "Maya Stone")
        self.assertEqual(intent.phone, "5551234567")
        self.assertEqual(intent.party_size, 4)
        self.assertEqual(intent.reservation_time, "2026-06-13T19:00:00")

    def test_extract_helpers(self) -> None:
        text = "Book for 3 on 2026-07-02 at 8:30 pm. My phone is (555) 321-0000."
        self.assertEqual(extract_party_size(text), 3)
        self.assertEqual(extract_phone(text), "5553210000")
        self.assertEqual(extract_datetime(text, today=date(2026, 6, 12)), "2026-07-02T20:30:00")
        self.assertIsNone(extract_name(text))
        self.assertEqual(extract_confirmation_code("confirmation code ABC12345"), "ABC12345")

    async def test_agent_collects_confirms_then_books(self) -> None:
        service = make_service(self)
        agent = ReservationCallAgent(service, DeterministicIntentParser())

        first = await agent.handle_turn(
            session_id="call-1",
            utterance="I need a table for two tomorrow at 7 pm",
            today=date(2026, 6, 12),
        )
        self.assertEqual(first["action"], "collect_details")
        self.assertIn("guest name", first["missing"])

        second = await agent.handle_turn(
            session_id="call-1",
            utterance="under Maya Stone, 555-123-4567",
            today=date(2026, 6, 12),
        )
        self.assertEqual(second["action"], "confirm_details")
        self.assertEqual(service.list_reservations(), [])

        third = await agent.handle_turn(
            session_id="call-1",
            utterance="yes please book it",
            today=date(2026, 6, 12),
        )
        self.assertEqual(third["action"], "reservation_confirmed")
        self.assertEqual(len(service.list_reservations()), 1)
        self.assertEqual(service.store.get_agent_session("call-1").state, "booked")

        retry = await agent.handle_turn(
            session_id="call-1",
            utterance="yes please book it",
            today=date(2026, 6, 12),
        )
        self.assertEqual(retry["action"], "reservation_confirmed")
        self.assertEqual(len(service.list_reservations()), 1)
        with service.store.connect() as connection:
            turn_count = connection.execute(
                "SELECT COUNT(*) AS count FROM agent_call_turns WHERE session_id = ?",
                ("call-1",),
            ).fetchone()["count"]
        self.assertEqual(turn_count, 8)

    async def test_agent_falls_back_when_primary_parser_fails(self) -> None:
        service = make_service(self)
        agent = ReservationCallAgent(service, FailingParser())

        response = await agent.handle_turn(
            session_id="call-2",
            utterance="I need a table for two tomorrow at 7 pm under Alex Chen, 555-333-2222",
            today=date(2026, 6, 12),
        )

        self.assertEqual(response["action"], "confirm_details")

    async def test_agent_hands_off_cancellation(self) -> None:
        service = make_service(self)
        agent = ReservationCallAgent(service, DeterministicIntentParser())

        response = await agent.handle_turn(
            session_id="call-3",
            utterance="Please cancel confirmation code ABC12345",
            today=date(2026, 6, 12),
        )

        self.assertEqual(response["action"], "needs_host")
        self.assertEqual(response["confirmation_code"], "ABC12345")
        self.assertEqual(service.store.get_agent_session("call-3").state, "needs_host")

    async def test_cancellation_text_does_not_confirm_pending_booking(self) -> None:
        service = make_service(self)
        agent = ReservationCallAgent(service, DeterministicIntentParser())

        await agent.handle_turn(
            session_id="call-4",
            utterance="I need a table for two tomorrow at 7 pm under Alex Chen, 555-333-2222",
            today=date(2026, 6, 12),
        )
        response = await agent.handle_turn(
            session_id="call-4",
            utterance="don't confirm, cancel it",
            today=date(2026, 6, 12),
        )
        self.assertEqual(response["action"], "needs_host")
        self.assertEqual(service.store.get_agent_session("call-4").state, "needs_host")

        retry = await agent.handle_turn(
            session_id="call-4",
            utterance="yes",
            today=date(2026, 6, 12),
        )
        self.assertEqual(retry["action"], "needs_host")
        second_retry = await agent.handle_turn(
            session_id="call-4",
            utterance="yes",
            today=date(2026, 6, 12),
        )
        self.assertEqual(second_retry["action"], "needs_host")
        self.assertEqual(service.list_reservations(), [])


class FailingParser:
    async def parse(self, utterance: str, *, today: date):
        raise RuntimeError("parser unavailable")


def make_service(test_case: unittest.TestCase) -> ReservationService:
    tempdir = tempfile.TemporaryDirectory()
    test_case.addCleanup(tempdir.cleanup)
    store = ReservationStore(Path(tempdir.name) / "agent.sqlite3")
    service = ReservationService(
        store,
        timezone_name="America/New_York",
        open_time="17:00",
        close_time="22:00",
        slot_minutes=15,
        slot_capacity=8,
        default_duration_minutes=90,
    )
    return service


if __name__ == "__main__":
    unittest.main()
