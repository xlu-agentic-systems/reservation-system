export type Reservation = {
  id: string;
  guest_name: string;
  phone: string;
  party_size: number;
  reservation_time: string;
  channel: "online" | "phone" | "agent";
  status: "confirmed" | "cancelled" | "seated" | "no_show";
  notes: string;
  source_session_id?: string | null;
  created_at: string;
  updated_at: string;
};

export type AvailabilitySlot = {
  reservation_time: string;
  seats_remaining: number;
  available: boolean;
};

export type CallAgentResponse = {
  action: string;
  message: string;
  missing?: string[];
  availability?: AvailabilitySlot[];
  reservation?: Reservation;
};
