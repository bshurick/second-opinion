import { render } from "ink-testing-library";
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type { Requirement } from "../src/engine/catalog.js";
import { loadCatalog, loadExtras } from "../src/engine/catalog.js";
import type { ExtrasState } from "../src/engine/extras.js";
import { App } from "../src/ui/App.js";
import { ExtrasScreen } from "../src/ui/screens/ExtrasScreen.js";
import { ModeScreen } from "../src/ui/screens/ModeScreen.js";
import type { BrokerChoice, EnvValues } from "../src/engine/env.js";
import { buildPlan, createContext, type Preflight, type Summary } from "../src/engine/installer.js";
import { Select } from "../src/ui/components/Select.js";
import { Steps } from "../src/ui/components/Steps.js";
import { TextInput } from "../src/ui/components/TextInput.js";
import { CredentialsScreen } from "../src/ui/screens/CredentialsScreen.js";
import { DoneScreen } from "../src/ui/screens/DoneScreen.js";
import { ReviewScreen } from "../src/ui/screens/ReviewScreen.js";
import { SkillPickerScreen } from "../src/ui/screens/SkillPickerScreen.js";
import { UninstallScreen } from "../src/ui/screens/UninstallScreen.js";
import { extrasRoot, FakeRunner, miniRoot, opts, tmpDir } from "./helpers.js";

const ENTER = "\r";
const ESCAPE = "";
const DOWN = "[B";
const tick = () => new Promise((r) => setTimeout(r, 20));

describe("Select", () => {
  it("moves with arrows, selects with enter, and jumps with numbers", async () => {
    const chosen: string[] = [];
    const { lastFrame, stdin } = render(
      <Select options={[{ value: "a", label: "First", hint: "one" }, { value: "b", label: "Second" }]} onSelect={(v) => chosen.push(v)} />,
    );
    expect(lastFrame()).toContain("❯ 1. First");
    expect(lastFrame()).toContain("one");
    stdin.write(DOWN);
    await tick();
    expect(lastFrame()).toContain("❯ 2. Second");
    stdin.write(ENTER);
    await tick();
    expect(chosen).toEqual(["b"]);
    stdin.write("1");
    await tick();
    expect(chosen).toEqual(["b", "a"]);
  });
});

describe("TextInput", () => {
  it("masks secrets, validates, and submits on a pasted newline", async () => {
    const got: string[] = [];
    const { lastFrame, stdin } = render(<TextInput label="Key" mask onSubmit={(v) => got.push(v)} />);
    stdin.write("abc");
    await tick();
    expect(lastFrame()).toContain("•••");
    expect(lastFrame()).not.toContain("abc");
    stdin.write(ENTER);
    await tick();
    expect(got).toEqual(["abc"]);
    const v2: string[] = [];
    const second = render(<TextInput label="Agent" validate={(v) => (v.includes("@") ? null : "needs an @")} onSubmit={(v) => v2.push(v)} />);
    second.stdin.write("nope");
    await tick();
    second.stdin.write(ENTER);
    await tick();
    expect(second.lastFrame()).toContain("✖ needs an @");
    expect(v2).toEqual([]);
    const third = render(<TextInput label="Id" onSubmit={(v) => v2.push(v)} />);
    third.stdin.write("pasted-id\n");
    await tick();
    expect(v2).toEqual(["pasted-id"]);
    const empty = render(<TextInput label="Id" onSubmit={(v) => v2.push(v)} />);
    empty.stdin.write(ENTER);
    await tick();
    expect(empty.lastFrame()).toContain("a value is required");
  });
});

describe("SkillPickerScreen", () => {
  const catalog = loadCatalog(miniRoot());

  it("toggles with space, explains dependency changes, and returns the selection on enter", async () => {
    let result: string[] | null = null;
    const { lastFrame, stdin } = render(<SkillPickerScreen catalog={catalog} initial={["a", "b", "c"]} onDone={(s) => (result = s)} />);
    expect(lastFrame()).toContain("Fam one");
    expect(lastFrame()).toContain("3 of 3 selected");
    expect(lastFrame()).toContain("◉ a key");
    stdin.write(" "); // deselect a → b follows
    await tick();
    expect(lastFrame()).toContain("○ a key");
    expect(lastFrame()).toContain("○ b");
    expect(lastFrame()).toContain("b needs a: also deselected b");
    expect(lastFrame()).toContain("1 of 3 selected");
    expect(lastFrame()).toContain("no brokerage key needed");
    stdin.write(DOWN);
    await tick();
    stdin.write(" "); // select b → a comes back
    await tick();
    expect(lastFrame()).toContain("b needs a: added a");
    expect(lastFrame()).toContain("3 of 3 selected");
    stdin.write("n");
    await tick();
    stdin.write(ENTER);
    await tick();
    expect(lastFrame()).toContain("select at least one skill");
    expect(result).toBeNull();
    stdin.write("a");
    await tick();
    stdin.write(ENTER);
    await tick();
    expect(result).toEqual(["a", "b", "c"]);
  });

  it("shows the highlighted skill's description and badges", () => {
    const { lastFrame } = render(<SkillPickerScreen catalog={catalog} initial={[]} onDone={() => {}} />);
    expect(lastFrame()).toContain("Skill A does things.");
    expect(lastFrame()).toContain("edgar");
  });
});

