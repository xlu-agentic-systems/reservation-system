import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { CallAgentResponse } from "../types/reservation";

type Props = {
  utterance: string;
  response: CallAgentResponse | null;
  onUtteranceChange: (value: string) => void;
  onSend: () => void;
  sending: boolean;
};

export function AgentCallConsole({ utterance, response, onUtteranceChange, onSend, sending }: Props) {
  return (
    <View style={styles.section}>
      <View style={styles.headingRow}>
        <Ionicons name="call-outline" size={18} color="#305f72" />
        <Text style={styles.heading}>AI Call Agent</Text>
      </View>
      <TextInput
        value={utterance}
        onChangeText={onUtteranceChange}
        multiline
        placeholder="Caller: I need a table for four tomorrow at 7 pm under Maya Stone, 555-123-4567"
        placeholderTextColor="#7b8b87"
        style={styles.textArea}
      />
      <Pressable disabled={sending || !utterance.trim()} onPress={onSend} style={styles.sendButton}>
        <Ionicons name="send-outline" size={18} color="#fff" />
        <Text style={styles.sendText}>{sending ? "Sending" : "Send Turn"}</Text>
      </Pressable>
      {response ? (
        <View style={styles.response}>
          <Text style={styles.responseAction}>{response.action}</Text>
          <Text style={styles.responseMessage}>{response.message}</Text>
        </View>
      ) : null}
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
  textArea: {
    backgroundColor: "#fff",
    borderColor: "#d6ded8",
    borderRadius: 8,
    borderWidth: 1,
    color: "#1f2d2f",
    fontSize: 15,
    minHeight: 92,
    padding: 12,
    textAlignVertical: "top"
  },
  sendButton: {
    alignItems: "center",
    alignSelf: "flex-start",
    backgroundColor: "#305f72",
    borderRadius: 8,
    flexDirection: "row",
    gap: 8,
    minHeight: 42,
    paddingHorizontal: 14
  },
  sendText: {
    color: "#fff",
    fontWeight: "800"
  },
  response: {
    backgroundColor: "#fff",
    borderColor: "#d6ded8",
    borderRadius: 8,
    borderWidth: 1,
    padding: 12
  },
  responseAction: {
    color: "#be5a38",
    fontSize: 12,
    fontWeight: "800",
    textTransform: "uppercase"
  },
  responseMessage: {
    color: "#1f2d2f",
    fontSize: 15,
    marginTop: 4
  }
});
