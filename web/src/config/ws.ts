export const WS_CONFIG = {
  url: import.meta.env.VITE_NIMBUS_WS_URL || "",
} as const;

export function buildWsUrl(params: {
  token: string;
  sessionId: string;
  roomId: string;
}): string {
  if (!WS_CONFIG.url) {
    throw new Error(
      "VITE_NIMBUS_WS_URL is not set. Copy web/.env.example to .env.local and fill it in."
    );
  }
  const u = new URL(WS_CONFIG.url);
  u.searchParams.set("token", params.token);
  u.searchParams.set("sessionId", params.sessionId);
  u.searchParams.set("roomId", params.roomId);
  return u.toString();
}
