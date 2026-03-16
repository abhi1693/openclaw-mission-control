export type AgentEmojiOption = {
  value: string;
  label: string;
  glyph: string;
};

export const AGENT_EMOJI_OPTIONS: readonly AgentEmojiOption[] = [
  { value: ":gear:", label: "Gear", glyph: "⚙️" },
  { value: ":alarm_clock:", label: "Alarm Clock", glyph: "⏰" },
  { value: ":art:", label: "Art", glyph: "🎨" },
  { value: ":brain:", label: "Brain", glyph: "🧠" },
  { value: ":wrench:", label: "Builder", glyph: "🔧" },
  { value: ":dart:", label: "Bullseye", glyph: "🎯" },
  { value: ":computer:", label: "Computer", glyph: "💻" },
  { value: ":chart_with_upwards_trend:", label: "Growth", glyph: "📈" },
  { value: ":bulb:", label: "Idea", glyph: "💡" },
  { value: ":zap:", label: "Lightning", glyph: "⚡" },
  { value: ":lock:", label: "Lock", glyph: "🔒" },
  { value: ":mailbox:", label: "Mailbox", glyph: "📬" },
  { value: ":megaphone:", label: "Megaphone", glyph: "📣" },
  { value: ":memo:", label: "Notes", glyph: "📝" },
  { value: ":owl:", label: "Owl", glyph: "🦉" },
  { value: ":robot:", label: "Robot", glyph: "🤖" },
  { value: ":rocket:", label: "Rocket", glyph: "🚀" },
  { value: ":mag:", label: "Search", glyph: "🔍" },
  { value: ":shield:", label: "Shield", glyph: "🛡️" },
  { value: ":sparkles:", label: "Sparkles", glyph: "✨" },
];

export const AGENT_EMOJI_GLYPHS: Record<string, string> = Object.fromEntries(
  AGENT_EMOJI_OPTIONS.map(({ value, glyph }) => [value, glyph]),
);