describe("CredentialsScreen", () => {
  const needsBrokerage = new Set<Requirement>(["brokerage"]);

  it("shows the three broker options when a brokerage connection is needed", () => {
    const { lastFrame } = render(
      <CredentialsScreen needs={needsBrokerage} existing={{}} brokers={new Set<BrokerChoice>()} acceptDefaults={false} onDone={() => {}} onCancel={() => {}} />,
    );
    const frame = lastFrame()!;
    expect(frame).toContain("SnapTrade (any brokerage, hosted portal, one free key)");
    expect(frame).toContain("E*Trade direct (your developer key, real-time quotes, daily re-auth)");
    expect(frame).toContain("Both");
    // The terminal wraps long lines, so compare against the flattened frame.
    const flat = frame.replace(/\s+/g, " ");
    expect(flat).toContain("E*Trade direct uses your own developer key from https://developer.etrade.com and needs a browser login each trading day.");
    expect(flat).toContain("If the same E*Trade account is also linked through SnapTrade, the direct connection is used for it; the SnapTrade copy is hidden.");
    expect(flat).toContain("Choosing SnapTrade alone keeps an E*Trade key already in .env; delete the ETRADE_* lines there to turn it off.");
  });

  it("collects an E*Trade key, secret and sandbox choice and reports them with the etrade broker", async () => {
    let done: [EnvValues, Set<BrokerChoice>] | null = null;
    const { stdin } = render(
      <CredentialsScreen
        needs={needsBrokerage}
        existing={{}}
        brokers={new Set<BrokerChoice>()}
        acceptDefaults={false}
        onDone={(v, b) => (done = [v, b])}
        onCancel={() => {}}
      />,
    );
    stdin.write("2"); // E*Trade direct
    await tick();
    stdin.write("EK123");
    await tick();
    stdin.write(ENTER);
    await tick();
    stdin.write("ESSECRET456");
    await tick();
    stdin.write(ENTER);
    await tick();
    stdin.write("2"); // Sandbox
    await tick();
    expect(done).not.toBeNull();
    const [values, brokers] = done!;
    expect(values).toMatchObject({ ETRADE_CONSUMER_KEY: "EK123", ETRADE_CONSUMER_SECRET: "ESSECRET456", ETRADE_SANDBOX: "1" });
    expect([...brokers]).toEqual(["etrade"]);
  });

  it("returns to the broker picker when escape is pressed on the SnapTrade client id prompt", async () => {
    const { lastFrame, stdin } = render(
      <CredentialsScreen needs={needsBrokerage} existing={{}} brokers={new Set<BrokerChoice>()} acceptDefaults={false} onDone={() => {}} onCancel={() => {}} />,
    );
    stdin.write("1"); // SnapTrade
    await tick();
    expect(lastFrame()).toContain("SnapTrade client id");
    stdin.write(ESCAPE);
    await tick();
    expect(lastFrame()).toContain("Which brokerage connection?");
  });

  it("skips the E*Trade sandbox question with acceptDefaults and defaults it to live", async () => {
    let done: [EnvValues, Set<BrokerChoice>] | null = null;
    const { lastFrame, stdin } = render(
      <CredentialsScreen
        needs={needsBrokerage}
        existing={{}}
        brokers={new Set<BrokerChoice>()}
        acceptDefaults={true}
        onDone={(v, b) => (done = [v, b])}
        onCancel={() => {}}
      />,
    );
    stdin.write("2"); // E*Trade direct
    await tick();
    stdin.write("EK123");
    await tick();
    stdin.write(ENTER);
    await tick();
    stdin.write("ESSECRET456");
    await tick();
    stdin.write(ENTER);
    await tick();
    expect(lastFrame()).not.toContain("E*Trade environment");
    expect(done).not.toBeNull();
    const [values, brokers] = done!;
    expect(values).toMatchObject({ ETRADE_CONSUMER_KEY: "EK123", ETRADE_CONSUMER_SECRET: "ESSECRET456", ETRADE_SANDBOX: "0" });
    expect([...brokers]).toEqual(["etrade"]);
  });
});

