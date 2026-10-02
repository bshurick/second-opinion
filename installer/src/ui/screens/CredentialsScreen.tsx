import { Box, Text } from "ink";
import { useEffect, useState } from "react";
import type { Requirement } from "../../engine/catalog.js";
import { maskSecret, validateEdgarUserAgent, type BrokerChoice, type EnvValues } from "../../engine/env.js";
import { Select } from "../components/Select.js";
import { TextInput } from "../components/TextInput.js";
import { color, glyph } from "../theme.js";

interface Props {
  needs: Set<Requirement>;
  /** Values already known from flags, the environment, or a previous .env. */
  existing: EnvValues;
  /** Brokers whose credentials are already complete; seeds the picker's initial choice. */
  brokers: Set<BrokerChoice>;
  /** --yes: skip the optional EDGAR prompt and the E*Trade environment prompt. */
  acceptDefaults: boolean;
  onDone: (values: EnvValues, brokers: Set<BrokerChoice>) => void;
  onCancel: () => void;
}

type Field = "brokers" | "keep-or-new" | "client-id" | "consumer-key" | "etrade-keep-or-new" | "etrade-key" | "etrade-secret" | "etrade-sandbox" | "edgar" | "done";

function firstField(needs: Set<Requirement>, existing: EnvValues, acceptDefaults: boolean): Field {
  if (needs.has("brokerage")) return "brokers";
  if (needs.has("edgar") && !existing.EDGAR_USER_AGENT && !acceptDefaults) return "edgar";
  return "done";
}

/** "both" when both are already set, else whichever one is, else default to SnapTrade. */
function initialBrokerChoice(brokers: ReadonlySet<BrokerChoice>): "snaptrade" | "etrade" | "both" {
  if (brokers.has("snaptrade") && brokers.has("etrade")) return "both";
  if (brokers.has("etrade")) return "etrade";
  return "snaptrade";
}

/**
 * Asks only for what the selection needs. Secrets are masked as typed and shown
 * afterwards by their last four characters only.
 */
