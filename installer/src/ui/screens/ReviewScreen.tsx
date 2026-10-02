import { Box, Text } from "ink";
import { loadExtras } from "../../engine/catalog.js";
import type { Context, Plan } from "../../engine/installer.js";
import { describeLinkState } from "../../engine/link.js";
import { tildify } from "../../engine/paths.js";
import { KeyValue as Line } from "../components/KeyValue.js";
import { Select } from "../components/Select.js";
import { color, glyph } from "../theme.js";

export type ReviewChoice = "install" | "install-replace-link" | "install-no-link" | "back" | "quit";

interface Props {
  ctx: Context;
  plan: Plan;
  onChoose: (choice: ReviewChoice) => void;
}

const list = (xs: string[]) => (xs.length ? xs.join(", ") : "none");

/** Everything that is about to happen, then one choice. */
export function ReviewScreen({ ctx, plan, onChoose }: Props) {
  const env = ctx.environ;
  const extrasOn = loadExtras(ctx.root).filter((e) => plan.extrasState[e.key]).map((e) => e.label);
  const conflict = plan.linkState.kind !== "absent" && plan.linkState.kind !== "ours";
  const envKeys = [
    ...(plan.brokers.has("snaptrade") ? ["SNAPTRADE_CLIENT_ID", "SNAPTRADE_CONSUMER_KEY"] : []),
    ...(plan.brokers.has("etrade") ? ["ETRADE_CONSUMER_KEY", "ETRADE_CONSUMER_SECRET", "ETRADE_SANDBOX"] : []),
    ...(plan.needs.has("edgar") && plan.values.EDGAR_USER_AGENT ? ["EDGAR_USER_AGENT"] : []),
  ];
  const options: { value: ReviewChoice; label: string; hint?: string; warn?: boolean }[] = conflict
    ? [
        { value: "install-replace-link", label: "Install and replace the link", hint: "what is there now is removed", warn: true },
        { value: "install-no-link", label: "Install without linking", hint: `run with: claude --plugin-dir ${tildify(ctx.target, env)}` },
        { value: "back", label: "Back to skills" },
        { value: "quit", label: "Quit" },
      ]
    : [
        { value: "install", label: ctx.configure ? "Save" : plan.previous ? "Update" : "Install" },
        { value: "back", label: ctx.configure ? "Back to extras" : "Back to skills" },
        { value: "quit", label: "Quit" },
      ];

  return (
    <Box flexDirection="column">
      <Text bold>Review</Text>
      <Box flexDirection="column" marginTop={1} borderStyle="round" borderColor={color.dim} paddingX={1}>
        {ctx.configure ? (
          <Line k="skills">
            <Text color={color.dim}>every skill, managed by Claude Code /plugin</Text>
          </Line>
        ) : null}
        {ctx.configure ? null : <Line k="skills">
          <Text>
            <Text color={color.ok}>{plan.diff.installed.length} new</Text>
            {plan.previous ? (
              <Text>
                {" "}{glyph.dot} {plan.diff.refreshed.length} refreshed {glyph.dot}{" "}
                <Text color={plan.diff.removed.length ? color.warn : undefined}>{plan.diff.removed.length} removed</Text>
              </Text>
            ) : null}
            <Text color={color.dim}> {glyph.dot} setup always included</Text>
          </Text>
        </Line>}
        {!ctx.configure && plan.diff.installed.length ? (
          <Line k="">
            <Text color={color.dim} wrap="wrap">
              + {list(plan.diff.installed)}
            </Text>
          </Line>
        ) : null}
        {!ctx.configure && plan.diff.removed.length ? (
          <Line k="">
            <Text color={color.warn} wrap="wrap">
              − {list(plan.diff.removed)}
            </Text>
          </Line>
        ) : null}
        <Line k="extras">
          <Text wrap="wrap">{extrasOn.length ? `on: ${extrasOn.join(", ")}` : "all off"}</Text>
        </Line>
        <Line k="python">
          <Text>
            {plan.python.version} <Text color={color.dim}>{glyph.arrow} venv at {tildify(`${ctx.data}/venv`, env)}</Text>
          </Text>
        </Line>
        {ctx.configure ? null : (
          <Line k="files">
            <Text>{tildify(ctx.target, env)}</Text>
          </Line>
        )}
        <Line k="settings">
          <Text>{tildify(ctx.data, env)}</Text>
          <Text color={color.dim}> (.env, installed.json; kept across updates)</Text>
        </Line>
        <Line k=".env">
          <Text>{envKeys.length ? envKeys.join(", ") : "no credentials needed"}</Text>
          {plan.preserved.length ? <Text color={color.dim}> (+{plan.preserved.length} of your own lines kept)</Text> : null}
        </Line>
        {plan.leftovers.length ? (
          <Line k="old copy">
            <Text color={color.warn} wrap="wrap">
              removes {plan.leftovers.map((p) => tildify(p, env)).join(", ")} (your data stays)
            </Text>
          </Line>
        ) : null}
        {ctx.configure ? null : <Line k="link">
          {ctx.options.noLink ? (
            <Text color={color.dim}>skipped (--no-link)</Text>
          ) : plan.linkState.kind === "ours" ? (
            <Text>
              {tildify(ctx.link, env)} <Text color={color.dim}>(already points here)</Text>
            </Text>
          ) : plan.linkState.kind === "absent" ? (
            <Text>{tildify(ctx.link, env)}</Text>
          ) : (
            <Text color={color.warn}>
              {glyph.warn} {describeLinkState(tildify(ctx.link, env), plan.linkState)}
            </Text>
          )}
        </Line>}
        {plan.warnings.map((w) => (
          <Line key={w} k="note">
            <Text color={color.warn} wrap="wrap">
              {w}
            </Text>
          </Line>
        ))}
      </Box>
      <Box marginTop={1}>
        <Select<ReviewChoice> options={options} onSelect={onChoose} onCancel={() => onChoose("back")} />
      </Box>
    </Box>
  );
}
