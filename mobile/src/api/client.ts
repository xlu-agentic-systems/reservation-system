import { AvailabilitySlot, CallAgentResponse, Reservation } from "../types/reservation";

const API_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type ReservationInput = {
  guest_name: string;
  phone: string;
  party_size: number;
  reservation_time: string;
  notes: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? `Request failed with ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export async function fetchAvailability(date: string, partySize: number): Promise<AvailabilitySlot[]> {
  const params = new URLSearchParams({ date, party_size: String(partySize) });
  const payload = await request<{ slots: AvailabilitySlot[] }>(`/availability?${params.toString()}`);
  return payload.slots;
}

export async function createReservation(input: ReservationInput): Promise<Reservation> {
  return request<Reservation>("/reservations", {
    method: "POST",
    body: JSON.stringify({ ...input, channel: "online" })
  });
}

export async function fetchReservations(date: string): Promise<Reservation[]> {
  const payload = await request<{ reservations: Reservation[] }>(`/reservations?date=${date}`);
  return payload.reservations;
}

export async function sendCallTurn(utterance: string, sessionId: string): Promise<CallAgentResponse> {
  return request<CallAgentResponse>("/agent/call-turn", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, utterance })
  });
}
