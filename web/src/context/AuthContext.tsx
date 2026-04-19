import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from "react";
import {
  CognitoUserPool,
  CognitoUser,
  AuthenticationDetails,
  CognitoUserAttribute,
  CognitoUserSession,
} from "amazon-cognito-identity-js";
import { COGNITO_CONFIG } from "../config/cognito.ts";

// ── Cognito pool instance ────────────────────────────────────────────────────

const userPool = COGNITO_CONFIG.userPoolId
  ? new CognitoUserPool({
      UserPoolId: COGNITO_CONFIG.userPoolId,
      ClientId: COGNITO_CONFIG.clientId,
    })
  : null;

// ── Types ────────────────────────────────────────────────────────────────────

interface User {
  id: string;
  email: string;
  displayName: string;
}

interface AuthState {
  user: User | null;
  loading: boolean;
  /** Cognito ID token for authenticating WebSocket connections */
  idToken: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, displayName: string) => Promise<void>;
  signOut: () => void;
  resetPassword: (email: string) => Promise<void>;
  /** Confirmation step after sign-up (Cognito sends a verification code) */
  confirmSignUp: (email: string, code: string) => Promise<void>;
  /** Redirect to Cognito Hosted UI for Google sign-in */
  signInWithGoogle: () => void;
  /** Exchange OAuth authorization code for tokens (called from callback route) */
  handleOAuthCallback: (code: string) => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

// ── Helper: extract User from Cognito session ────────────────────────────────

function userFromSession(session: CognitoUserSession): User {
  const payload = session.getIdToken().decodePayload();
  return {
    id: payload.sub as string,
    email: (payload.email as string) || "",
    displayName: (payload.name as string) || (payload.email as string)?.split("@")[0] || "User",
  };
}

// ── Fallback mock auth (when Cognito env vars are not set) ───────────────────

function useMockAuth(): AuthState {
  const [user, setUser] = useState<User | null>(() => {
    const stored = localStorage.getItem("nimbus_user");
    return stored ? JSON.parse(stored) : null;
  });
  const [loading, setLoading] = useState(false);

  const signIn = useCallback(async (email: string, _password: string) => {
    setLoading(true);
    await new Promise((r) => setTimeout(r, 600));
    const u: User = { id: crypto.randomUUID(), email, displayName: email.split("@")[0] };
    localStorage.setItem("nimbus_user", JSON.stringify(u));
    setUser(u);
    setLoading(false);
  }, []);

  const signUp = useCallback(async (email: string, _password: string, displayName: string) => {
    setLoading(true);
    await new Promise((r) => setTimeout(r, 600));
    const u: User = { id: crypto.randomUUID(), email, displayName };
    localStorage.setItem("nimbus_user", JSON.stringify(u));
    setUser(u);
    setLoading(false);
  }, []);

  const signOut = useCallback(() => {
    localStorage.removeItem("nimbus_user");
    setUser(null);
  }, []);

  const resetPassword = useCallback(async (_email: string) => {
    setLoading(true);
    await new Promise((r) => setTimeout(r, 600));
    setLoading(false);
  }, []);

  const confirmSignUp = useCallback(async (_email: string, _code: string) => {}, []);

  const signInWithGoogle = useCallback(() => {
    // Mock: simulate Google sign-in
    const u: User = { id: crypto.randomUUID(), email: "user@gmail.com", displayName: "Google User" };
    localStorage.setItem("nimbus_user", JSON.stringify(u));
    setUser(u);
  }, []);

  const handleOAuthCallback = useCallback(async (_code: string) => {
    // Mock: same as above
    const u: User = { id: crypto.randomUUID(), email: "user@gmail.com", displayName: "Google User" };
    localStorage.setItem("nimbus_user", JSON.stringify(u));
    setUser(u);
  }, []);

  return { user, loading, idToken: null, signIn, signUp, signOut, resetPassword, confirmSignUp, signInWithGoogle, handleOAuthCallback };
}

// ── Real Cognito auth ────────────────────────────────────────────────────────

