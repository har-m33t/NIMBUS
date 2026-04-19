/**
 * Preferences API configuration.
 * Set VITE_PREFERENCES_API_URL in .env.local to the CloudFormation output
 * "PreferencesApiUrl" after deploying the SAM stack.
 */
export const PREFERENCES_API_URL = import.meta.env.VITE_PREFERENCES_API_URL || "";

export async function saveVoicePreference(userId: string, preferredVoiceId: string): Promise<void> {
  if (!PREFERENCES_API_URL) return;
  const resp = await fetch(PREFERENCES_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ userId, preferredVoiceId }),
  });
  if (!resp.ok) {
    const data = await resp.json().catch(() => ({}));
    throw new Error(data.error || `HTTP ${resp.status}`);
  }
}
