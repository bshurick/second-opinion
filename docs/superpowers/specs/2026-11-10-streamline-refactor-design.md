# Streamlining refactor: plan

Date: 2026-11-10. Status: approved; phases 1 and 2 implemented. Open questions answered 2026-11-10 (see the end).

## Why

The plugin grew one feature at a time, and each feature brought its own settings file, its own trigger words and its own session-start notice. The result works, but the person has to steer it:

- **Install has two routes, three front doors and a 23-row skill picker.** A new user meets the marketplace commands, a Node installer, then `setup`, `onboarding` and `connect` as separate conversations.
- **Settings live in six places** and nothing shows them together (table below).
- **Depth is chosen per request by phrasing.** "What's X worth" gives the quick DCF; "deep dive on X" gives the researched one. Light and deep results then mix downstream: light picks sit in the pick store beside deep ones, and core-satellite needs an `include_light` switch to cope.
- **Core/satellite is a second portfolio manager.** It has its own buckets, ceiling, step-up plan, deposit routing and rebalancer, beside the rebalancing skill's targets, bands, deposit routing and rebalancer. "Where does this deposit go" and "rebalance" each have two owners with different answers.
- **Common moments need the right phrase.** Adding money, checking in and rebalancing each depend on the person knowing which skill's vocabulary to use, and on reading four separate session-start notices.

### Where settings live today

| Setting | File | Set by |
|---|---|---|
| Keys, EDGAR contact, cash/margin per account (`BROKER_ACCOUNT_TYPES`) | `.env` | installer, by hand |
| Installed skills, extras on/off | `installed.json` | installer |
| Approach, horizon, goals, `account_roles` (trading/retirement/savings) | `profile.json` | onboarding |
| Ceiling, weighting, `include_light`, short-term-gain policy, employer symbol, step-up plan | `core-satellite.json` | core-satellite |
| Target weights and classes | `targets.json` | rebalancing `--save` |
| Taxable vs tax-advantaged per account | nowhere (guessed each run, corrected by flags) | rebalancing |

An account is classified three times (cash/margin, trading/retirement, taxable/tax-advantaged) in three places.

## Goals

1. Install is one command block and one conversation.
2. Every setting is in one file, grouped under plain names, and one command shows them all.
3. Research depth is a saved setting. With depth set to deep, no skill produces or consumes a lightweight valuation or stock pick.
4. Stock picks are a sub-portfolio (a sleeve) inside one portfolio plan. The sleeve has its own rebalancing rules; the global plan treats it as one line.
5. Adding money, checking in, rebalancing and opening a pick each work from an ordinary sentence, with no skill names or flags to know.

## Non-goals

- New deep modes. Candidates are listed in section 2 and not built.
- Changes to the order protocol, the hard gate, or the no-advice rules.
- Changes to the math inside the valuation, rebalancing or sleeve scripts beyond what merging them needs.
- Dropping the guided (checkout) install. It stays for development and scripted installs.

## Anti-goals

- A deep-mode install that quietly spends a session's usage on a casual question.
- A settings change made without the person's own words (the existing `decide` rule stays).
- Losing a saved decision, pick, plan or target during migration.

---

## 1. Install and first run

### What changes

**One documented route.** The README leads with the marketplace install only. The guided installer moves to `docs/install.md` under "From a checkout".

**One first-run conversation.** `setup`, `onboarding` and the first-run half of `connect` become one flow, started by "get started with Second Opinion". It walks the steps below, skips any already done, and can stop and resume at any step. `connect` remains as its own skill for relinking and daily E*Trade logins.

| Step | What the person does | Skippable |
|---|---|---|
| 1. Check | Nothing. Python, virtualenv and smoke test run and report. | no |
| 2. Keys | Runs one command in their own terminal. Keys never enter chat. | yes (research-only use) |
| 3. Connect | Signs in at SnapTrade's portal or E*Trade. | yes |
| 4. Accounts | Confirms a table of accounts with a proposed role each. | with step 3 |
| 5. Depth | Picks Standard or Deep, shown with what each costs (section 2). | defaults to Standard |
| 6. Portfolio plan | Confirms the proposed plan (section 3): employer stock, picks sleeve, cash reserve. | yes |
| 7. About you | The current six profile questions, cut to the three that change behaviour. | yes |

