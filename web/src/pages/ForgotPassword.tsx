import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext.tsx";
import NimbusButton from "../components/ui/NimbusButton.tsx";
import NimbusInput from "../components/ui/NimbusInput.tsx";

export default function ForgotPassword() {
  const { resetPassword, loading } = useAuth();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    await resetPassword(email);
    setSent(true);
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 relative">

      <div className="relative w-full max-w-md z-10">
        <div className="glass-strong rounded-2xl p-8">
          <h2 className="text-xl font-semibold text-nimbus-text mb-2 text-center">Reset Password</h2>
          <p className="text-sm text-nimbus-mist text-center mb-6">
            Enter your email and we'll send a verification code.
          </p>

          {sent ? (
            <div className="text-center">
              <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-nimbus-teal/10 flex items-center justify-center">
                <svg className="w-8 h-8 text-nimbus-teal" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
                  <polyline points="22 4 12 14.01 9 11.01" />
                </svg>
              </div>
              <p className="text-nimbus-text mb-4">Check your email for a reset code.</p>
              <Link to="/signin" className="text-nimbus-teal hover:underline text-sm font-medium">
                Back to Sign In
              </Link>
            </div>
          ) : (
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
              <NimbusButton type="submit" glow loading={loading} className="w-full">
                Send Reset Code
              </NimbusButton>
              <Link to="/signin" className="text-center text-sm text-nimbus-mist hover:text-nimbus-teal transition-colors">
                Back to Sign In
              </Link>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
