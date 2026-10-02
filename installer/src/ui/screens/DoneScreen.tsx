import { Box, Text } from "ink";
import type { Context, Summary } from "../../engine/installer.js";
import { tildify } from "../../engine/paths.js";
import { KeyValue } from "../components/KeyValue.js";
import { Panel } from "../components/Panel.js";
import { suggestions } from "../suggestions.js";
import { color, glyph } from "../theme.js";

interface Props {
  ctx: Context;
  summary: Summary;
  /** True when this run was an update of an existing install. */
  updated: boolean;
}

export function DoneScreen({ ctx, summary, updated }: Props) {
  const env = ctx.environ;
  const total = summary.skills.installed.length + summary.skills.refreshed.length;
  const smokeOk = !Object.values(summary.smoke).includes("failed");
  const hasKeys = summary.smoke.status !== "no_keys" || summary.smoke.etrade !== "no_keys";
  const tries = suggestions([...summary.skills.installed, ...summary.skills.refreshed], hasKeys, {
    etradeNeedsLogin: summary.smoke.etrade === "no_login",
  });
  return (
    <Box flexDirection="column">
      <Panel tint={color.ok} title={summary.mode === "configure" ? `${glyph.check} Configured` : `${glyph.check} ${updated ? "Updated" : "Installed"} ${total} skill${total === 1 ? "" : "s"}`}>
        <Box flexDirection="column" marginTop={1}>
          {summary.mode !== "configure" && summary.skills.installed.length ? (
            <KeyValue k="new">
              <Text wrap="wrap">{summary.skills.installed.join(", ")}</Text>
            </KeyValue>
          ) : null}
          {summary.mode !== "configure" && summary.skills.refreshed.length ? (
            <KeyValue k="refreshed">
              <Text wrap="wrap">{summary.skills.refreshed.join(", ")}</Text>
            </KeyValue>
          ) : null}
          {summary.mode !== "configure" && summary.skills.removed.length ? (
            <KeyValue k="removed">
              <Text wrap="wrap">{summary.skills.removed.join(", ")}</Text>
            </KeyValue>
          ) : null}
          <KeyValue k="plugin">
            <Text>{tildify(summary.target, env)}</Text>
          </KeyValue>
          <KeyValue k="settings">
            <Text>{tildify(summary.data, env)}</Text>
          </KeyValue>
          {summary.mode === "configure" ? null : (
            <KeyValue k="link">{summary.link ? <Text>{tildify(summary.link, env)}</Text> : <Text color={color.warn}>not linked</Text>}</KeyValue>
          )}
          <KeyValue k="smoke">
            <Text color={smokeOk ? undefined : color.warn}>
              imports {summary.smoke.imports} {glyph.dot} dcf {summary.smoke.dcf} {glyph.dot} status {summary.smoke.status}
              {summary.smoke.etrade !== "no_keys" ? (
                <>
                  {" "}
                  {glyph.dot} etrade {summary.smoke.etrade}
                </>
              ) : null}
            </Text>
          </KeyValue>
        </Box>
        {summary.notes.length ? (
          <Box flexDirection="column" marginTop={1}>
            {summary.notes.map((n) => (
              <Text key={n} color={color.dim} wrap="wrap">
                {n}
              </Text>
            ))}
          </Box>
        ) : null}
        {summary.warnings.length ? (
          <Box flexDirection="column" marginTop={1}>
            {summary.warnings.map((w) => (
              <Text key={w} color={color.warn} wrap="wrap">
                {glyph.warn} {w}
              </Text>
            ))}
          </Box>
        ) : null}
      </Panel>
      <Box flexDirection="column" marginTop={1}>
        <Text bold>Next</Text>
        <Text>
          <Text color={color.accent}>1.</Text>{" "}
          {summary.mode === "configure" ? "Start a new Claude Code session, or run" : summary.link ? "Start Claude Code:" : "Start Claude Code with the plugin:"}{" "}
          <Text bold>{summary.mode === "configure" ? "/reload-plugins" : summary.link ? "claude" : `claude --plugin-dir ${tildify(summary.target, env)}`}</Text>
        </Text>
        {tries.map((t, i) => (
          <Text key={t.prompt}>
            <Text color={color.accent}>{i + 2}.</Text> {i === 0 ? "Ask it to " : "Then "}
            <Text bold>{t.prompt}</Text>
            {t.note ? <Text color={color.dim}> ({t.note})</Text> : null}
          </Text>
        ))}
        <Box marginTop={1}>
          <Text color={color.dim}>
            {summary.mode === "configure" ? "Re-run node install.js any time to change keys or extras." : "Re-run node install.js any time to add or remove skills or pick up a newer checkout."}
          </Text>
        </Box>
      </Box>
    </Box>
  );
}
