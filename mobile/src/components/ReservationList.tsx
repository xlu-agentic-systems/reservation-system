import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { Reservation } from "../types/reservation";

type Props = {
  reservations: Reservation[];
  onStatusChange: (reservationId: string, status: Reservation["status"]) => void;
};

export function ReservationList({ reservations, onStatusChange }: Props) {
  return (
    <View style={styles.section}>
      <View style={styles.headingRow}>
        <Ionicons name="restaurant-outline" size={18} color="#305f72" />
        <Text style={styles.heading}>Today</Text>
      </View>
      {reservations.length === 0 ? (
        <Text style={styles.empty}>No reservations for the selected date.</Text>
      ) : (
        reservations.map((reservation) => (
          <View key={reservation.id} style={styles.item}>
            <View>
              <Text style={styles.name}>{reservation.guest_name}</Text>
              <Text style={styles.meta}>
                {formatTime(reservation.reservation_time)} · Party {reservation.party_size} · {reservation.channel}
              </Text>
              <Text style={styles.table}>{reservation.table_names.join("+") || "Unassigned"}</Text>
            </View>
            <View style={styles.actions}>
              <Text style={styles.status}>{reservation.status}</Text>
              {reservation.status === "confirmed" ? (
                <View style={styles.actionRow}>
                  <Pressable onPress={() => onStatusChange(reservation.id, "seated")} style={styles.iconButton}>
                    <Ionicons name="checkmark" size={16} color="#1f2d2f" />
                  </Pressable>
                  <Pressable onPress={() => onStatusChange(reservation.id, "no_show")} style={styles.iconButton}>
                    <Ionicons name="close" size={16} color="#1f2d2f" />
                  </Pressable>
                  <Pressable onPress={() => onStatusChange(reservation.id, "cancelled")} style={styles.iconButton}>
                    <Ionicons name="trash-outline" size={16} color="#1f2d2f" />
                  </Pressable>
                </View>
              ) : null}
            </View>
          </View>
        ))
      )}
    </View>
  );
}

function formatTime(value: string): string {
  return new Date(value).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

const styles = StyleSheet.create({
  section: {
    gap: 10
  },
  headingRow: {
    alignItems: "center",
    flexDirection: "row",
    gap: 8
  },
  heading: {
    color: "#1f2d2f",
    fontSize: 18,
    fontWeight: "700"
  },
  empty: {
    color: "#60746f",
    fontSize: 14
  },
  item: {
    alignItems: "flex-start",
    backgroundColor: "#fff",
    borderColor: "#d6ded8",
    borderRadius: 8,
    borderWidth: 1,
    flexDirection: "row",
    justifyContent: "space-between",
    padding: 12
  },
  actions: {
    alignItems: "flex-end",
    gap: 8
  },
  actionRow: {
    flexDirection: "row",
    gap: 6
  },
  iconButton: {
    alignItems: "center",
    backgroundColor: "#e8efe8",
    borderRadius: 8,
    height: 32,
    justifyContent: "center",
    width: 32
  },
  name: {
    color: "#1f2d2f",
    fontSize: 15,
    fontWeight: "800"
  },
  meta: {
    color: "#60746f",
    fontSize: 13,
    marginTop: 3
  },
  table: {
    color: "#60746f",
    fontSize: 12,
    marginTop: 3
  },
  status: {
    color: "#305f72",
    fontSize: 12,
    fontWeight: "800",
    textTransform: "uppercase"
  }
});
