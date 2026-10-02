import { Box, Text, useInput, useStdout } from "ink";
import { useMemo, useState } from "react";
import { families, requirementsFor, type Skill } from "../../engine/catalog.js";
import { resolveSelection, toggleSkill } from "../../engine/selection.js";
import { KeyHints } from "../components/KeyHints.js";
import { color, glyph } from "../theme.js";

interface Props {
  catalog: Skill[];
  initial: string[];
  onDone: (selected: string[]) => void;
  onCancel?: () => void;
  /** Heading; the default is "Choose the skills to install". */
  title?: string;
}

type Row = { kind: "family"; family: string } | { kind: "skill"; skill: Skill };

function buildRows(catalog: Skill[]): Row[] {
  const rows: Row[] = [];
  for (const fam of families(catalog)) {
    rows.push({ kind: "family", family: fam });
    for (const s of catalog) if (s.family === fam) rows.push({ kind: "skill", skill: s });
  }
  return rows;
}

const BADGE: Record<string, { text: string; tint: string }> = {
  brokerage: { text: "key", tint: color.key },
  edgar: { text: "edgar", tint: color.edgar },
};

/**
 * Checklist grouped by family. Toggling keeps dependencies consistent and explains
 * every automatic change in a note under the list.
 */
export function SkillPickerScreen({ catalog, initial, onDone, onCancel, title = "Choose the skills to install" }: Props) {
  const rows = useMemo(() => buildRows(catalog), [catalog]);
  const skillIndexes = useMemo(() => rows.map((r, i) => (r.kind === "skill" ? i : -1)).filter((i) => i >= 0), [rows]);
  const [selected, setSelected] = useState<Set<string>>(() => new Set(resolveSelection(catalog, initial).names));
  const [cursor, setCursor] = useState(skillIndexes[0] ?? 0);
  const [note, setNote] = useState<string | null>(null);
  const { stdout } = useStdout();

  // Each family after the first adds a blank spacer line; reserve for header, description, and footer too.
  const familyCount = families(catalog).length;
  const rowsAvailable = Math.max(6, (stdout?.rows ?? 40) - 14 - Math.max(0, familyCount - 1));
  const viewportStart = Math.min(Math.max(0, cursor - Math.floor(rowsAvailable / 2)), Math.max(0, rows.length - rowsAvailable));
  const visible = rows.slice(viewportStart, viewportStart + rowsAvailable);

  const move = (delta: number) => {
    const pos = skillIndexes.indexOf(cursor);
    const next = (pos + delta + skillIndexes.length) % skillIndexes.length;
    setCursor(skillIndexes[next]!);
  };

  const apply = (names: string[], notes: string[]) => {
    setSelected(new Set(names));
    setNote(notes.length ? notes.join("; ") : null);
  };

  useInput((input, key) => {
    if (key.upArrow || input === "k") move(-1);
    else if (key.downArrow || input === "j") move(1);
    else if (input === " ") {
      const row = rows[cursor];
      if (row?.kind === "skill") {
        const r = toggleSkill(catalog, selected, row.skill.name);
        apply(r.names, r.notes);
      }
    } else if (input === "a") apply(catalog.map((s) => s.name), []);
    else if (input === "n") apply([], []);
    else if (input === "f") {
      // Toggle the whole family under the cursor: all on unless every member is already on.
      const row = rows[cursor];
      if (row?.kind === "skill") {
        const members = catalog.filter((s) => s.family === row.skill.family).map((s) => s.name);
        const allOn = members.every((m) => selected.has(m));
        let names = [...selected];
        let notes: string[] = [];
        if (allOn) {
          const r = resolveSelection(catalog, names.filter((n) => !members.includes(n)), { dropDependents: true });
          names = r.names;
          notes = r.notes;
        } else {
          const r = resolveSelection(catalog, [...names, ...members]);
          names = r.names;
          notes = r.notes;
        }
        apply(names, notes);
      }
    } else if (key.return) {
      if (selected.size === 0) setNote("select at least one skill (press a for all)");
      else onDone(catalog.filter((s) => selected.has(s.name)).map((s) => s.name));
    } else if (key.escape && onCancel) onCancel();
  });

  const current = rows[cursor];
  const needs = requirementsFor(catalog, selected);
  const keyCount = catalog.filter((s) => selected.has(s.name) && s.requires.includes("brokerage")).length;

  return (
    <Box flexDirection="column">
      <Text bold>{title}</Text>
      <Text color={color.dim}>
        Fewer skills means a shorter skill list in every Claude session. <Text color={color.key}>key</Text> needs a brokerage connection (SnapTrade or E*Trade); <Text color={color.edgar}>edgar</Text> needs an SEC contact.
      </Text>
      <Box flexDirection="column" marginTop={1}>
        {viewportStart > 0 ? <Text color={color.dim}>  ↑ {viewportStart} more</Text> : null}
        {visible.map((row, i) => {
          const index = viewportStart + i;
          if (row.kind === "family") {
            const members = catalog.filter((s) => s.family === row.family);
            const on = members.filter((s) => selected.has(s.name)).length;
            return (
              <Box key={`f:${row.family}`} marginTop={index === 0 ? 0 : 1}>
                <Text bold color={color.accent}>
                  {row.family}
                </Text>
                <Text color={color.dim}>
                  {"  "}
                  {on}/{members.length}
                </Text>
              </Box>
            );
          }
          const s = row.skill;
          const active = index === cursor;
          const on = selected.has(s.name);
          return (
            <Box key={s.name}>
              <Text color={color.accent}>{active ? glyph.pointer : " "} </Text>
              <Text color={on ? color.ok : color.dim}>{on ? glyph.on : glyph.off} </Text>
              <Text bold={active} color={active ? color.accent : on ? undefined : color.dim}>
                {s.name}
              </Text>
              {s.requires.map((r) => (
                <Text key={r} color={BADGE[r]?.tint}>
                  {" "}
                  {BADGE[r]?.text}
                </Text>
              ))}
              {s.dependsOn.length ? <Text color={color.dim}> needs {s.dependsOn.join(", ")}</Text> : null}
            </Box>
          );
        })}
        {viewportStart + rowsAvailable < rows.length ? <Text color={color.dim}>  ↓ {rows.length - viewportStart - rowsAvailable} more</Text> : null}
      </Box>
      <Box marginTop={1} minHeight={2} flexDirection="column">
        {current?.kind === "skill" ? (
          <Text color={color.dim} wrap="wrap">
            {current.skill.description}
          </Text>
        ) : null}
      </Box>
      <Box minHeight={1}>{note ? <Text color={color.warn}>{glyph.warn} {note}</Text> : null}</Box>
      <Box marginTop={1} flexDirection="column">
        <Text>
          <Text bold>{selected.size}</Text> of {catalog.length} selected
          {keyCount ? <Text color={color.dim}> {glyph.dot} {keyCount} need a brokerage key</Text> : <Text color={color.dim}> {glyph.dot} no brokerage key needed</Text>}
          {needs.has("edgar") ? <Text color={color.dim}> {glyph.dot} EDGAR contact needed</Text> : null}
        </Text>
        <KeyHints hints={[["↑↓", "move"], ["space", "toggle"], ["f", "family"], ["a", "all"], ["n", "none"], ["enter", "continue"]]} />
      </Box>
    </Box>
  );
}