Step 4 replaces three classifications with one. Each account gets one role, and the scripts derive the rest:

| Role | Taxable | Holds picks | Core sold to fund picks |
|---|---|---|---|
| trading | yes | yes | yes |
| retirement | no | no | no |
| savings | yes | no | no |

Margin stays a separate yes/no on the account, since it is a fact about the account and not a role.

Step 7 keeps `approach`, `horizon` and `pre_trade_check`, the three fields that steer which analysis leads. `risk_appetite`, `experience`, `goals`, `trades_actively` and `uses_options` are read by nothing but the context line; they stay as optional fields the person can set later and are no longer asked. (My call; see open questions.)

**No skill picker by default.** The marketplace route already installs everything. The guided installer keeps `--skills` and `--without` as flags and drops the interactive picker screen. The reason given for the picker (a shorter skill list per session) is better served by having fewer skills (section 4).

**Key entry without Node.** Marketplace users need Node only to type keys. A small Python key-entry script (`configure.py keys`, run in a terminal, hidden input, writes `.env` at mode 0600) removes that requirement. Python is already required. The Node installer keeps doing this for checkout installs. (My call.)

### Updating

Today the marketplace route has no update instructions, and the version in `plugin.json` and `marketplace.json` has stayed at `1.0.0` with no tags. Leading with the marketplace route makes this a requirement.

- **A version that moves.** Every release bumps the version in both files and adds a CHANGELOG entry and a git tag. A CI check fails when skills, scripts or hooks changed since the last tag and the version did not. Verify first how Claude Code detects a plugin update (version field or commit) and whether third-party marketplaces update automatically; the docs wording depends on the answer.
- **One documented update command** for each route, in the README beside the install block: the marketplace update commands, and `git pull && node install.js` for a checkout.
- **What an update does on the next session.** The session-start hook already rebuilds the virtualenv when `requirements.txt` changes. It also runs the settings migration (below) and compares the running version with the one recorded in the data directory. When they differ it prints one inbox line, "Updated to X.Y.Z", with any change that needs the person (a renamed command, a new setting at its default), then records the new version.
- **Settings carry a schema number.** `settings.json` has `schema: N`. Each release that changes its shape ships a step from N to N+1, so an install that skips several versions still migrates in order. A settings file newer than the plugin (a downgrade) is read-only and says so.
- **"Is there an update?"** "Check my setup" reports the installed version, the latest released version when it can be read, and the command to update. Nothing updates itself.

### One settings file

`settings.json` in the data directory replaces `installed.json`'s extras, `core-satellite.json`'s decisions, `targets.json` and `profile.json`'s `account_roles`. Keys stay in `.env`. The profile stays in `profile.json`, since it describes the person and carries provenance per field.

```
settings.json
  depth            "standard" | "deep"
  deep             { ask_above: 3 }                         section 2
  accounts         { <id>: { role, margin } }
  plan             { targets, sleeves, cash_reserve, bands } section 3
  taxes            { short_term_rate, long_term_rate, short_term_gain_policy }
  guardrails       { pre_buy_check: on|off }                 today's trade-journal extra
  replies          { follow_ups: on|off, pages: on|off }
  lessons          on|off                                    today's financial-education extra
  history          [ { date, key, value } ]                  today's `decisions` list
```

- **One reader.** `lib/second_opinion/settings.py` is the only code that reads or writes the file. Hooks call it (`settings.py get depth`) instead of the current regex over `installed.json` in `hooks/common.sh`.
- **One command to see them.** "Show my settings" prints every group in plain language with the date each was last changed, and what each default means when unset.
- **One command to change one.** `settings.py set KEY VALUE`, with the existing rule that it runs only after the person answers in their own words.
- **`pages` is new.** The README tells people to "ask for the answer in chat" if they do not want a page published. That is a standing preference and belongs in settings.
- **`installed.json` shrinks** to what the installer owns: installed skills, source path, version.

