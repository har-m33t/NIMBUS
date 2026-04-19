import { Outlet, Link, useLocation } from "react-router-dom";
import { useAuth } from "../../context/AuthContext.tsx";
import ConnectionBadge from "../ui/ConnectionBadge.tsx";

export default function AppShell() {
  const { user, signOut } = useAuth();
  const location = useLocation();
  const isSession = location.pathname.startsWith("/session/");

  return (
    <div className="min-h-screen flex flex-col">
      {/* Aurora accent bar */}
      <div className="h-[2px] aurora-bar" aria-hidden="true" />

      {/* Header */}
      <header className="flex items-center justify-between px-6 py-3 bg-white/80 backdrop-blur-md border-b border-nimbus-mist/10 shadow-soft relative z-30">
        <div className="flex items-center gap-4">
          <Link to="/" className="flex items-center gap-2 group">
            {/* Nimbus wordmark */}
            <div className="relative">
              <div className="absolute inset-0 bg-nimbus-gold/20 blur-xl rounded-full" aria-hidden="true" />
              <svg className="w-8 h-8 text-nimbus-gold relative" viewBox="0 0 32 32" fill="none">
                <circle cx="16" cy="16" r="8" fill="currentColor" opacity="0.2" />
                <circle cx="16" cy="16" r="5" fill="currentColor" opacity="0.5" />
                <circle cx="16" cy="16" r="2.5" fill="currentColor" />
              </svg>
            </div>
            <span className="text-lg font-bold tracking-wider text-nimbus-text group-hover:text-nimbus-gold transition-colors">
              NIMBUS
            </span>
          </Link>

          {isSession && (
            <span className="text-xs text-nimbus-mist font-mono" id="session-timer">
              00:00
            </span>
          )}
        </div>

        <div className="flex items-center gap-4">
          <ConnectionBadge status="connected" />

          {/* User dropdown */}
          <div className="relative group">
            <button className="flex items-center gap-2 px-3 py-1.5 rounded-xl hover:bg-nimbus-surface transition-colors">
              <div className="w-8 h-8 rounded-full bg-nimbus-surface flex items-center justify-center text-sm font-semibold text-nimbus-gold border border-nimbus-gold/20">
                {user?.displayName?.[0]?.toUpperCase() || "?"}
              </div>
              <span className="text-sm text-nimbus-mist hidden sm:block">{user?.displayName}</span>
              <svg className="w-3 h-3 text-nimbus-mist" viewBox="0 0 12 12" fill="currentColor">
                <path d="M6 8L1 3h10L6 8z" />
              </svg>
            </button>

            {/* Dropdown menu */}
            <div className="absolute right-0 top-full mt-1 w-48 py-1 bg-white rounded-xl border border-nimbus-mist/10 shadow-cloud opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 z-50">
              <Link
                to="/settings"
                className="flex items-center gap-2 px-4 py-2.5 text-sm text-nimbus-mist hover:text-nimbus-text hover:bg-nimbus-surface/50 transition-colors"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="3" />
                  <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
                </svg>
                Settings
              </Link>
              <button
                onClick={signOut}
                className="flex items-center gap-2 w-full px-4 py-2.5 text-sm text-nimbus-coral hover:bg-nimbus-coral/5 transition-colors"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" />
                </svg>
                Sign Out
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 relative">
        <Outlet />
      </main>
    </div>
  );
}
