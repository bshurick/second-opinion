import { Text } from "ink";
import { useEffect, useState } from "react";
import { color, SPINNER_FRAMES } from "../theme.js";

export function Spinner({ tint = color.accent }: { tint?: string }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI((n) => (n + 1) % SPINNER_FRAMES.length), 80);
    return () => clearInterval(t);
  }, []);
  return <Text color={tint}>{SPINNER_FRAMES[i]}</Text>;
}