### Migration

A one-time, idempotent migration runs from the session-start hook, as the data-directory move does today. It reads the old files, writes `settings.json`, and renames each old file to `<name>.migrated` rather than deleting it. `ceiling: 1.0` (no effective ceiling) migrates to a sleeve with no target; see section 3.

---

## 2. Depth as a setting

### The setting

| | Standard | Deep |
|---|---|---|
| Valuation | Quick: scripted DCF, comps, DDM, Graham/Buffett | Researched scenarios by segment, sourced ledger |
| Stock picking | Screen and funnel, light picks | Deep picker, downside gate, deep picks only |
| Reviews (portfolio, property, trades, tax plans) | Scripted answer; deep run on request | Deep run is the default answer |
| Cost | Seconds, little usage | Minutes, 5 to 40 subagents per run |

Standard keeps today's behaviour, including "deep dive on X" as a per-request upgrade. Deep changes the default and closes the light paths.

### The rule in deep mode

**A valuation or a pick is deep, or it is not given.** Concretely:

| Request | Today | Deep mode |
|---|---|---|
| "What's X worth?" | Quick DCF, offers deep | Answer from a saved deep valuation if one is current; else run deep |
| "Find me stocks" | Screen, funnel, `dcf.py` price check | Deep picker |
| "Run a value screen" | Screen page | Screen page, labelled as candidates and not picks; no fair values, no save offer |
| Save a pick | `save-light` or `save-deep` | `save-deep` only; `save-light` exits 2 |
| Light picks already saved | Re-checked on light rules | Listed as "needs deep valuation"; no light re-check, no tilt, no new money |
| Picks sleeve, valuation weighting | Deep picks, or light with `include_light` | Deep picks only; `include_light` is removed |
| New pick with no deep valuation | Opens, flagged | Runs the deep valuation first, then opens |
| Pick re-check says rerun is due | Offers the rerun | Runs it |
| "How diversified am I?" | Holdings answer, offers deep review | Holdings answer, plus the saved deep review's re-check; a new deep review when none is saved or a rerun is due |
| Several tickers compared | One quick row each | A deep valuation each, subject to the ask threshold below |

Three things keep deep mode from being wasteful, since "always deep" must not mean "always rerun":

1. **Reuse while current.** A saved deep result answers the question until its own re-check says a rerun is due (the existing `rerun_deep` and `rerun_due` rules). The reply states the valuation's date.
2. **Say the size, ask above a threshold.** One deep run starts without asking, with one line stating its size. A request that would start more than `deep.ask_above` deep valuations (default 3) states the total and asks once. (My call on the default.)
3. **Mechanical lookups are not valuations.** A quote, a ratio, a filing section, an option chain or a screen's candidate list is the same in both modes. The rule covers outputs that state a fair value, an expected return or a pick.

### How it is enforced

Prose in 27 skill files will drift. The setting is enforced in three layers:

1. **Scripts.** `settings.depth()` in the shared library. `picks.py save-light` and the light branch of `check` refuse in deep mode. The sleeve engine ignores light picks. `valuation/render.py` (the quick page) stamps "Standard depth" on its output, so a quick page can never pass as a deep one.
2. **One session rule.** A `hooks/depth-deep.md` file loaded at session start when depth is deep, the way `portfolio-check.md` is loaded today. It holds the table above. Skills refer to "the session's depth rule" and keep no private copy of it.
3. **Tests.** `tests/test_skills_structure.py` gains a check that every skill with a deep path names the depth rule and that no skill's steps offer `save-light` or a quick fair value without the standard-depth condition.

Each skill's "Two modes" table is replaced by one line pointing to the depth rule, plus the trigger words that still upgrade a single request in standard mode.

### Other deep modes worth building later

