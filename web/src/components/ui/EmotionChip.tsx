const EMOTION_STYLES: Record<string, { bg: string; emoji: string }> = {
  HAPPY:     { bg: "bg-emotion-happy",     emoji: "😊" },
  SAD:       { bg: "bg-emotion-sad",       emoji: "😢" },
  ANGRY:     { bg: "bg-emotion-angry",     emoji: "😠" },
  CALM:      { bg: "bg-emotion-calm",      emoji: "😌" },
  SURPRISED: { bg: "bg-emotion-surprised", emoji: "😲" },
  FEAR:      { bg: "bg-emotion-fear",      emoji: "😨" },
  DISGUSTED: { bg: "bg-emotion-disgusted", emoji: "🤢" },
  CONFUSED:  { bg: "bg-emotion-confused",  emoji: "😕" },
};

export default function EmotionChip({
  emotion,
  confidence,
  size = "sm",
}: {
  emotion: string;
  confidence?: number;
  size?: "sm" | "lg";
}) {
  const style = EMOTION_STYLES[emotion] || EMOTION_STYLES.CALM;
  const isSm = size === "sm";

  return (
    <div
      className={`inline-flex items-center gap-1.5 rounded-full transition-all duration-300 ${isSm ? "px-2 py-0.5 text-xs" : "px-3 py-1.5 text-sm"}`}
      style={{ background: `color-mix(in srgb, var(--color-emotion-${emotion.toLowerCase()}) 25%, white)` }}
    >
      <span>{style.emoji}</span>
      <span className="font-medium text-nimbus-text capitalize">{emotion.toLowerCase()}</span>
      {confidence !== undefined && (
        <span className="text-nimbus-mist">{Math.round(confidence * 100)}%</span>
      )}
    </div>
  );
}
