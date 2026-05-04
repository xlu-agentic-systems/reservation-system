import { Ionicons } from "@expo/vector-icons";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { AvailabilitySlot } from "../types/reservation";

type Props = {
  slots: AvailabilitySlot[];
  selectedTime: string;
  onSelect: (time: string) => void;
};

export function AvailabilityStrip({ slots, selectedTime, onSelect }: Props) {
  return (
    <View style={styles.section}>
      <View style={styles.headingRow}>
        <Ionicons name="time-outline" size={18} color="#305f72" />
        <Text style={styles.heading}>Availability</Text>
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.list}>
        {slots.map((slot) => {
          const selected = slot.reservation_time === selectedTime;
          return (
            <Pressable
              key={slot.reservation_time}
              disabled={!slot.available}
              onPress={() => onSelect(slot.reservation_time)}
              style={[styles.slot, selected && styles.slotSelected, !slot.available && styles.slotDisabled]}
            >
              <Text style={[styles.time, selected && styles.slotSelectedText]}>
                {formatTime(slot.reservation_time)}
              </Text>
              <Text style={[styles.seats, selected && styles.slotSelectedText]}>
                {slot.seats_remaining} seats
              </Text>
              <Text style={[styles.tables, selected && styles.slotSelectedText]}>
                {slot.table_names.length ? slot.table_names.join("+") : "No table"}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>
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
  list: {
    gap: 8,
    paddingRight: 20
  },
  slot: {
    alignItems: "center",
    backgroundColor: "#fff",
    borderColor: "#d6ded8",
    borderRadius: 8,
    borderWidth: 1,
    minWidth: 92,
    paddingHorizontal: 12,
    paddingVertical: 10
  },
  slotSelected: {
    backgroundColor: "#305f72",
    borderColor: "#305f72"
  },
  slotDisabled: {
    opacity: 0.45
  },
  slotSelectedText: {
    color: "#fff"
  },
  time: {
    color: "#1f2d2f",
    fontSize: 14,
    fontWeight: "700"
  },
  seats: {
    color: "#60746f",
    fontSize: 12,
    marginTop: 2
  },
  tables: {
    color: "#60746f",
    fontSize: 11,
    marginTop: 2
  }
});
