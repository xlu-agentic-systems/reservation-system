import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

type Props = {
  guestName: string;
  phone: string;
  partySize: number;
  notes: string;
  selectedTime: string;
  onGuestNameChange: (value: string) => void;
  onPhoneChange: (value: string) => void;
  onPartySizeChange: (value: number) => void;
  onNotesChange: (value: string) => void;
  onSubmit: () => void;
  submitting: boolean;
};

export function ReservationForm({
  guestName,
  phone,
  partySize,
  notes,
  selectedTime,
  onGuestNameChange,
  onPhoneChange,
  onPartySizeChange,
  onNotesChange,
  onSubmit,
  submitting
}: Props) {
  return (
    <View style={styles.section}>
      <View style={styles.headingRow}>
        <Ionicons name="calendar-outline" size={18} color="#305f72" />
        <Text style={styles.heading}>Online Reservation</Text>
      </View>
      <View style={styles.fieldRow}>
        <TextInput
          value={guestName}
          onChangeText={onGuestNameChange}
          placeholder="Guest name"
          placeholderTextColor="#7b8b87"
          style={styles.input}
        />
        <TextInput
          value={phone}
          onChangeText={onPhoneChange}
          placeholder="Phone"
          placeholderTextColor="#7b8b87"
          keyboardType="phone-pad"
          style={styles.input}
        />
      </View>
      <View style={styles.partyRow}>
        <Text style={styles.label}>Party</Text>
        <View style={styles.stepper}>
          <Pressable onPress={() => onPartySizeChange(Math.max(1, partySize - 1))} style={styles.iconButton}>
            <Ionicons name="remove" size={18} color="#1f2d2f" />
          </Pressable>
          <Text style={styles.partySize}>{partySize}</Text>
          <Pressable onPress={() => onPartySizeChange(Math.min(12, partySize + 1))} style={styles.iconButton}>
            <Ionicons name="add" size={18} color="#1f2d2f" />
          </Pressable>
        </View>
      </View>
      <TextInput
        value={notes}
        onChangeText={onNotesChange}
        placeholder="Notes"
        placeholderTextColor="#7b8b87"
        style={styles.input}
      />
      <Pressable
        disabled={submitting || !selectedTime}
        onPress={onSubmit}
        style={[styles.submit, (!selectedTime || submitting) && styles.submitDisabled]}
      >
        <Ionicons name="checkmark-circle-outline" size={19} color="#fff" />
        <Text style={styles.submitText}>{submitting ? "Booking" : "Reserve"}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    gap: 12
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
  fieldRow: {
    gap: 10
  },
  input: {
    backgroundColor: "#fff",
    borderColor: "#d6ded8",
    borderRadius: 8,
    borderWidth: 1,
    color: "#1f2d2f",
    fontSize: 15,
    minHeight: 46,
    paddingHorizontal: 12
  },
  partyRow: {
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "space-between"
  },
  label: {
    color: "#475b57",
    fontSize: 15,
    fontWeight: "700"
  },
  stepper: {
    alignItems: "center",
    flexDirection: "row",
    gap: 12
  },
  iconButton: {
    alignItems: "center",
    backgroundColor: "#e8efe8",
    borderRadius: 8,
    height: 36,
    justifyContent: "center",
    width: 36
  },
  partySize: {
    color: "#1f2d2f",
    fontSize: 18,
    fontWeight: "800",
    minWidth: 24,
    textAlign: "center"
  },
  submit: {
    alignItems: "center",
    backgroundColor: "#be5a38",
    borderRadius: 8,
    flexDirection: "row",
    gap: 8,
    justifyContent: "center",
    minHeight: 48
  },
  submitDisabled: {
    opacity: 0.45
  },
  submitText: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "800"
  }
});
