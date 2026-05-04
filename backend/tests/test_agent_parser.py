from __future__ import annotations

import unittest
from datetime import date

from app.llm_agent import DeterministicIntentParser, extract_datetime, extract_name, extract_party_size, extract_phone


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


if __name__ == "__main__":
    unittest.main()
