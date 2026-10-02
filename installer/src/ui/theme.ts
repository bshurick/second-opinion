/** One place for colors and glyphs so every screen reads as the same product. */
export const color = {
  accent: "#D97757",
  ok: "green",
  warn: "yellow",
  err: "red",
  dim: "gray",
  info: "cyan",
  key: "yellow",
  edgar: "blue",
} as const;

export const glyph = {
  check: "✔",
  cross: "✖",
  warn: "⚠",
  pointer: "❯",
  on: "◉",
  off: "○",
  dot: "•",
  arrow: "→",
  star: "✻",
} as const;

export const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
