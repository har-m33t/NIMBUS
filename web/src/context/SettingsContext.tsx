import { createContext, useContext, useState, useEffect, type ReactNode } from "react";

export interface NimbusSettings {
  voice: string;
  fontSize: "small" | "medium" | "large";
  captionPos: "bottom" | "top";
  theme: "light" | "dark";
  aslEnabled: boolean;
  zoomUrl: string;
}

const DEFAULTS: NimbusSettings = {
  voice: "Matthew",
  fontSize: "medium",
  captionPos: "bottom",
  theme: "light",
  aslEnabled: true,
  zoomUrl: "",
};

const STORAGE_KEY = "nimbus_settings";

function load(): NimbusSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch { /* ignore */ }
  return { ...DEFAULTS };
}

interface SettingsCtx {
  settings: NimbusSettings;
  update: (patch: Partial<NimbusSettings>) => void;
}

const Ctx = createContext<SettingsCtx>({ settings: DEFAULTS, update: () => {} });

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<NimbusSettings>(load);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  }, [settings]);

  function update(patch: Partial<NimbusSettings>) {
    setSettings((prev) => ({ ...prev, ...patch }));
  }

  return <Ctx.Provider value={{ settings, update }}>{children}</Ctx.Provider>;
}

export function useSettings() {
  return useContext(Ctx);
}
