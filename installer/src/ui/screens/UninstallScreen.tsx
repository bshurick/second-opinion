import { Box, Text } from "ink";
import { useEffect, useState } from "react";
import { InstallError } from "../../engine/errors.js";
import type { Context } from "../../engine/installer.js";
import { planUninstall, uninstall, type UninstallResult } from "../../engine/link.js";
import { tildify } from "../../engine/paths.js";
import { Panel } from "../components/Panel.js";
import { Select } from "../components/Select.js";
import { Spinner } from "../components/Spinner.js";
import { color, glyph } from "../theme.js";

type Choice = "keep" | "purge" | "cancel";

interface Props {
  ctx: Context;
  onDone: (result: UninstallResult | null) => void;
  onFail: (error: InstallError) => void;
}

/** Shows what will go and what stays, then removes it. */
export function UninstallScreen({ ctx, onDone, onFail }: Props) {
  const env = ctx.environ;
  const pretty = (p: string) => p.split(" -> ").map((part) => tildify(part, env)).join(` ${glyph.arrow} `);
  const [choice, setChoice] = useState<Choice | null>(ctx.options.yes ? (ctx.options.purgeData ? "purge" : "keep") : null);
  const [result, setResult] = useState<UninstallResult | null>(null);
  const plan = planUninstall(ctx.target, ctx.link, ctx.data, false);
  const dataExists = plan.keep.some((k) => k.includes("--purge-data"));

  useEffect(() => {
    if (!choice || choice === "cancel") return;
    uninstall(ctx.target, ctx.link, ctx.data, choice === "purge", async () => true)
      .then((r) => {
        setResult(r);
        setTimeout(() => onDone(r), 200);
      })
      .catch((err: unknown) => onFail(err instanceof InstallError ? err : new InstallError(String((err as Error)?.message ?? err))));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [choice]);

  if (result) {
    return (
      <Panel tint={color.ok} title={`${glyph.check} Uninstalled`}>
        {result.removed.map((r) => (
          <Text key={r}>
            <Text color={color.dim}>removed  </Text>
            {tildify(r, env)}
          </Text>
        ))}
        {result.kept.map((k) => (
          <Text key={k} color={color.dim}>
            kept     {k}
          </Text>
        ))}
      </Panel>
    );
  }

  if (choice && choice !== "cancel") {
    return (
      <Box>
        <Spinner />
        <Text> Removing…</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      <Text bold>Uninstall</Text>
      <Box flexDirection="column" marginTop={1} borderStyle="round" borderColor={color.dim} paddingX={1}>
        {plan.remove.length ? (
          plan.remove.map((r) => (
            <Text key={r}>
              <Text color={color.warn}>remove </Text>
              {pretty(r)}
            </Text>
          ))
        ) : (
          <Text color={color.dim}>nothing installed at {tildify(ctx.target, env)}</Text>
        )}
        {dataExists ? (
          <Text>
            <Text color={color.dim}>data   </Text>
            {tildify(ctx.data, env)} <Text color={color.dim}>(venv, ledger, journal, snapshots, caches)</Text>
          </Text>
        ) : null}
      </Box>
      <Box marginTop={1}>
        <Select<Choice>
          options={[
            { value: "keep", label: "Remove the plugin, keep my data", hint: "re-installing later finds the ledger and journal again" },
            ...(dataExists ? [{ value: "purge" as const, label: "Remove everything, including data", warn: true, hint: "cannot be undone" }] : []),
            { value: "cancel", label: "Cancel" },
          ]}
          onSelect={(c) => (c === "cancel" ? onDone(null) : setChoice(c))}
          onCancel={() => onDone(null)}
        />
      </Box>
    </Box>
  );
}