export function CredentialsScreen({ needs, existing, brokers: initialBrokers, acceptDefaults, onDone, onCancel }: Props) {
  const [values, setValues] = useState<EnvValues>({ ...existing });
  const [chosenBrokers, setChosenBrokers] = useState<Set<BrokerChoice>>(initialBrokers);
  const [field, setField] = useState<Field>(() => firstField(needs, existing, acceptDefaults));
  const [completed, setCompleted] = useState<string[]>([]);

  const afterEtrade = (v: EnvValues): Field => (needs.has("edgar") && !v.EDGAR_USER_AGENT && !acceptDefaults ? "edgar" : "done");

  /** Where to go once the E*Trade key+secret (or a kept pair) are settled. */
  const afterEtradeCreds = (): Field => "etrade-sandbox";

  /** Where to go once SnapTrade (or a kept pair) is settled: the E*Trade fields, or past them. */
  const nextAfterSnaptrade = (v: EnvValues, b: Set<BrokerChoice>): Field => {
    if (b.has("etrade")) return v.ETRADE_CONSUMER_KEY && v.ETRADE_CONSUMER_SECRET ? "etrade-keep-or-new" : "etrade-key";
    return afterEtrade(v);
  };

  const finish = (v: EnvValues, b: Set<BrokerChoice>) => {
    setField("done");
    onDone(v, b);
  };

  const applySandboxDefault = (v: EnvValues): EnvValues => ({ ...v, ETRADE_SANDBOX: v.ETRADE_SANDBOX ?? "0" });

  /** After the E*Trade key+secret: ask the sandbox question, unless --yes says skip it. */
  const proceedFromEtradeCreds = (v: EnvValues, b: Set<BrokerChoice>) => {
    if (acceptDefaults) {
      const withDefault = applySandboxDefault(v);
      setValues(withDefault);
      const next = afterEtrade(withDefault);
      if (next === "done") finish(withDefault, b);
      else setField(next);
    } else {
      setField(afterEtradeCreds());
    }
  };

  // Nothing to ask for this selection: hand the known values straight back.
  const nothingToAsk = firstField(needs, existing, acceptDefaults) === "done";
  useEffect(() => {
    if (nothingToAsk) onDone(existing, initialBrokers);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  if (field === "done") return null;

  return (
    <Box flexDirection="column">
      <Text bold>Credentials</Text>
      <Text color={color.dim}>Stored in the plugin's .env (mode 600). Never printed, logged, or sent anywhere but the API that owns them.</Text>
      {completed.map((c) => (
        <Text key={c} color={color.ok}>
          {glyph.check} <Text color={undefined}>{c}</Text>
        </Text>
      ))}
      <Box marginTop={1}>
        {field === "brokers" ? (
          <Box flexDirection="column">
            <Text bold>Which brokerage connection?</Text>
            <Select<"snaptrade" | "etrade" | "both">
              options={[
                { value: "snaptrade", label: "SnapTrade (any brokerage, hosted portal, one free key)" },
                { value: "etrade", label: "E*Trade direct (your developer key, real-time quotes, daily re-auth)" },
                { value: "both", label: "Both" },
              ]}
              initial={initialBrokerChoice(chosenBrokers)}
              onSelect={(choice) => {
                const b: Set<BrokerChoice> = choice === "both" ? new Set(["snaptrade", "etrade"]) : new Set([choice]);
                setChosenBrokers(b);
                if (b.has("snaptrade")) {
                  setField(values.SNAPTRADE_CLIENT_ID && values.SNAPTRADE_CONSUMER_KEY ? "keep-or-new" : "client-id");
                } else if (b.has("etrade")) {
                  setField(values.ETRADE_CONSUMER_KEY && values.ETRADE_CONSUMER_SECRET ? "etrade-keep-or-new" : "etrade-key");
                }
              }}
              onCancel={onCancel}
            />
            <Box flexDirection="column" marginTop={1}>
              <Text color={color.dim}>E*Trade direct uses your own developer key from https://developer.etrade.com and needs a browser login each trading day.</Text>
              <Text color={color.dim}>If the same E*Trade account is also linked through SnapTrade, the direct connection is used for it; the SnapTrade copy is hidden.</Text>
              <Text color={color.dim}>Choosing SnapTrade alone keeps an E*Trade key already in .env; delete the ETRADE_* lines there to turn it off.</Text>
            </Box>
          </Box>
        ) : null}
        {field === "keep-or-new" ? (
          <Box flexDirection="column">
            <Text bold>SnapTrade API key found ({maskSecret(values.SNAPTRADE_CONSUMER_KEY ?? "")})</Text>
            <Box marginTop={1}>
              <Select<"keep" | "new">
                options={[
                  { value: "keep", label: "Keep it" },
                  { value: "new", label: "Enter a new key" },
                ]}
                onSelect={(choice) => {
                  if (choice === "keep") {
                    setCompleted((c) => [...c, `SnapTrade key kept (${maskSecret(values.SNAPTRADE_CONSUMER_KEY ?? "")})`]);
                    const next = nextAfterSnaptrade(values, chosenBrokers);
                    if (next === "done") finish(values, chosenBrokers);
                    else setField(next);
                  } else setField("client-id");
                }}
                onCancel={() => setField("brokers")}
              />
            </Box>
          </Box>
        ) : null}
        {field === "client-id" ? (
          <TextInput
            label="SnapTrade client id"
            help={["Free Personal API key: sign in at https://dashboard.snaptrade.com (2FA required), then https://dashboard.snaptrade.com/api-key"]}
            placeholder="e.g. YOUR-NAME-ABC123"
            onSubmit={(v) => {
              setValues((cur) => ({ ...cur, SNAPTRADE_CLIENT_ID: v }));
              setCompleted((c) => [...c, `SnapTrade client id ${v}`]);
              setField("consumer-key");
            }}
            onCancel={() => setField("brokers")}
          />
        ) : null}
        {field === "consumer-key" ? (
          <TextInput
            label="SnapTrade consumer key"
            help={["Shown once on the dashboard; paste it here. Input is hidden."]}
            mask
            onSubmit={(v) => {
              const next = { ...values, SNAPTRADE_CONSUMER_KEY: v };
              setValues(next);
              setCompleted((c) => [...c, `SnapTrade consumer key ${maskSecret(v)}`]);
              const after = nextAfterSnaptrade(next, chosenBrokers);
              if (after === "done") finish(next, chosenBrokers);
              else setField(after);
            }}
            onCancel={() => setField("client-id")}
          />
        ) : null}
        {field === "etrade-keep-or-new" ? (
          <Box flexDirection="column">
            <Text bold>E*Trade key found ({maskSecret(values.ETRADE_CONSUMER_SECRET ?? "")})</Text>
            <Box marginTop={1}>
              <Select<"keep" | "new">
                options={[
                  { value: "keep", label: "Keep it" },
                  { value: "new", label: "Enter a new key" },
                ]}
                onSelect={(choice) => {
                  if (choice === "keep") {
                    setCompleted((c) => [...c, `E*Trade key kept (${maskSecret(values.ETRADE_CONSUMER_SECRET ?? "")})`]);
                    proceedFromEtradeCreds(values, chosenBrokers);
                  } else setField("etrade-key");
                }}
                onCancel={() => setField("brokers")}
              />
            </Box>
          </Box>
        ) : null}
        {field === "etrade-key" ? (
          <TextInput
            label="E*Trade consumer key"
            help={["Apply at https://developer.etrade.com; the key is tied to your own E*Trade login"]}
            mask
            onSubmit={(v) => {
              setValues((cur) => ({ ...cur, ETRADE_CONSUMER_KEY: v }));
              setCompleted((c) => [...c, `E*Trade consumer key ${maskSecret(v)}`]);
              setField("etrade-secret");
            }}
            onCancel={() => setField("brokers")}
          />
        ) : null}
        {field === "etrade-secret" ? (
          <TextInput
            label="E*Trade consumer secret"
            help={["Shown once on the developer dashboard; paste it here. Input is hidden."]}
            mask
            onSubmit={(v) => {
              const next = { ...values, ETRADE_CONSUMER_SECRET: v };
              setValues(next);
              setCompleted((c) => [...c, `E*Trade consumer secret ${maskSecret(v)}`]);
              proceedFromEtradeCreds(next, chosenBrokers);
            }}
            onCancel={() => setField("etrade-key")}
          />
        ) : null}
        {field === "etrade-sandbox" ? (
          <Box flexDirection="column">
            <Text bold>E*Trade environment</Text>
            <Box marginTop={1}>
              <Select<"prod" | "sandbox">
                options={[
                  { value: "prod", label: "Live (api.etrade.com)" },
                  { value: "sandbox", label: "Sandbox (apisb.etrade.com, fake accounts)" },
                ]}
                initial={existing.ETRADE_SANDBOX === "1" ? "sandbox" : "prod"}
                onSelect={(choice) => {
                  const next = { ...values, ETRADE_SANDBOX: choice === "sandbox" ? "1" : "0" };
                  setValues(next);
                  setCompleted((c) => [...c, `E*Trade environment ${choice === "sandbox" ? "sandbox" : "live"}`]);
                  const after = afterEtrade(next);
                  if (after === "done") finish(next, chosenBrokers);
                  else setField(after);
                }}
                onCancel={() => setField("etrade-secret")}
              />
            </Box>
          </Box>
        ) : null}
        {field === "edgar" ? (
          <TextInput
            label="SEC EDGAR contact (optional)"
            help={[
              "fundamental-research reads SEC filings; the SEC requires a User-Agent with a contact address on every request.",
              "Form: app-name contact@email   Enter with nothing to skip (the skill will warn until you set it).",
            ]}
            placeholder="second-opinion me@example.com"
            allowEmpty
            validate={validateEdgarUserAgent}
            onSubmit={(v) => {
              const next = { ...values, ...(v ? { EDGAR_USER_AGENT: v } : {}) };
              setValues(next);
              setCompleted((c) => [...c, v ? `EDGAR contact ${v}` : "EDGAR contact skipped"]);
              finish(next, chosenBrokers);
            }}
            onCancel={onCancel}
          />
        ) : null}
      </Box>
    </Box>
  );
}
