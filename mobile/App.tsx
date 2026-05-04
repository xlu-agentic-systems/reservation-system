import { StatusBar } from "expo-status-bar";
import { useEffect, useMemo, useState } from "react";
import { Alert, SafeAreaView, ScrollView, StyleSheet, Text, View } from "react-native";

import { AgentCallConsole } from "./src/components/AgentCallConsole";
import { AvailabilityStrip } from "./src/components/AvailabilityStrip";
import { ReservationForm } from "./src/components/ReservationForm";
import { ReservationList } from "./src/components/ReservationList";
import { createReservation, fetchAvailability, fetchReservations, sendCallTurn } from "./src/api/client";
import { AvailabilitySlot, CallAgentResponse, Reservation } from "./src/types/reservation";

export default function App() {
  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const [partySize, setPartySize] = useState(2);
  const [guestName, setGuestName] = useState("");
  const [phone, setPhone] = useState("");
  const [notes, setNotes] = useState("");
  const [selectedTime, setSelectedTime] = useState("");
  const [slots, setSlots] = useState<AvailabilitySlot[]>([]);
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [utterance, setUtterance] = useState("");
  const [agentResponse, setAgentResponse] = useState<CallAgentResponse | null>(null);
  const [sendingTurn, setSendingTurn] = useState(false);

  async function refresh() {
    const [nextSlots, nextReservations] = await Promise.all([
      fetchAvailability(today, partySize),
      fetchReservations(today)
    ]);
    setSlots(nextSlots);
    setReservations(nextReservations);
    if (!selectedTime || !nextSlots.some((slot) => slot.reservation_time === selectedTime && slot.available)) {
      setSelectedTime(nextSlots.find((slot) => slot.available)?.reservation_time ?? "");
    }
  }

  useEffect(() => {
    refresh().catch((error: Error) => Alert.alert("Backend unavailable", error.message));
  }, [partySize]);

  async function handleSubmit() {
    if (!guestName.trim() || !phone.trim() || !selectedTime) {
      Alert.alert("Missing details", "Guest name, phone, and time are required.");
      return;
    }
    setSubmitting(true);
    try {
      await createReservation({
        guest_name: guestName,
        phone,
        party_size: partySize,
        reservation_time: selectedTime,
        notes
      });
      setGuestName("");
      setPhone("");
      setNotes("");
      await refresh();
    } catch (error) {
      Alert.alert("Reservation failed", error instanceof Error ? error.message : "Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSendTurn() {
    setSendingTurn(true);
    try {
      const response = await sendCallTurn(utterance, "mobile-demo-session");
      setAgentResponse(response);
      if (response.reservation) {
        setUtterance("");
        await refresh();
      }
    } catch (error) {
      Alert.alert("Agent failed", error instanceof Error ? error.message : "Please try again.");
    } finally {
      setSendingTurn(false);
    }
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar style="dark" />
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.header}>
          <Text style={styles.title}>Juniper Table</Text>
          <Text style={styles.subtitle}>Reservations synchronized across online and phone channels</Text>
        </View>
        <AvailabilityStrip slots={slots} selectedTime={selectedTime} onSelect={setSelectedTime} />
        <ReservationForm
          guestName={guestName}
          phone={phone}
          partySize={partySize}
          notes={notes}
          selectedTime={selectedTime}
          onGuestNameChange={setGuestName}
          onPhoneChange={setPhone}
          onPartySizeChange={setPartySize}
          onNotesChange={setNotes}
          onSubmit={handleSubmit}
          submitting={submitting}
        />
        <AgentCallConsole
          utterance={utterance}
          response={agentResponse}
          onUtteranceChange={setUtterance}
          onSend={handleSendTurn}
          sending={sendingTurn}
        />
        <ReservationList reservations={reservations} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    backgroundColor: "#f7f4ef",
    flex: 1
  },
  content: {
    gap: 24,
    padding: 20,
    paddingBottom: 40
  },
  header: {
    gap: 4,
    paddingTop: 8
  },
  title: {
    color: "#1f2d2f",
    fontSize: 30,
    fontWeight: "900"
  },
  subtitle: {
    color: "#60746f",
    fontSize: 15,
    lineHeight: 21
  }
});
