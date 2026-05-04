export type Reservation = {
  id: string;
  confirmation_code: string;
  guest_name: string;
  phone: string;
  party_size: number;
  reservation_time: string;
  duration_minutes: number;
  ends_at: string;
  channel: "online" | "phone" | "agent" | "walk_in";
  status: "confirmed" | "cancelled" | "seated" | "no_show";
  notes: string;
  source_session_id?: string | null;
  table_ids: string[];
  table_names: string[];
  created_at: string;
  updated_at: string;
};

export type AvailabilitySlot = {
  reservation_time: string;
  ends_at: string;
  seats_remaining: number;
  available: boolean;
  table_ids: string[];
  table_names: string[];
};

export type CallAgentResponse = {
  action: string;
  message: string;
  missing?: string[];
  availability?: AvailabilitySlot[];
  reservation?: Reservation;
};
