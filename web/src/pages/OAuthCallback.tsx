import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext.tsx";

export default function OAuthCallback() {
  const [searchParams] = useSearchParams();
  const { handleOAuthCallback } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState("");

  useEffect(() => {
    const code = searchParams.get("code");
    const oauthError = searchParams.get("error");

    if (oauthError) {
      setError(oauthError);
      setTimeout(() => navigate("/signin"), 2000);
      return;
    }

    if (!code) {
      setError("No authorization code received");
      setTimeout(() => navigate("/signin"), 2000);
      return;
    }

    handleOAuthCallback(code)
      .then(() => navigate("/"))
      .catch((err) => {
        setError(err?.message || "OAuth sign-in failed");
        setTimeout(() => navigate("/signin"), 3000);
      });
  }, [searchParams, handleOAuthCallback, navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center">
      {error ? (
        <div className="text-center">
          <p className="text-nimbus-coral text-sm mb-2">{error}</p>
          <p className="text-nimbus-mist text-xs">Redirecting to sign in…</p>
        </div>
      ) : (
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-nimbus-gold border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-nimbus-mist text-sm">Completing sign in…</p>
        </div>
      )}
    </div>
  );
}
