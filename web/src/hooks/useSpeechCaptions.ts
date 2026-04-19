import { useEffect, useRef, useState } from "react";

export interface SpeechCaption {
  id: string;
  text: string;
  timestamp: string;
}

interface UseSpeechCaptionsOptions {
  enabled: boolean;
  onCaption: (caption: SpeechCaption) => void;
}

export function useSpeechCaptions({ enabled, onCaption }: UseSpeechCaptionsOptions) {
  const [interimText, setInterimText] = useState("");
  const [supported] = useState(
    () => typeof window !== "undefined" && ("SpeechRecognition" in window || "webkitSpeechRecognition" in window),
  );
  const onCaptionRef = useRef(onCaption);
  onCaptionRef.current = onCaption;

  useEffect(() => {
    if (!supported || !enabled) {
      setInterimText("");
      return;
    }

    const SR =
      (window as unknown as { SpeechRecognition?: typeof SpeechRecognition }).SpeechRecognition ??
      (window as unknown as { webkitSpeechRecognition?: typeof SpeechRecognition }).webkitSpeechRecognition;

    if (!SR) return;

    const recognition = new SR();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    let active = true;

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) {
          const text = result[0].transcript.trim();
          if (text) {
            onCaptionRef.current({ id: `stt-${Date.now()}-${i}`, text, timestamp: new Date().toISOString() });
          }
        } else {
          interim += result[0].transcript;
        }
      }
      setInterimText(interim);
    };

    recognition.onend = () => {
      setInterimText("");
      // Auto-restart so it keeps listening without the user re-toggling
      if (active) {
        try { recognition.start(); } catch { /* already starting */ }
      }
    };

    try { recognition.start(); } catch { /* already started */ }

    return () => {
      active = false;
      recognition.onend = null;
      recognition.onresult = null;
      recognition.stop();
      setInterimText("");
    };
  }, [supported, enabled]);

  return { interimText, supported };
}
