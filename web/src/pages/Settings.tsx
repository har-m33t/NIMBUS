import { useState } from "react";
import SpotlightCard from "../components/ui/SpotlightCard.tsx";
import NimbusButton from "../components/ui/NimbusButton.tsx";
import NimbusInput from "../components/ui/NimbusInput.tsx";

export default function Settings() {
  const [voice, setVoice] = useState("Matthew");
  const [fontSize, setFontSize] = useState<"small" | "medium" | "large">("medium");
  const [captionPos, setCaptionPos] = useState<"bottom" | "top">("bottom");
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [zoomUrl, setZoomUrl] = useState("");

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-nimbus-text mb-8">Settings</h1>

      <div className="space-y-6">
        {/* Voice Selection */}
        <SpotlightCard className="rounded-2xl p-6">
          <h2 className="text-sm font-medium text-nimbus-mist uppercase tracking-wider mb-4">Voice</h2>
          <div className="flex items-center gap-4">
            <select
              value={voice}
              onChange={(e) => setVoice(e.target.value)}
              className="flex-1 px-4 py-3 rounded-xl bg-white border border-nimbus-mist/20 text-nimbus-text focus:outline-none focus:ring-2 focus:ring-nimbus-gold/50 shadow-soft"
            >
              <option value="Matthew">Matthew (Male, US)</option>
              <option value="Joanna">Joanna (Female, US)</option>
              <option value="Amy">Amy (Female, UK)</option>
              <option value="Brian">Brian (Male, UK)</option>
            </select>
            <NimbusButton variant="secondary" size="sm">
              Preview
            </NimbusButton>
          </div>
          <p className="text-xs text-nimbus-mist mt-2">
            TTS voice adjusts pitch, rate, and volume based on detected emotion.
          </p>
        </SpotlightCard>

        {/* Caption Font Size */}
        <SpotlightCard className="rounded-2xl p-6">
          <h2 className="text-sm font-medium text-nimbus-mist uppercase tracking-wider mb-4">Caption Size</h2>
          <div className="flex gap-3">
            {(["small", "medium", "large"] as const).map((size) => {
              const px = { small: 20, medium: 24, large: 32 }[size];
              return (
                <button
                  key={size}
                  onClick={() => setFontSize(size)}
                  className={`flex-1 px-4 py-4 rounded-xl border transition-all ${
                    fontSize === size
                      ? "border-nimbus-gold/50 bg-nimbus-gold/5 text-nimbus-text"
                      : "border-nimbus-mist/15 text-nimbus-mist hover:border-nimbus-mist/30"
                  }`}
                >
                  <span style={{ fontSize: `${px}px` }} className="block mb-1">Aa</span>
                  <span className="text-xs capitalize">{size}</span>
                </button>
              );
            })}
          </div>
        </SpotlightCard>

        {/* Caption Position */}
        <SpotlightCard className="rounded-2xl p-6">
          <h2 className="text-sm font-medium text-nimbus-mist uppercase tracking-wider mb-4">Caption Position</h2>
          <div className="flex gap-3">
            {(["top", "bottom"] as const).map((pos) => (
              <button
                key={pos}
                onClick={() => setCaptionPos(pos)}
                className={`flex-1 px-4 py-4 rounded-xl border transition-all ${
                  captionPos === pos
                    ? "border-nimbus-gold/50 bg-nimbus-gold/5"
                    : "border-nimbus-mist/15 hover:border-nimbus-mist/30"
                }`}
              >
                <div className="w-full h-16 rounded-lg bg-nimbus-surface/50 relative mb-2">
                  <div className={`absolute left-2 right-2 h-3 rounded bg-nimbus-gold/30 ${pos === "top" ? "top-2" : "bottom-2"}`} />
                </div>
                <span className="text-xs text-nimbus-mist capitalize">{pos}</span>
              </button>
            ))}
          </div>
        </SpotlightCard>

        {/* Theme */}
        <SpotlightCard className="rounded-2xl p-6">
          <h2 className="text-sm font-medium text-nimbus-mist uppercase tracking-wider mb-4">Theme</h2>
          <div className="flex gap-3">
            {(["light", "dark"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTheme(t)}
                className={`flex-1 px-4 py-4 rounded-xl border transition-all flex items-center justify-center gap-2 ${
                  theme === t
                    ? "border-nimbus-gold/50 bg-nimbus-gold/5 text-nimbus-text"
                    : "border-nimbus-mist/15 text-nimbus-mist hover:border-nimbus-mist/30"
                }`}
              >
                {t === "dark" ? (
                  <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
                  </svg>
                ) : (
                  <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="5" />
                    <line x1="12" y1="1" x2="12" y2="3" />
                    <line x1="12" y1="21" x2="12" y2="23" />
                    <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
                    <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                    <line x1="1" y1="12" x2="3" y2="12" />
                    <line x1="21" y1="12" x2="23" y2="12" />
                    <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
                    <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
                  </svg>
                )}
                <span className="text-sm capitalize">{t}</span>
              </button>
            ))}
          </div>
        </SpotlightCard>

        {/* Zoom Integration */}
        <SpotlightCard className="rounded-2xl p-6">
          <h2 className="text-sm font-medium text-nimbus-mist uppercase tracking-wider mb-4">Zoom Integration</h2>
          <div className="flex items-center gap-3">
            <NimbusInput
              placeholder="Zoom Caption API URL"
              value={zoomUrl}
              onChange={(e) => setZoomUrl(e.target.value)}
              className="flex-1"
            />
            <NimbusButton variant="secondary" size="sm" disabled={!zoomUrl}>
              Test
            </NimbusButton>
          </div>
        </SpotlightCard>

        {/* Save */}
        <NimbusButton glow className="w-full">
          Save Preferences
        </NimbusButton>
      </div>
    </div>
  );
}
