# Connecting brokerages

Two ways to connect. SnapTrade covers most US and Canadian brokerages through one free key; E*Trade can also be connected directly with your own developer key. You can use both: if the same E*Trade account is connected both ways, the direct connection is used.

| | SnapTrade | E*Trade direct |
|---|---|---|
| Brokerages covered | Every brokerage SnapTrade supports | E*Trade only |
| Quotes | Delayed (Yahoo) | Real-time |
| Session lifetime | Connection persists | Re-authorize daily |
| Orders | Through SnapTrade, whole shares | Through E*Trade's preview-then-place flow, fractional allowed |

## Connect through SnapTrade

1. Get a free Personal API key: sign in at https://dashboard.snaptrade.com, enable 2FA, and copy the client id and consumer key from https://dashboard.snaptrade.com/api-key. Enter both when the installer asks how brokerages connect, or set `SNAPTRADE_CLIENT_ID` and `SNAPTRADE_CONSUMER_KEY` in the data directory's `.env`.
2. In Claude, say "Connect my brokerage." Claude opens SnapTrade's connection portal in your browser. Pick your brokerage and sign in there; your password goes to SnapTrade's portal, never to Claude or this plugin. To go straight to one brokerage, name it: "Connect Fidelity."
3. Say "which accounts are connected?" to confirm. Repeat step 2 for another brokerage; say "disconnect Fidelity" to remove one (Claude Code asks you to approve the disconnect command).

Connections persist across sessions. If a brokerage later needs re-authorization, the connect skill's status report says so and Claude offers to reconnect.

- **Dry run first.** Say "connect the sandbox brokerage" to try SnapTrade's simulated, read-only `SANDBOX` account. It checks that your key, the connection flow, accounts, positions, and quotes work end to end.
- **Which brokerages.** Ask "which brokerages can I connect?" for the current list with trade and read support.
- **Read or trade.** Connections ask for trade permission by default. Say "connect Fidelity read-only" for an account you only want to view; a read-only connection can never place orders. Permission is fixed when the connection is made; to change it, ask Claude to reconnect with the other permission. What you grant on the brokerage's own login screen must match, or the connection ends up read-only.
- **Margin accounts.** SnapTrade does not report whether an account is cash or margin, so the plugin treats every SnapTrade account as cash. Declare margin accounts with `BROKER_ACCOUNT_TYPES` (see [Configuration](configuration.md)) so order previews and unsettled-cash warnings are right.
- **One user per key.** A Personal API key resolves to a single SnapTrade user. The plugin registers one the first time it needs to. Any other app using the same key sees the same connections.

## Connect E*Trade directly

1. Apply for a key at https://developer.etrade.com (it is tied to your E*Trade login). Enter it when the installer asks how brokerages connect, or set `ETRADE_CONSUMER_KEY` and `ETRADE_CONSUMER_SECRET` in `.env`.
2. In Claude, say "Connect E*Trade." Claude shows an authorize link. Sign in on E*Trade's site, read the five-character code it displays, and paste the code in the chat. The link carries your consumer key because E*Trade's flow requires it in the URL; the consumer secret never leaves `.env`.
3. That lasts for the day. E*Trade tokens expire at midnight Eastern, so the next day's first E*Trade question starts with the same link-and-code step.

Set `ETRADE_SANDBOX=1` to try the whole flow against E*Trade's sandbox (fake accounts, fake fills) first. E*Trade accounts report cash or margin themselves.

## SnapTrade's MCP server

SnapTrade also offers a hosted, read-only [MCP server](https://docs.snaptrade.com/docs/mcp-server) that you add under Settings, Connectors in Claude and sign into with OAuth. If all you want is balances and positions in chat, it is simpler and needs no key. It does no analysis and cannot place orders; this plugin uses the REST API with a Personal API key for that reason.