describe("ReviewScreen", () => {
  it("lists the diff, credentials, and the link conflict options", () => {
    const root = miniRoot();
    const home = tmpDir();
    const ctx = createContext(root, opts([]), { HOME: home }, new FakeRunner());
    const pre: Preflight = { node: "20", python: { found: { command: ["python3"], version: "3.12.0", hasVenv: true, source: "PATH" }, rejected: [] }, previous: { skills: ["a", "b"], source_path: root, source_commit: null, installer_version: "1", installed_at: "" }, commit: "abc" };
    const plan = buildPlan(ctx, pre, pre.python.found!, ["a", "c"], { SNAPTRADE_CLIENT_ID: "client-id-value", SNAPTRADE_CONSUMER_KEY: "super-secret-value" });
    const { lastFrame } = render(<ReviewScreen ctx={ctx} plan={plan} onChoose={() => {}} />);
    const frame = lastFrame()!;
    expect(frame).toContain("1 new • 1 refreshed • 1 removed");
    expect(frame).toContain("+ c");
    expect(frame).toContain("− b");
    expect(frame).toContain("SNAPTRADE_CLIENT_ID, SNAPTRADE_CONSUMER_KEY");
    expect(frame).toContain("~/.claude/skills/second-opinion");
    expect(frame).toContain("EDGAR_USER_AGENT not set");
    expect(frame).toContain("1. Update");
    expect(frame).not.toContain("super-secret-value"); // never the secret itself
    expect(frame).not.toContain("client-id-value");
    const conflicted = buildPlan({ ...ctx, link: path.join(root, "skills") }, pre, pre.python.found!, ["a"], plan.values);
    const c = render(<ReviewScreen ctx={{ ...ctx, link: path.join(root, "skills") }} plan={conflicted} onChoose={() => {}} />);
    expect(c.lastFrame()).toContain("is a real");
    expect(c.lastFrame()).toContain("Install and replace the link");
    expect(c.lastFrame()).toContain("Install without linking");
  });
});

describe("UninstallScreen", () => {
  it("renders the removing state without a bare text node", () => {
    const root = miniRoot();
    const home = tmpDir();
    const ctx = createContext(root, opts(["--uninstall", "--yes"]), { HOME: home }, new FakeRunner());
    const { lastFrame } = render(<UninstallScreen ctx={ctx} onDone={() => {}} onFail={() => {}} />);
    expect(lastFrame()).toContain("Removing…");
  });
});

describe("Steps", () => {
  it("renders every status", () => {
    const { lastFrame } = render(
      <Steps
        now={5000}
        steps={[
          { id: "1", label: "Done", status: "done", detail: "ok", startedAt: 1000, endedAt: 3500 },
          { id: "2", label: "Running", status: "running", live: "pip output", startedAt: 4000 },
          { id: "3", label: "Skipped", status: "skipped", detail: "--no-link" },
          { id: "4", label: "Pending", status: "pending" },
          { id: "5", label: "Failed", status: "failed", detail: "boom" },
        ]}
      />,
    );
    const f = lastFrame()!;
    expect(f).toContain("✔ Done  ok 2.5s");
    expect(f).toContain("Running");
    expect(f).toContain("pip output");
    expect(f).toContain("• Skipped  --no-link");
    expect(f).toContain("○ Pending");
    expect(f).toContain("✖ Failed  boom");
  });
});

describe("suggestions", () => {
  it("only proposes prompts for installed skills and respects the key requirement", async () => {
    const { suggestions } = await import("../src/ui/suggestions.js");
    expect(suggestions(["valuation", "real-estate"], false).map((s) => s.prompt)).toEqual(["what is AAPL worth?", "should I rent or buy?"]);
    expect(suggestions(["connect", "portfolio-snapshot", "valuation"], false).map((s) => s.prompt)).toEqual(["what is AAPL worth?"]);
    expect(suggestions(["connect", "portfolio-snapshot", "valuation"], true).map((s) => s.prompt)).toEqual(["connect my brokerage", "how is my portfolio?"]);
    expect(suggestions(["tax-aware"], true)).toEqual([]);
  });

  it("puts a Connect E*Trade prompt first when told the token needs a fresh login", async () => {
    const { suggestions } = await import("../src/ui/suggestions.js");
    const withLogin = suggestions(["connect", "portfolio-snapshot"], true, { etradeNeedsLogin: true });
    expect(withLogin[0]!.prompt).toBe("Connect E*Trade");
    expect(withLogin[0]!.note).toBe("opens the E*Trade login; paste the 5-character code back in the chat");
    expect(withLogin.map((s) => s.prompt)).toEqual(["Connect E*Trade", "connect my brokerage", "how is my portfolio?"]);
    expect(suggestions(["connect", "portfolio-snapshot"], true, { etradeNeedsLogin: false }).map((s) => s.prompt)).toEqual(["connect my brokerage", "how is my portfolio?"]);
  });
});

