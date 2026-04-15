export type Temperature = "quente" | "morno" | "frio";

const FORTY_EIGHT_HOURS = 48 * 60 * 60 * 1000;
const SEVEN_DAYS = 7 * 24 * 60 * 60 * 1000;

export function getTemperature(lastMsgAt: string | null): Temperature {
  if (!lastMsgAt) return "frio";
  const diff = Date.now() - new Date(lastMsgAt).getTime();
  if (diff < FORTY_EIGHT_HOURS) return "quente";
  if (diff < SEVEN_DAYS) return "morno";
  return "frio";
}

export const TEMPERATURE_CONFIG = {
  quente: { label: "Quente", color: "#f87171", bg: "#fef2f2", dotColor: "#f87171", borderColor: "#f87171" },
  morno:  { label: "Morno",  color: "#ca8a04", bg: "#fefce8", dotColor: "#e8d44d", borderColor: "#e8d44d" },
  frio:   { label: "Frio",   color: "#60a5fa", bg: "#eff6ff", dotColor: "#60a5fa", borderColor: "#60a5fa" },
} as const;
