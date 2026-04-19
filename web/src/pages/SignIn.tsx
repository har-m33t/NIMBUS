import { useState, useEffect, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { useAuth } from "../context/AuthContext.tsx";
import { useCloudTransition } from "../context/CloudTransitionContext.tsx";
import NimbusGlow from "../components/effects/NimbusGlow.tsx";
import NimbusButton from "../components/ui/NimbusButton.tsx";
import NimbusInput from "../components/ui/NimbusInput.tsx";

export default function SignIn() {
  const { signIn, signInWithGoogle, loading } = useAuth();
  const { triggerEnvelope, triggerPart } = useCloudTransition();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  // On mount, part the global clouds to reveal sign-in form
  useEffect(() => {
    const t = setTimeout(() => triggerPart(), 150);
    return () => clearTimeout(t);
  }, [triggerPart]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      // 1. Envelope clouds over the screen
      await triggerEnvelope();
      // 2. Sign in (route will change behind the clouds)
      await signIn(email, password);
      // Dashboard will trigger the part on mount
    } catch (err: any) {
      // Auth failed — part clouds back open to show the form
      triggerPart();
      setError(err?.message || "Sign in failed");
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 relative overflow-hidden">

      <motion.div
        initial={{ opacity: 0, y: 60 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 1.2, delay: 0.2, ease: [0.22, 1, 0.36, 1] }}
        className="relative w-full max-w-md z-10"
      >
        {/* Nimbus wordmark + glow */}
        <div className="flex flex-col items-center mb-8 relative">
          <NimbusGlow size={250} color="gold" className="-top-[80px] left-1/2 -translate-x-1/2" />
          <div className="relative">
            <svg className="w-16 h-16 text-nimbus-gold mb-3" viewBox="0 0 32 32" fill="none">
              <circle cx="16" cy="16" r="12" fill="currentColor" opacity="0.1" />
              <circle cx="16" cy="16" r="8" fill="currentColor" opacity="0.2" />
              <circle cx="16" cy="16" r="5" fill="currentColor" opacity="0.5" />
              <circle cx="16" cy="16" r="2.5" fill="currentColor" />
            </svg>
          </div>
          <h1 className="text-3xl font-bold tracking-wider text-nimbus-text">NIMBUS</h1>
          <p className="text-nimbus-mist text-sm mt-1">Real-time ASL interpretation</p>
        </div>

        <div className="glass-strong rounded-2xl p-8">
          <h2 className="text-xl font-semibold text-nimbus-text mb-6 text-center">Sign In</h2>

          {error && (
            <div className="mb-4 px-4 py-2.5 rounded-xl bg-red-50 border border-nimbus-coral/20 text-sm text-nimbus-coral">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
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
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />

            <div className="flex justify-end">
              <Link to="/forgot-password" className="text-xs text-nimbus-teal hover:underline">
                Forgot password?
              </Link>
            </div>

            <NimbusButton type="submit" glow loading={loading} className="w-full mt-2">
              Sign In
            </NimbusButton>
          </form>

          {/* Divider */}
          <div className="flex items-center gap-3 my-6">
            <div className="flex-1 h-px bg-nimbus-mist/15" />
            <span className="text-xs text-nimbus-mist">or continue with</span>
            <div className="flex-1 h-px bg-nimbus-mist/15" />
          </div>

          {/* Google OAuth */}
          <NimbusButton variant="secondary" className="w-full gap-2" onClick={signInWithGoogle}>
            <svg className="w-5 h-5" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" />
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
            </svg>
            Continue with Google
          </NimbusButton>

          <p className="text-center text-sm text-nimbus-mist mt-6">
            Don't have an account?{" "}
            <Link to="/signup" className="text-nimbus-teal hover:underline font-medium">
              Sign Up
            </Link>
          </p>
        </div>
      </motion.div>
    </div>
  );
}