describe("DoneScreen", () => {
  const environ = { HOME: "/home/u" };
  const ctx = createContext(miniRoot(), opts([]), environ, new FakeRunner());

  function summaryWith(etrade: Summary["smoke"]["etrade"], status: Summary["smoke"]["status"] = "no_keys"): Summary {
    return {
      target: ctx.target,
      link: ctx.link,
      skills: { installed: ["connect", "portfolio-snapshot"], refreshed: [], removed: [] },
      extras: {},
      mode: "copy",
      data: ctx.data,
      notes: [],
      dependencies: { venv: "/home/u/venv/bin/python", installed: true },
      smoke: { imports: "ok", dcf: "ok", status, etrade },
      warnings: [],
    };
  }

  it("suggests connecting E*Trade first and shows the etrade smoke status when the token needs a fresh login", () => {
    const { lastFrame } = render(<DoneScreen ctx={ctx} summary={summaryWith("no_login")} updated={false} />);
    const frame = lastFrame()!;
    expect(frame).toContain("Connect E*Trade");
    expect(frame).toContain("opens the E*Trade login; paste the 5-character code back in the chat");
    expect(frame).toContain("etrade no_login");
  });

  it("says nothing about E*Trade when it was not chosen", () => {
    const { lastFrame } = render(<DoneScreen ctx={ctx} summary={summaryWith("no_keys")} updated={false} />);
    const frame = lastFrame()!;
    expect(frame).not.toContain("Connect E*Trade");
    expect(frame).not.toContain("etrade no_keys");
    expect(frame).not.toContain("etrade ok");
  });
});

describe("ExtrasScreen", () => {
  const extras = loadExtras(extrasRoot());

  it("lists every extra with its blurb and cost, toggles with space, and returns the state on enter", async () => {
    let got: ExtrasState | null = null;
    const { lastFrame, stdin } = render(<ExtrasScreen extras={extras} initial={{ c: false, tips: false }} onDone={(s) => (got = s)} onCustomize={() => {}} />);
    const frame = lastFrame()!;
    expect(frame).toContain("Optional extras");
    expect(frame).toContain("Skill C extra");
    expect(frame).toContain("Does C.");
    expect(frame).toContain("Adds a step.");
    expect(frame).toContain("Tips");
    expect(frame).toContain("Shows tips.");
    expect(frame).toContain("customize every skill");
    stdin.write(" ");
    await tick();
    stdin.write(DOWN);
    await tick();
    stdin.write(ENTER);
    await tick();
    expect(got).toEqual({ c: true, tips: false });
  });

  it("c opens the full picker and escape goes back", async () => {
    let customized: ExtrasState | null = null;
    let cancelled = 0;
    const { stdin } = render(<ExtrasScreen extras={extras} initial={{ c: false, tips: false }} onDone={() => {}} onCustomize={(s) => (customized = s)} onCancel={() => cancelled++} />);
    stdin.write(" ");
    await tick();
    stdin.write("c");
    await tick();
    stdin.write(ESCAPE);
    await tick();
    expect(customized).toEqual({ c: true, tips: false }); // the edits so far carry into the full picker
    expect(cancelled).toBe(1);
  });
});

describe("ModeScreen", () => {
  it("offers Change extras beside Update and Change skills", async () => {
    const chosen: string[] = [];
    const { lastFrame, stdin } = render(<ModeScreen previous={{ skills: ["a"], source_path: "", source_commit: null, installer_version: "", installed_at: "" }} onSelect={(m) => chosen.push(m)} />);
    expect(lastFrame()).toContain("Change extras");
    stdin.write("3");
    await tick();
    expect(chosen).toEqual(["extras"]);
  });
});