Noted only. In rough order of how much they would change answers:

| Candidate | Skill | Question it answers |
|---|---|---|
| Employer stock plan | tax-aware + portfolio plan | What the vesting schedule, concentration and tax cost imply across sell-on-vest, hold and staged plans |
| Holding thesis review | valuation / stock-screener | For a stock held without a saved valuation: what the price assumes today, and whether the reason for owning it still holds |
| Fund due diligence | portfolio-analysis | What a core fund actually holds, costs and overlaps with, against named alternatives |
| Retirement plan review | retirement | Which assumptions the success odds rest on (Social Security, healthcare, taxes, return path), each sourced |
| Stress scenarios | risk-analysis | Scenarios built from this portfolio's own bets, in place of replaying four historical crashes |
| Dividend safety | dividend-income | Each payer's coverage, debt and payout history read from filings |
| Earnings preview and review | fundamental-research | What a quarter has to show for a saved thesis, then what it showed |
| Target allocation design | rebalancing | An investment policy drafted from goals, horizon and accounts, with the evidence behind each weight |
| Bond and credit review | fixed-income | What a bond fund's credit and rate exposure rest on |
| Refinance and payoff review | debt-tracker + real-estate | Current lender terms researched against the recorded debts |
| Macro regime brief | market-analysis | What positioning, flows and rates jointly imply, with dated sources |
| Alert triage | watchlist | Why a watched name moved, checked against its saved thesis |
| Event setup | options | An earnings or event position: implied move against researched history |
| Spending audit | spending | Recurring charges researched for cheaper equivalents and forgotten renewals |

In deep mode, a skill with no deep path behaves as it does today. The settings page lists which skills have one, so "deep" never implies more than exists.

---

## 3. Picks as a sleeve of one portfolio plan

### The problem with today's shape

`core-satellite` models the whole account set as core, satellite, employer and cash, then manages the satellite with a ceiling, a growth plan and its own rebalancer. `rebalancing` separately holds targets and bands over the same accounts and treats unmapped stocks as frozen. Neither knows the other's rules. The ceiling, `grow`, `plan-step`, `add`, `deposit` and `similar_to_last` all answer one question (how big the picks should be and how money gets there) that a target weight answers directly.

### The new shape

One portfolio plan in `settings.json`. A target key is a symbol, a class, `CASH`, or a **sleeve**. A sleeve is a named sub-portfolio with a membership rule and its own rules for what happens inside it. The global rebalancer sees a sleeve as one line.

```
plan
  targets        { US: 0.55, INTL: 0.15, BONDS: 0.10, PICKS: 0.20 }   optional
  cash_reserve   5000
  bands          { absolute: 0.05, relative: 0.25 }
  sleeves
    PICKS     { members: "picks",        weighting: "valuation", max_position: 0.05,
                band: { relative: 0.25, floor: 250 }, rebalance: "on_request",
                accounts: "trading" }
    EMPLOYER  { members: ["AMZN"],       policy: "sell_on_arrival" }
```

| Question | Global plan | Inside the picks sleeve |
|---|---|---|
| What is rebalanced | Classes, funds and the sleeve as one line | The individual picks |
| Target | The saved weights | The sleeve's weighting: equal, market cap, valuation tilt or current size |
| When it trades | Band breach or the person's calendar | Only on request |
| Bands | 5/25 | 25% of target or $250, whichever is larger |
| Where sells land | Tax-advantaged accounts first | Same account only; proceeds buy other picks |
| What holds a position still | Nothing | Re-check due, deep valuation needed, no market cap |
| Tax | Highest-cost lots, short-term policy | The same |

What this replaces:

| Today | Becomes |
|---|---|
| `ceiling` | The sleeve's target weight. No target means the sleeve is unmanaged in size, which is what a saved `ceiling: 1.0` means today |
| `grow`, `add`, `plan-step`, step-up plan, `increases` history | A contribution routed by the plan. A sleeve below its target takes new money first. A staged increase is a target with a date (`glide: {to: 0.20, by: 2027-06-30}`) |
| `deposit` proposal and `--satellite` split | The same contribution routing; the split is what the targets imply, shown before any trade |
| `new-pick` | Opening a member of the sleeve, sized by the sleeve's rule |
| `core-satellite rebalance` | "Rebalance my picks": the sleeve's inside rules |
| `rebalancing` | "Rebalance": the global plan, sleeve as one line |
| Employer bucket and `employer_symbol` | A sleeve with its own policy. A sell-on-arrival policy makes a vest an expected event the check-in can name (section 4) |
| Frozen holdings | Still frozen, and now listed as "not in the plan" with one line each |
| `include_light` | Removed (section 2) |

**No targets saved** is a supported state, and the common one. Then contributions buy the existing funds pro rata, the picks sleeve takes money only when the person says so, and "rebalance" reports that no targets exist and offers to derive them from today's weights.

### Code

- `skills/rebalancing` becomes the single home (renamed `portfolio-plan`; my call). `rebalance.py` stays the global engine and gains sleeve-as-one-line support.
- `core-satellite/scripts/sleeves.py` and `weights.py` move in as the picks sleeve's inside engine. Their pick-hold rules, trim bands, same-account routing and lot logic are kept as they are; the ceiling, grow and plan-step code paths are deleted.
- `run.py`'s classification (fund-shaped names, sweep de-duplication, employer candidate from vest deposits) moves to the shared library, since the snapshot and the plan both need it and each has its own copy of parts of it today.
- One entry point: `plan.py status | contribute AMOUNT | withdraw AMOUNT | rebalance [--sleeve NAME] | open SYMBOL`.
- The `core-satellite` skill is removed. Its trigger phrases ("add $5k to my picks", "my ETF vs stock mix") move to the merged skill's description.
- `references/research.md` moves with the sleeve engine; the tracking-error and effective-count figures stay in `status`.

The two existing rebalancers have different, well-tested trade logic. The merge puts them behind one entry point and one settings model; it does not rewrite either into the other.

---

## 4. Less steering for common moments

### One check-in in place of four notices

Session start today prints the full watchlist, the picks due, a plan-step notice, a profile line, and three standing rules. The watchlist block alone is about 25 lines.

Replace the four summaries with one **inbox** of at most six lines, each a thing that needs attention and the sentence that handles it:

```
Second Opinion, 3 things:
- Cash: $4,210 arrived in Individual since Nov 5.        "put the new cash to work"
- Picks: 6 of 16 due for a re-check (4 awaiting 10-Qs).  "re-check my picks"
- Watchlist: PRDO is 15.9% below where you added it.     "what happened to PRDO"
```

Nothing to report prints nothing. The full watchlist table moves behind "show my watchlist".

"Check in" (or "how's my portfolio") then runs one sequence: E*Trade login if needed, the brief, drift against the plan, new cash, picks due, alerts fired. Each part is one section of one reply. Today that takes four requests to four skills.

### Money arriving is detected, not announced

The snapshot already stores the last read. Comparing cash and employer-stock units between reads identifies a deposit, a dividend build-up or a vest without being told. The inbox names it, and "put it to work" routes it by the plan and returns the trade list.

| The person says | What runs |
|---|---|
| "I added $5k" / "put the new cash to work" | `plan.py contribute`, routed by targets, sleeve included |
| "Add $5k to my picks" | `plan.py contribute 5000 --sleeve PICKS` |
| "My RSUs vested" | The employer sleeve's policy: the sale if sell-on-arrival, then the proceeds as a contribution |
| "Rebalance" | Global plan |
| "Rebalance my picks" | Sleeve rules |
| "I want to buy X" | Deep valuation if none is current (deep mode), then `plan.py open X`, then the order protocol |
| "I need $10k out" | `plan.py withdraw`, overweights and tax-advantaged first |

### One chain from plan to orders

