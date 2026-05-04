from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from .reservations import ReservationCreate, ReservationError, ReservationNotAvailableError, ReservationService, record_to_dict


logger = logging.getLogger(__name__)


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
    confirmation_code: str | None = None
    notes: str = ""


class IntentParser(Protocol):
    async def parse(self, utterance: str, *, today: date) -> AgentIntent:
        ...


class DeterministicIntentParser:
    async def parse(self, utterance: str, *, today: date) -> AgentIntent:
        lower = utterance.lower()
        if "cancel" in lower:
            return AgentIntent(
                action="cancel_reservation",
                phone=extract_phone(utterance),
                confirmation_code=extract_confirmation_code(utterance),
            )
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
                            "confirmation_code": {"type": ["string", "null"]},
                            "notes": {"type": "string"},
                        },
                        "required": [
                            "action",
                            "guest_name",
                            "phone",
                            "party_size",
                            "reservation_time",
                            "confirmation_code",
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
        self.fallback_parser = DeterministicIntentParser()

    async def handle_turn(
        self,
        *,
        session_id: str,
        utterance: str,
        caller_phone: str | None = None,
        today: date | None = None,
    ) -> dict[str, Any]:
        self.service.store.append_agent_turn(session_id=session_id, role="caller", text=utterance)
        today_value = today or date.today()
        existing_session = self.service.store.get_agent_session(session_id)
        if existing_session and existing_session.state == "booked" and existing_session.reservation_id:
            record = self.service.get_reservation(existing_session.reservation_id)
            response = {
                "action": "reservation_confirmed",
                "state": "booked",
                "message": (
                    f"Confirmed for {record.guest_name}, party of {record.party_size}. "
                    f"Confirmation code {record.confirmation_code}."
                ),
                "reservation": record_to_dict(record),
            }
            self.service.store.append_agent_turn(
                session_id=session_id,
                role="agent",
                text=response["message"],
                action=response["action"],
            )
            return response
        if existing_session and existing_session.state == "needs_host":
            response = {
                "action": "needs_host",
                "state": "needs_host",
                "message": "A host needs to take over this call. Please start a new call for a new booking.",
            }
            self.service.store.append_agent_turn(
                session_id=session_id,
                role="agent",
                text=response["message"],
                action=response["action"],
            )
            return response

        try:
            intent = await self.parser.parse(utterance, today=today_value)
        except Exception as exc:
            logger.info("Primary intent parser failed; falling back to deterministic parser: %s", exc)
            intent = await self.fallback_parser.parse(utterance, today=today_value)

        if intent.action == "cancel_reservation" or is_cancellation(utterance):
            response = self.cancellation_handoff(session_id, intent.confirmation_code or extract_confirmation_code(utterance))
            self.service.store.append_agent_turn(
                session_id=session_id,
                role="agent",
                text=response["message"],
                action=response["action"],
            )
            return response

        if existing_session and existing_session.state == "ready_to_confirm" and is_affirmation(utterance):
            response = self.book_confirmed_session(existing_session)
            self.service.store.append_agent_turn(
                session_id=session_id,
                role="agent",
                text=response["message"],
                action=response["action"],
            )
            return response

        session = self.service.store.upsert_agent_session(
            session_id=session_id,
            caller_phone=caller_phone,
            guest_name=intent.guest_name,
            phone=intent.phone,
            party_size=intent.party_size,
            reservation_time=intent.reservation_time,
            notes=intent.notes or None,
        )
        guest_name = intent.guest_name or session.guest_name
        phone = intent.phone or caller_phone or session.phone or session.caller_phone
        party_size = intent.party_size or session.party_size
        reservation_time = intent.reservation_time or session.reservation_time

        if intent.action == "check_availability":
            target_time = intent.reservation_time or session.reservation_time
            target_date = date.fromisoformat(target_time[:10]) if target_time else date.today()
            slots = self.service.availability(target_date, party_size=intent.party_size or session.party_size or 1)
            available_slots = [slot for slot in slots if slot.available][:5]
            response = {
                "action": intent.action,
                "message": "I found available times." if available_slots else "I do not see open times for that party size.",
                "availability": [slot.__dict__ for slot in available_slots],
            }
            self.service.store.append_agent_turn(
                session_id=session_id,
                role="agent",
                text=response["message"],
                action=response["action"],
            )
            return response

        merged_intent = AgentIntent(
            action=intent.action,
            guest_name=guest_name,
            phone=phone,
            party_size=party_size,
            reservation_time=reservation_time,
            notes=session.notes or intent.notes,
        )
        missing = missing_create_fields(merged_intent, phone)
        if missing:
            self.service.store.upsert_agent_session(session_id=session_id, state="collecting")
            response = {
                "action": "collect_details",
                "state": "collecting",
                "missing": missing,
                "message": f"I can book that. I still need: {', '.join(missing)}.",
            }
            self.service.store.append_agent_turn(
                session_id=session_id,
                role="agent",
                text=response["message"],
                action=response["action"],
            )
            return response

        response = {
            "action": "confirm_details",
            "state": "ready_to_confirm",
            "message": (
                f"I have {guest_name}, party of {party_size}, at {reservation_time}, "
                f"phone ending {phone[-4:] if phone else ''}. Should I book it?"
            ),
            "proposed_reservation": {
                "guest_name": guest_name,
                "phone": phone,
                "party_size": party_size,
                "reservation_time": reservation_time,
                "notes": session.notes or intent.notes,
            },
        }
        self.service.store.upsert_agent_session(session_id=session_id, state="ready_to_confirm")
        self.service.store.append_agent_turn(
            session_id=session_id,
            role="agent",
            text=response["message"],
            action=response["action"],
        )
        return response

    def cancellation_handoff(self, session_id: str, confirmation_code: str | None) -> dict[str, Any]:
        self.service.store.upsert_agent_session(session_id=session_id, state="needs_host")
        return {
            "action": "needs_host",
            "state": "needs_host",
            "message": (
                f"I found cancellation intent for {confirmation_code}. A host should verify and cancel it."
                if confirmation_code
                else "A host should verify cancellation requests. Please provide the confirmation code."
            ),
            "confirmation_code": confirmation_code,
        }

    def book_confirmed_session(self, session) -> dict[str, Any]:
        try:
            record = self.service.create_reservation(
                ReservationCreate(
                    guest_name=session.guest_name or "",
                    phone=session.phone or session.caller_phone or "",
                    party_size=session.party_size or 0,
                    reservation_time=session.reservation_time or "",
                    channel="agent",
                    notes=session.notes,
                    source_session_id=session.session_id,
                )
            )
        except ReservationNotAvailableError as exc:
            alternatives = self.alternatives(session.reservation_time, session.party_size or 1)
            self.service.store.upsert_agent_session(session_id=session.session_id, state="collecting")
            return {
                "action": "reservation_unavailable",
                "state": "collecting",
                "message": str(exc),
                "availability": alternatives,
            }
        except ReservationError as exc:
            return {
                "action": "reservation_failed",
                "message": str(exc),
            }
        self.service.store.upsert_agent_session(
            session_id=session.session_id,
            state="booked",
            reservation_id=record.id,
        )
        return {
            "action": "reservation_confirmed",
            "state": "booked",
            "message": (
                f"Confirmed for {record.guest_name}, party of {record.party_size}. "
                f"Confirmation code {record.confirmation_code}."
            ),
            "reservation": record_to_dict(record),
        }

    def alternatives(self, reservation_time: str | None, party_size: int) -> list[dict[str, Any]]:
        if not reservation_time:
            return []
        target_date = date.fromisoformat(reservation_time[:10])
        return [slot.__dict__ for slot in self.service.availability(target_date, party_size=party_size) if slot.available][:3]


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


def extract_confirmation_code(utterance: str) -> str | None:
    match = re.search(r"\b(?:confirmation|code|reservation)\s*(?:is|#|number|code)?\s*([A-Z0-9]{6,10})\b", utterance, re.I)
    return match.group(1).upper() if match else None


def is_affirmation(utterance: str) -> bool:
    lower = utterance.lower()
    if re.search(r"\b(don't|do not|no|cancel|stop|never)\b", lower):
        return False
    return bool(re.search(r"\b(yes|yeah|yep|please book|book it|confirm it|that works)\b", lower))


def is_cancellation(utterance: str) -> bool:
    return bool(re.search(r"\b(cancel|don't book|do not book|stop)\b", utterance.lower()))


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
