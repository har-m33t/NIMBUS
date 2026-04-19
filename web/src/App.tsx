import { Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext.tsx";
import { CloudTransitionProvider, useCloudTransition } from "./context/CloudTransitionContext.tsx";
import { SettingsProvider } from "./context/SettingsContext.tsx";
import { TelemetryProvider } from "./context/TelemetryContext.tsx";
import CloudLayers from "./components/effects/CloudBackground.tsx";
import GlassBox from "./components/GlassBox.tsx";
import AppShell from "./components/layout/AppShell.tsx";
import SignIn from "./pages/SignIn.tsx";
import SignUp from "./pages/SignUp.tsx";
import ForgotPassword from "./pages/ForgotPassword.tsx";
import Dashboard from "./pages/Dashboard.tsx";
import Session from "./pages/Session.tsx";
import Settings from "./pages/Settings.tsx";
import OAuthCallback from "./pages/OAuthCallback.tsx";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/signin" replace />;
  return <>{children}</>;
}

function PublicRoute({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (user) return <Navigate to="/" replace />;
  return <>{children}</>;
}

/** Single persistent cloud layer driven by CloudTransitionContext */
function PersistentClouds() {
  const { phase } = useCloudTransition();
  return <CloudLayers envelope={phase === "envelope"} parting={phase === "parting"} />;
}

export default function App() {
  return (
    <TelemetryProvider>
    <AuthProvider>
      <SettingsProvider>
      <CloudTransitionProvider>
        <PersistentClouds />
        <GlassBox />
        <Routes>
          {/* Public auth routes */}
          <Route path="/signin" element={<PublicRoute><SignIn /></PublicRoute>} />
          <Route path="/signup" element={<PublicRoute><SignUp /></PublicRoute>} />
          <Route path="/forgot-password" element={<PublicRoute><ForgotPassword /></PublicRoute>} />
          <Route path="/oauth/callback" element={<OAuthCallback />} />

          {/* Protected app routes */}
          <Route path="/" element={<ProtectedRoute><AppShell /></ProtectedRoute>}>
            <Route index element={<Dashboard />} />
            <Route path="session/:roomId" element={<Session />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </CloudTransitionProvider>
      </SettingsProvider>
    </AuthProvider>
    </TelemetryProvider>
  );
}