describe("ReviewScreen extras", () => {
  it("names the extras that are on, or says they are all off", () => {
    const root = extrasRoot();
    const ctx = createContext(root, opts([]), { HOME: tmpDir() }, new FakeRunner());
    const pre: Preflight = { node: "20", python: { found: { command: ["python3"], version: "3.12.0", hasVenv: true, source: "PATH" }, rejected: [] }, previous: null, commit: null };
    const on = buildPlan(ctx, pre, pre.python.found!, ["a", "c"], {}, undefined, { tips: false });
    expect(render(<ReviewScreen ctx={ctx} plan={on} onChoose={() => {}} />).lastFrame()).toMatch(/extras\s+on: Skill C extra/);
    const off = buildPlan(ctx, pre, pre.python.found!, ["a"], {}, undefined, { tips: false });
    expect(render(<ReviewScreen ctx={ctx} plan={off} onChoose={() => {}} />).lastFrame()).toMatch(/extras\s+all off/);
  });
});

describe("App wizard", () => {
  it("a fresh install picks core skills, then offers the extras off, then asks for credentials", async () => {
    const root = extrasRoot();
    const home = tmpDir();
    const ctx = createContext(root, opts([]), { HOME: home, SECOND_OPINION_DATA: path.join(home, "data") }, new FakeRunner());
    const { lastFrame, stdin } = render(<App ctx={ctx} commit={null} onExit={() => {}} />);
    for (let i = 0; i < 50 && !lastFrame()!.includes("Choose the core skills"); i++) await tick();
    expect(lastFrame()).toContain("Choose the core skills");
    expect(lastFrame()).not.toContain("Skill C extra");
    stdin.write(ENTER);
    await tick();
    expect(lastFrame()).toContain("Optional extras");
    stdin.write(" ");
    await tick();
    stdin.write(ENTER);
    await tick();
    expect(lastFrame()).toContain("Skills • 3 of 3 selected");
    expect(lastFrame()).toContain("Extras • Skill C extra");
  });

  it("a catalog without extras skips the extras step", async () => {
    const root = miniRoot();
    const home = tmpDir();
    const ctx = createContext(root, opts([]), { HOME: home, SECOND_OPINION_DATA: path.join(home, "data") }, new FakeRunner());
    const { lastFrame, stdin } = render(<App ctx={ctx} commit={null} onExit={() => {}} />);
    for (let i = 0; i < 50 && !lastFrame()!.includes("Choose the core skills"); i++) await tick();
    stdin.write(ENTER);
    await tick();
    expect(lastFrame()).not.toContain("Optional extras");
    expect(lastFrame()).toContain("Skills • 3 of 3 selected");
  });

  it("Change extras on an existing install starts from what is installed and keeps the other skills", async () => {
    const root = extrasRoot();
    const home = tmpDir();
    const ctx = createContext(root, opts([]), { HOME: home, SECOND_OPINION_DATA: path.join(home, "data") }, new FakeRunner());
    fs.mkdirSync(ctx.target, { recursive: true });
    fs.writeFileSync(path.join(ctx.target, "installed.json"), JSON.stringify({ skills: ["a", "b", "c"], source_path: "", source_commit: null, installer_version: "2.0.0", installed_at: "" }));
    const { lastFrame, stdin } = render(<App ctx={ctx} commit={null} onExit={() => {}} />);
    for (let i = 0; i < 50 && !lastFrame()!.includes("Change extras"); i++) await tick();
    stdin.write("3");
    await tick();
    const frame = lastFrame()!;
    expect(frame).toContain("Optional extras");
    expect(frame).toContain("1 of 2 on"); // legacy record: skill extra installed; non-skill extras are opt-in, so off
    stdin.write(" "); // turn Skill C extra off
    await tick();
    stdin.write(ENTER);
    await tick();
    expect(lastFrame()).toContain("Extras • all off");
    expect(lastFrame()).toContain("Skills • 2 of 3 selected");
  });

  it("a /plugin install opens on the extras, never offers the skill picker, and says only the data dir is written", async () => {
    const home = tmpDir();
    const root = extrasRoot(path.join(home, ".claude", "plugins", "cache", "second-opinion", "second-opinion", "1.0.0"));
    const ctx = createContext(root, opts([]), { HOME: home }, new FakeRunner());
    expect(ctx.configure).toBe(true);
    const { lastFrame } = render(<App ctx={ctx} commit={null} onExit={() => {}} />);
    for (let i = 0; i < 50 && !lastFrame()!.includes("Optional extras"); i++) await tick();
    const frame = lastFrame()!;
    expect(frame).toContain("Claude Code manages the plugin files");
    expect(frame).toContain("0 of 2 on");
    expect(frame).not.toContain("customize every skill");
  });
});
