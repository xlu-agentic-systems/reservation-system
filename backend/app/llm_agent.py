from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from .reservations import ReservationCreate, ReservationError, ReservationService, record_to_dict


SYSTEM_PROMPT = """
You are a concise restaurant reservation phone agent. Extract reservation intent from the caller.
Return JSON that follows the provided schema. Use ISO datetimes when the caller provides a date and time.
Ask for missing details instead of inventing them.
"""


@dataclass(frozen=True)
class AgentIntent:
    action: str
    guest_name: str | None = None
    phone: str | None = None
    party_size: int | None = None
    reservation_time: str | None = None
    notes: str = ""


class IntentParser(Protocol):
    async def parse(self, utterance: str, *, today: date) -> AgentIntent:
        ...


class DeterministicIntentParser:
    async def parse(self, utterance: str, *, today: date) -> AgentIntent:
        lower = utterance.lower()
        if "cancel" in lower:
            return AgentIntent(action="cancel_reservation", phone=extract_phone(utterance))
        if "available" in lower or "availability" in lower or "open" in lower:
            return AgentIntent(
                action="check_availability",
                party_size=extract_party_size(utterance),
                reservation_time=extract_datetime(utterance, today=today),
            )

        return AgentIntent(
            action="create_reservation",
            guest_name=extract_name(utterance),
            phone=extract_phone(utterance),
            party_size=extract_party_size(utterance),
            reservation_time=extract_datetime(utterance, today=today),
            notes=utterance.strip(),
        )


class OpenAIIntentParser:
    def __init__(self, *, api_key: str, model: str) -> None:
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def parse(self, utterance: str, *, today: date) -> AgentIntent:
        response = await self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Today is {today.isoformat()}. Caller said: {utterance}",
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "reservation_intent",
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": [
                                    "create_reservation",
                                    "check_availability",
                                    "cancel_reservation",
                                    "unknown",
                                ],
                            },
                            "guest_name": {"type": ["string", "null"]},
                            "phone": {"type": ["string", "null"]},
                            "party_size": {"type": ["integer", "null"], "minimum": 1},
                            "reservation_time": {"type": ["string", "null"]},
                            "notes": {"type": "string"},
                        },
                        "required": [
                            "action",
                            "guest_name",
                            "phone",
                            "party_size",
                            "reservation_time",
                            "notes",
                        ],
                    },
                    "strict": True,
                }
            },
        )
        payload = json.loads(response.output_text)
        return AgentIntent(**payload)


class ReservationCallAgent:
    def __init__(self, service: ReservationService, parser: IntentParser) -> None:
        self.service = service
        self.parser = parser

    async def handle_turn(
        self,
        *,
        session_id: str,
        utterance: str,
        caller_phone: str | None = None,
        today: date | None = None,
    ) -> dict[str, Any]:
        intent = await self.parser.parse(utterance, today=today or date.today())
        phone = intent.phone or caller_phone

        if intent.action == "check_availability":
            target_date = date.fromisoformat(intent.reservation_time[:10]) if intent.reservation_time else date.today()
            slots = self.service.availability(target_date, party_size=intent.party_size or 1)
            available_slots = [slot for slot in slots if slot.available][:5]
            return {
                "action": intent.action,
                "message": "I found available times." if available_slots else "I do not see open times for that party size.",
                "availability": [slot.__dict__ for slot in available_slots],
            }

        if intent.action == "cancel_reservation":
            return {
                "action": intent.action,
                "message": "I can help cancel that. Please provide the reservation confirmation ID.",
            }

        missing = missing_create_fields(intent, phone)
        if missing:
            return {
                "action": "collect_details",
                "missing": missing,
                "message": f"I can book that. I still need: {', '.join(missing)}.",
            }

        try:
            record = self.service.create_reservation(
                ReservationCreate(
                    guest_name=intent.guest_name or "",
                    phone=phone or "",
                    party_size=intent.party_size or 0,
                    reservation_time=intent.reservation_time or "",
                    channel="agent",
                    notes=intent.notes,
                    source_session_id=session_id,
                )
            )
        except ReservationError as exc:
            return {
                "action": "reservation_failed",
                "message": str(exc),
            }

        return {
            "action": "reservation_confirmed",
            "message": f"Confirmed for {record.guest_name}, party of {record.party_size}.",
            "reservation": record_to_dict(record),
        }


def missing_create_fields(intent: AgentIntent, phone: str | None) -> list[str]:
    missing: list[str] = []
    if not intent.guest_name:
        missing.append("guest name")
    if not phone:
        missing.append("phone number")
    if not intent.party_size:
        missing.append("party size")
    if not intent.reservation_time:
        missing.append("date and time")
    return missing


def extract_party_size(utterance: str) -> int | None:
    lower = utterance.lower()
    match = re.search(r"(?:party of|table for|for)\s+(\d+)", lower)
    if match:
        return int(match.group(1))
    words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    for word, value in words.items():
        if re.search(rf"\b(?:party of|table for|for)\s+{word}\b", lower):
            return value
    return None


def extract_phone(utterance: str) -> str | None:
    for match in re.finditer(r"(\+?\d[\d\s().-]{7,}\d)", utterance):
        candidate = re.sub(r"[^\d+]", "", match.group(1))
        digit_count = len(candidate.lstrip("+"))
        if 10 <= digit_count <= 15:
            return candidate
    return None


def extract_name(utterance: str) -> str | None:
    match = re.search(r"\b(?:name is|under|for)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", utterance)
    return match.group(1).strip() if match else None


def extract_datetime(utterance: str, *, today: date) -> str | None:
    lower = utterance.lower()
    iso_match = re.search(
        r"(\d{4}-\d{2}-\d{2})(?:\s+(?:at|@))?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
        lower,
    )
    if iso_match:
        return build_datetime(iso_match.group(1), iso_match.group(2), iso_match.group(3), iso_match.group(4))

    day = today
    if "tomorrow" in lower:
        day = today + timedelta(days=1)
    else:
        day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        for index, name in enumerate(day_names):
            if name in lower:
                days_ahead = (index - today.weekday()) % 7
                day = today + timedelta(days=days_ahead or 7)
                break

    time_match = re.search(r"\b(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", lower)
    if not time_match:
        return None
    return build_datetime(day.isoformat(), time_match.group(1), time_match.group(2), time_match.group(3))


def build_datetime(day: str, hour_value: str, minute_value: str | None, meridiem: str | None) -> str:
    hour = int(hour_value)
    minute = int(minute_value or "0")
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    return datetime.fromisoformat(day).replace(hour=hour, minute=minute).isoformat()
