export const THEME_STORAGE_KEY = "pies-pear-music-theme";

export type ThemeId = "amber-night" | "midnight" | "oled" | "lavender" | "daylight" | "high-contrast" | "forest" | "rosewood" | "solarized" | "paper";

export interface ThemePreset {
  id: ThemeId;
  name: string;
  description: string;
  colors: Record<string, string>;
}

export interface AppearanceConfig {
  version: 1;
  theme: ThemeId;
}

export const themes: ThemePreset[] = [
  {
    id: "amber-night", name: "Amber Night", description: "Warm dark default",
    colors: { "--bg": "#15131c", "--surface": "rgba(255,255,255,0.05)", "--border": "rgba(255,255,255,0.09)", "--accent": "#fcd34d", "--accent-hover": "#fde68a", "--accent-dim": "rgba(252,211,77,0.18)", "--accent-2": "#c4b5fd", "--accent-3": "#5eead4", "--text-primary": "#ffffff", "--text-secondary": "rgba(255,255,255,0.7)", "--text-muted": "rgba(255,255,255,0.48)" },
  },
  {
    id: "midnight", name: "Midnight Blue", description: "Cool dark blue",
    colors: { "--bg": "#0b1220", "--surface": "rgba(148,163,184,0.10)", "--border": "rgba(148,163,184,0.20)", "--accent": "#67e8f9", "--accent-hover": "#a5f3fc", "--accent-dim": "rgba(103,232,249,0.18)", "--accent-2": "#a5b4fc", "--accent-3": "#5eead4", "--text-primary": "#f8fafc", "--text-secondary": "#cbd5e1", "--text-muted": "#94a3b8" },
  },
  {
    id: "oled", name: "OLED", description: "True black with emerald",
    colors: { "--bg": "#000000", "--surface": "#101010", "--border": "#292929", "--accent": "#34d399", "--accent-hover": "#6ee7b7", "--accent-dim": "rgba(52,211,153,0.20)", "--accent-2": "#60a5fa", "--accent-3": "#f472b6", "--text-primary": "#ffffff", "--text-secondary": "#d4d4d4", "--text-muted": "#a3a3a3" },
  },
  {
    id: "lavender", name: "Lavender", description: "Soft multihue dark",
    colors: { "--bg": "#171326", "--surface": "rgba(196,181,253,0.10)", "--border": "rgba(196,181,253,0.22)", "--accent": "#c4b5fd", "--accent-hover": "#ddd6fe", "--accent-dim": "rgba(196,181,253,0.22)", "--accent-2": "#f9a8d4", "--accent-3": "#67e8f9", "--text-primary": "#faf5ff", "--text-secondary": "#ddd6fe", "--text-muted": "#b8add6" },
  },
  {
    id: "daylight", name: "Daylight", description: "High-legibility light",
    colors: { "--bg": "#f8fafc", "--surface": "#ffffff", "--border": "#cbd5e1", "--accent": "#a16207", "--accent-hover": "#854d0e", "--accent-dim": "#fef3c7", "--accent-2": "#5b21b6", "--accent-3": "#0f766e", "--text-primary": "#0f172a", "--text-secondary": "#334155", "--text-muted": "#64748b" },
  },
  {
    id: "high-contrast", name: "High Contrast", description: "Maximum separation",
    colors: { "--bg": "#000000", "--surface": "#000000", "--border": "#ffffff", "--accent": "#ffff00", "--accent-hover": "#ffffff", "--accent-dim": "#4d4d00", "--accent-2": "#00ffff", "--accent-3": "#ff00ff", "--text-primary": "#ffffff", "--text-secondary": "#ffffff", "--text-muted": "#e5e5e5" },
  },
  {
    id: "forest", name: "Forest", description: "Mossy green dark",
    colors: { "--bg": "#102019", "--surface": "#183126", "--border": "#31533d", "--accent": "#a3e635", "--accent-hover": "#bef264", "--accent-dim": "#365314", "--accent-2": "#2dd4bf", "--accent-3": "#facc15", "--text-primary": "#f0fdf4", "--text-secondary": "#bbd7c3", "--text-muted": "#8caf99" },
  },
  {
    id: "rosewood", name: "Rosewood", description: "Deep wine and coral",
    colors: { "--bg": "#241117", "--surface": "#351923", "--border": "#613044", "--accent": "#fb7185", "--accent-hover": "#fda4af", "--accent-dim": "#672837", "--accent-2": "#e879f9", "--accent-3": "#fbbf24", "--text-primary": "#fff1f2", "--text-secondary": "#f3c5ce", "--text-muted": "#bf8794" },
  },
  {
    id: "solarized", name: "Solarized", description: "Muted blue and gold",
    colors: { "--bg": "#002b36", "--surface": "#073642", "--border": "#285461", "--accent": "#b58900", "--accent-hover": "#d5b13e", "--accent-dim": "#584500", "--accent-2": "#2aa198", "--accent-3": "#268bd2", "--text-primary": "#fdf6e3", "--text-secondary": "#c8c1a9", "--text-muted": "#93a1a1" },
  },
  {
    id: "paper", name: "Paper", description: "Warm light neutral",
    colors: { "--bg": "#f7f1e5", "--surface": "#fffdf7", "--border": "#d8cdb9", "--accent": "#9a3412", "--accent-hover": "#7c2d12", "--accent-dim": "#fed7aa", "--accent-2": "#6d28d9", "--accent-3": "#0f766e", "--text-primary": "#292524", "--text-secondary": "#57534e", "--text-muted": "#78716c" },
  },
];

export function getStoredTheme(): ThemeId {
  if (typeof localStorage === "undefined") return "amber-night";
  const value = localStorage.getItem(THEME_STORAGE_KEY);
  return themes.some((theme) => theme.id === value) ? value as ThemeId : "amber-night";
}

export function applyTheme(id: ThemeId): void {
  const theme = themes.find((candidate) => candidate.id === id) ?? themes[0];
  for (const [token, value] of Object.entries(theme.colors)) {
    document.documentElement.style.setProperty(token, value);
  }
  document.documentElement.dataset.theme = theme.id;
  localStorage.setItem(THEME_STORAGE_KEY, theme.id);
}

export function serializeAppearance(id: ThemeId): string {
  const config: AppearanceConfig = { version: 1, theme: id };
  return `${JSON.stringify(config, null, 2)}\n`;
}

export function parseAppearance(value: string): ThemeId {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error("Theme file is not valid JSON");
  }
  if (
    !parsed || typeof parsed !== "object" ||
    (parsed as { version?: unknown }).version !== 1 ||
    typeof (parsed as { theme?: unknown }).theme !== "string"
  ) {
    throw new Error("Theme file must use appearance schema version 1");
  }
  const theme = (parsed as { theme: string }).theme;
  if (!themes.some((candidate) => candidate.id === theme)) {
    throw new Error("Theme file names an unsupported preset");
  }
  return theme as ThemeId;
}

function relativeLuminance(hex: string): number {
  const match = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!match) throw new Error(`Expected a six-digit hex color, received ${hex}`);
  const channels = [0, 2, 4].map((offset) => parseInt(match[1].slice(offset, offset + 2), 16) / 255);
  const linear = channels.map((channel) => (
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  ));
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

export function textContrast(id: ThemeId): number {
  const theme = themes.find((candidate) => candidate.id === id) ?? themes[0];
  const background = relativeLuminance(theme.colors["--bg"]);
  const text = relativeLuminance(theme.colors["--text-primary"]);
  return (Math.max(background, text) + 0.05) / (Math.min(background, text) + 0.05);
}