function useCognitoAuth(): AuthState {
  const [user, setUser] = useState<User | null>(null);
  const [idToken, setIdToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true); // starts true for session restore

  // Restore existing session on mount
  useEffect(() => {
    const cognitoUser = userPool!.getCurrentUser();
    if (!cognitoUser) {
      setLoading(false);
      return;
    }
    cognitoUser.getSession((err: Error | null, session: CognitoUserSession | null) => {
      if (!err && session && session.isValid()) {
        setUser(userFromSession(session));
        setIdToken(session.getIdToken().getJwtToken());
      }
      setLoading(false);
    });
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    setLoading(true);
    const cognitoUser = new CognitoUser({ Username: email, Pool: userPool! });
    const authDetails = new AuthenticationDetails({ Username: email, Password: password });

    return new Promise<void>((resolve, reject) => {
      cognitoUser.authenticateUser(authDetails, {
        onSuccess(session) {
          setUser(userFromSession(session));
          setIdToken(session.getIdToken().getJwtToken());
          setLoading(false);
          resolve();
        },
        onFailure(err) {
          setLoading(false);
          reject(err);
        },
      });
    });
  }, []);

  const signUp = useCallback(async (email: string, password: string, displayName: string) => {
    setLoading(true);
    const attributes = [
      new CognitoUserAttribute({ Name: "email", Value: email }),
      new CognitoUserAttribute({ Name: "name", Value: displayName }),
    ];

    return new Promise<void>((resolve, reject) => {
      userPool!.signUp(email, password, attributes, [], (err, _result) => {
        setLoading(false);
        if (err) {
          reject(err);
          return;
        }
        // User must confirm email before signing in
        resolve();
      });
    });
  }, []);

  const confirmSignUp = useCallback(async (email: string, code: string) => {
    setLoading(true);
    const cognitoUser = new CognitoUser({ Username: email, Pool: userPool! });

    return new Promise<void>((resolve, reject) => {
      cognitoUser.confirmRegistration(code, true, (err, _result) => {
        setLoading(false);
        if (err) {
          reject(err);
          return;
        }
        resolve();
      });
    });
  }, []);

  const signOut = useCallback(() => {
    const cognitoUser = userPool!.getCurrentUser();
    if (cognitoUser) cognitoUser.signOut();
    setUser(null);
    setIdToken(null);
  }, []);

  const resetPassword = useCallback(async (email: string) => {
    setLoading(true);
    const cognitoUser = new CognitoUser({ Username: email, Pool: userPool! });

    return new Promise<void>((resolve, reject) => {
      cognitoUser.forgotPassword({
        onSuccess() {
          setLoading(false);
          resolve();
        },
        onFailure(err) {
          setLoading(false);
          reject(err);
        },
      });
    });
  }, []);

  // Google sign-in via Cognito Hosted UI
  const signInWithGoogle = useCallback(() => {
    const { domain, region, clientId, redirectUri } = COGNITO_CONFIG;
    if (!domain) {
      alert("Google sign-in is not configured yet. Please use email/password to sign in.");
      return;
    }
    const hostedUiBase = `https://${domain}.auth.${region}.amazoncognito.com`;
    const params = new URLSearchParams({
      identity_provider: "Google",
      redirect_uri: redirectUri,
      response_type: "code",
      client_id: clientId,
      scope: "email openid profile",
    });
    window.location.href = `${hostedUiBase}/oauth2/authorize?${params.toString()}`;
  }, []);

  // Exchange OAuth authorization code for tokens
  const handleOAuthCallback = useCallback(async (code: string) => {
    const { domain, region, clientId, redirectUri } = COGNITO_CONFIG;
    const hostedUiBase = `https://${domain}.auth.${region}.amazoncognito.com`;

    setLoading(true);
    try {
      const resp = await fetch(`${hostedUiBase}/oauth2/token`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          grant_type: "authorization_code",
          client_id: clientId,
          redirect_uri: redirectUri,
          code,
        }),
      });

      if (!resp.ok) {
        throw new Error(`Token exchange failed: ${resp.status}`);
      }

      const data = await resp.json();
      const idTokenJwt = data.id_token as string;

      // Decode the ID token payload to extract user info
      const payload = JSON.parse(atob(idTokenJwt.split(".")[1]));
      setUser({
        id: payload.sub,
        email: payload.email || "",
        displayName: payload.name || payload.email?.split("@")[0] || "User",
      });
      setIdToken(idTokenJwt);
    } finally {
      setLoading(false);
    }
  }, []);

  return { user, loading, idToken, signIn, signUp, signOut, resetPassword, confirmSignUp, signInWithGoogle, handleOAuthCallback };
}

// ── Provider ─────────────────────────────────────────────────────────────────

// Choose the provider component once at module level so hooks are never
// called conditionally (React rules-of-hooks).
const InnerProvider = userPool ? CognitoAuthProvider : MockAuthProvider;

function CognitoAuthProvider({ children }: { children: ReactNode }) {
  const auth = useCognitoAuth();
  return <AuthContext.Provider value={auth}>{children}</AuthContext.Provider>;
}

function MockAuthProvider({ children }: { children: ReactNode }) {
  const auth = useMockAuth();
  return <AuthContext.Provider value={auth}>{children}</AuthContext.Provider>;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  return <InnerProvider>{children}</InnerProvider>;
}