A plan today ends with "to place these orders, say so", then hands off between skills. The chain plan → pre-buy check → preview → one `confirm` should be a single continuous flow that a plan's trade list enters directly, with the freshness read, the pick re-checks and the E*Trade login done at the start of the chain and not discovered midway. The gate and the per-block confirmation are unchanged.

### Standing answers in place of repeated questions

`DECISION_NEEDED` interrupts a plan mid-run for the ceiling, the employer symbol and the short-term-gain policy. Those are asked once in first-run step 6 and stored. A plan that meets an unset one uses the conservative default, says so in one line, and continues. Whole-share-only accounts are recorded per account from the first rejected fractional preview, so `--whole-shares` is never needed again.

### Fewer skills, clearer owners

27 skill descriptions load into every session, and several questions have two owners.

| Change | Why |
|---|---|
| `core-satellite` into `portfolio-plan` | Section 3 |
| `setup` + `onboarding` into one `get-started` | Section 1 |
| Orders owned by one skill | The scripts live in `trading` and the protocol in `portfolio-analysis`; every plan hands off across both |
| `portfolio-snapshot` into `portfolio-analysis` | "How is my portfolio" and "how diversified am I" are one conversation; the brief becomes its first section |
| `debt-tracker` into `personal-finance` | Recording debts and planning their payoff are split across two skills today |

That is 27 skills down to 22 or 23, with no capability removed. The last two merges are optional and can be dropped without affecting the rest. (My call.)

---

## Order of work

Each phase ships on its own and leaves the plugin working.

| Phase | Contents | Depends on |
|---|---|---|
| 1. Settings | `settings.json`, the shared reader, migration, "show my settings", hooks read it | none |
| 2. Depth | The setting, script enforcement, the session rule, skill text, tests | 1 |
| 3. Portfolio plan | Sleeves in the plan, merged entry point, `core-satellite` removed, migration of ceiling and targets | 1 |
| 4. Check-in | Inbox hook, cash and vest detection, the check-in sequence, plan-to-orders chain | 3 |
| 5. First run | Merged `get-started` flow, account roles table, Python key entry, README and install docs | 1, 2, 3 |
| 6. Skill merges | Orders owner, the optional merges | 3 |

First run comes late on purpose: it asks about depth and the plan, so those have to exist first.

## Risks

| Risk | Handling |
|---|---|
| Deep mode spends heavily on casual questions | Reuse while current, the ask threshold, a stated size before every run, and first-run step 5 showing the cost before the choice |
| Migration loses a decision | Old files renamed, never deleted; migration tested against fixtures of every current file shape, including `ceiling: 1.0` and `plan: null` |
| The sleeve merge changes trades | Golden tests: today's `run.py` outputs on the sample household must equal the merged engine's for add, new pick and rebalance |
| Marketplace users are mid-flight | Old trigger phrases keep working through the merged skills' descriptions for one release; CHANGELOG names every renamed command |
| A single session rule file is ignored by the model | Script-level refusals are the backstop; the rule only routes |

## Open questions

These are the calls in this document that are mine and change what gets built.

1. **Standard as the default depth.** Deep by default would suit how the plugin is used by its author, but a new user's first "what's X worth" would start a dozen subagents.
2. **Deep mode running without asking** for a single company, and asking above three. The alternative is to always ask.
3. **Step-up plans become a target with a date.** The cadence, pause and resume commands go away. If the staged plan is used as a discipline device, it should stay as a sleeve feature.
4. **Profile cut to three questions.** The other fields are unused by any script.
5. **Renaming `rebalancing` to `portfolio-plan`**, and the two optional merges in section 4.
6. **Python key entry** alongside the Node installer, which means two key-entry paths to maintain.

### Answers (2026-11-10)

1. Standard is the default depth. 2. Deep runs one valuation without asking and asks above three. 3. Step-up plans become a target with a date (no step-up plan was saved). 4. The profile is cut to three questions; the other fields stay optional. 5. `rebalancing` is renamed `portfolio-plan`, and both optional merges in section 4 are made. 6. Python key entry is added alongside the Node installer.
