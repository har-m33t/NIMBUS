import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.tsx";
import NimbusGlow from "../components/effects/NimbusGlow.tsx";
import NimbusButton from "../components/ui/NimbusButton.tsx";
import NimbusInput from "../components/ui/NimbusInput.tsx";

export default function SignUp() {
  const { signUp, confirmSignUp, signIn, loading } = useAuth();
  const navigate = useNavigate();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [needsConfirmation, setNeedsConfirmation] = useState(false);
  const [code, setCode] = useState("");

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (password !== confirm) {
      setError("Passwords do not match");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    try {
      await signUp(email, password, displayName);
      // Cognito requires email verification before sign-in
      setNeedsConfirmation(true);
    } catch (err: any) {
      setError(err?.message || "Sign up failed");
    }
  }

  async function handleConfirm(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await confirmSignUp(email, code);
      // Auto sign-in after confirmation
      await signIn(email, password);
      navigate("/");
    } catch (err: any) {
      setError(err?.message || "Verification failed");
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 relative">

      <div className="relative w-full max-w-md z-10">
        <div className="flex flex-col items-center mb-8 relative">
          <NimbusGlow size={250} color="gold" className="-top-[80px] left-1/2 -translate-x-1/2" />
          <svg className="w-16 h-16 text-nimbus-gold mb-3" viewBox="0 0 32 32" fill="none">
            <circle cx="16" cy="16" r="12" fill="currentColor" opacity="0.1" />
            <circle cx="16" cy="16" r="8" fill="currentColor" opacity="0.2" />
            <circle cx="16" cy="16" r="5" fill="currentColor" opacity="0.5" />
            <circle cx="16" cy="16" r="2.5" fill="currentColor" />
          </svg>
          <h1 className="text-3xl font-bold tracking-wider text-nimbus-text">NIMBUS</h1>
          <p className="text-nimbus-mist text-sm mt-1">Create your account</p>
        </div>

        <div className="glass-strong rounded-2xl p-8">
          <h2 className="text-xl font-semibold text-nimbus-text mb-6 text-center">
            {needsConfirmation ? "Verify Email" : "Sign Up"}
          </h2>

          {error && (
            <div className="mb-4 px-4 py-2.5 rounded-xl bg-red-50 border border-nimbus-coral/20 text-sm text-nimbus-coral">
              {error}
            </div>
          )}

          {needsConfirmation ? (
            <form onSubmit={handleConfirm} className="flex flex-col gap-4">
              <p className="text-sm text-nimbus-mist text-center mb-2">
                We sent a verification code to <span className="text-nimbus-text font-medium">{email}</span>
              </p>
              <NimbusInput
                label="Verification Code"
                type="text"
                placeholder="Enter 6-digit code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
                autoComplete="one-time-code"
              />
              <NimbusButton type="submit" glow loading={loading} className="w-full mt-2">
                Verify & Sign In
              </NimbusButton>
            </form>
          ) : (
            <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <NimbusInput
              label="Display Name"
              type="text"
              placeholder="Your name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              required
              autoComplete="name"
            />
            <NimbusInput
              label="Email"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
            />
            <NimbusInput
              label="Password"
              type="password"
              placeholder="At least 8 characters"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="new-password"
            />
            <NimbusInput
              label="Confirm Password"
              type="password"
              placeholder="••••••••"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
              autoComplete="new-password"
            />

            <NimbusButton type="submit" glow loading={loading} className="w-full mt-2">
              Create Account
            </NimbusButton>
          </form>
          )}

          <p className="text-center text-sm text-nimbus-mist mt-6">
            Already have an account?{" "}
            <Link to="/signin" className="text-nimbus-teal hover:underline font-medium">
              Sign In
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
