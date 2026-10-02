import { Box, Text } from "ink";
import type { InstalledRecord } from "../../engine/materialize.js";
import { Select } from "../components/Select.js";
import { color } from "../theme.js";

export type Mode = "update" | "change" | "extras" | "uninstall" | "quit";

interface Props {
  previous: InstalledRecord;
  onSelect: (mode: Mode) => void;
}

/** Shown only when an install already exists. */
export function ModeScreen({ previous, onSelect }: Props) {
  const n = previous.skills.length;
  return (
    <Box flexDirection="column">
      <Text bold>An install already exists. What would you like to do?</Text>
      <Box marginY={1}>
        <Select<Mode>
          options={[
            { value: "update", label: "Update", hint: `refresh the same ${n} skills from this checkout` },
            { value: "change", label: "Change skills", hint: "add or remove skills, then update" },
            { value: "extras", label: "Change extras", hint: "turn optional extras on or off, keep everything else" },
            { value: "uninstall", label: "Uninstall", hint: "remove the plugin; your data stays unless you say otherwise", warn: true },
            { value: "quit", label: "Quit", hint: "leave everything as it is" },
          ]}
          onSelect={onSelect}
        />
      </Box>
      <Text color={color.dim}>Installed skills: {previous.skills.join(", ")}</Text>
    </Box>
  );
}
