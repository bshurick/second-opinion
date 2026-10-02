import { Box, Text, useStdout } from "ink";
import { color, glyph } from "../theme.js";
import { KeyValue } from "./KeyValue.js";

interface Props {
  version: string;
  commit: string | null;
  target: string;
  data: string;
  link: string;
  /** Configure only: Claude Code manages the plugin files, so only the data dir is written. */
  configure?: boolean;
}

/** The welcome box: who we are, and the only paths this program writes. */
export function Header({ version, commit, target, data, link, configure = false }: Props) {
  // Static items are not bounded by the terminal width, so bound this one explicitly.
  const { stdout } = useStdout();
  const width = Math.max(40, Math.min(stdout?.columns ?? 80, 120));
  return (
    <Box flexDirection="column" borderStyle="round" borderColor={color.accent} paddingX={1} marginBottom={1} width={width}>
      <Box>
        <Text color={color.accent} bold>
          {glyph.star} Second Opinion
        </Text>
        <Text color={color.dim}>
          {"  "}for Claude Code {glyph.dot} installer {version}
          {commit ? ` ${glyph.dot} ${commit.slice(0, 7)}` : ""}
        </Text>
      </Box>
      <Box flexDirection="column" marginTop={1}>
        <Text color={color.dim}>Finance skills that work with your brokerage accounts, SEC filings and market data from local Python scripts.</Text>
        {configure ? (
          <>
            <Text color={color.dim}>Claude Code manages the plugin files at {target}.</Text>
            <Text color={color.dim}>This installer writes only your settings, extras and Python environment:</Text>
            <Box flexDirection="column" marginLeft={2}>
              <KeyValue k="data" width={9}>
                <Text>{data}</Text>
              </KeyValue>
            </Box>
          </>
        ) : (
          <>
            <Text color={color.dim}>This installer writes to exactly three places:</Text>
            <Box flexDirection="column" marginLeft={2}>
              <KeyValue k="plugin" width={9}>
                <Text>{target}</Text>
              </KeyValue>
              <KeyValue k="data" width={9}>
                <Text>{data}</Text>
              </KeyValue>
              <KeyValue k="link" width={9}>
                <Text>{link}</Text>
              </KeyValue>
            </Box>
          </>
        )}
      </Box>
    </Box>
  );
}
