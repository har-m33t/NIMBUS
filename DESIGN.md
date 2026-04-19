# NIMBUS — Design Specification

> **Frontend Design Source of Truth** — All UI implementation must reference this file.
> Last updated: 2026-04-18

---

## 1. Information Architecture & Sitemap

### Auth (Public Routes)
- **Sign In** — Email/Password + Google OAuth
- **Sign Up** — Email/Password + Email Verification Code
- **Forgot Password** — Email → Verification Code → New Password

### App (Protected Routes — require Cognito auth)
- **Dashboard** — "Start Session" CTA, Join Room input, Recent Sessions list
- **Active Session** (`/session/:roomId`) — Real-time interpretation view
  - Webcam Feed (with MediaPipe skeleton overlay)
  - Gloss Token Ticker
  - Caption Bar (Emotion badges + TTS audio indicator)
  - Participants Panel (collapsible sidebar)
  - Signal Quality Indicator + Status Orb
  - Emotion Display
- **Settings** — User Preferences (Voice, Captions, Theme, Zoom integration)

### Global Shell
- Header: NIMBUS wordmark, session timer, user avatar dropdown, connection badge

---

## 2. Design Philosophy — "Above the Clouds"

NIMBUS evokes the luminous space above clouds where light breaks through. The UI is **light, airy, and open** — a sky you look up into. Content lives in the clearing between soft, layered clouds that frame every screen from the sides.

1. **Light & Airy** — White and sky-blue dominate. Depth comes from layered clouds and soft shadows, not darkness.
2. **Cloud-Framed Content** — Opaque, layered cloud shapes drift in from both edges of every screen, creating a natural viewport into the app content.
3. **The User's Face is the Hero** — The webcam feed is dominant. Everything orbits it.
4. **Accessibility is the Product** — WCAG 2.1 AA floor. Visual-first, no audio-only cues.
5. **Trust Through Transparency** — Show the pipeline working: gloss tokens, signal strength, emotion.
6. **Elevated Interactions** — Cards tilt on hover (3D perspective), buttons have animated gradient borders, captions reveal word-by-word. Every micro-interaction feels polished.

---

## 3. Screen-by-Screen Wireframes

### A. Auth Screens
- Light sky gradient background (white → soft blue-lavender)
- **Layered cloud shapes** from both sides — 3–4 opaque SVG cloud layers at different depths
- Centered card (480px max-width) with **frosted glass** on white (`backdrop-blur + white/80`)
- NIMBUS wordmark + nimbus glow halo above the form
- Nimbus Gold primary CTA buttons with animated gradient border
- Social sign-in (Google) as outlined secondary button
- Smooth transitions between sign-in / sign-up / forgot-password
- Mouse-tracked parallax on cloud layers for depth

### B. Dashboard / Home
- Sky gradient background with **layered opaque clouds from both sides**
  - Left clouds: 2–3 stacked cloud SVGs, partially off-screen, different vertical positions
  - Right clouds: 2–3 complementary cloud SVGs mirrored
  - Each layer drifts at a different speed (parallax effect)
  - Content sits in the "clearing" between the clouds
- Center-aligned hero area:
  - Large "Start Session" button with **animated moving gradient border** and soft gold glow
  - "Join Room" text input + button below
- Recent Sessions: **Spotlight Cards** — white cards with cursor-tracking radial light
- Empty state (first-time): illustrated onboarding card with camera positioning tip
- Connection badge in header (Soft Teal = connected)

### C. Active Session Screen (Primary — most design attention)

```
┌─────────────────────────────────────────────────────────┐
│ Header: NIMBUS | Timer | Room ID | ◉ Orb | Controls    │
├──────────────────────────────────┬──────────────────────┤
│                                  │   Participants       │
│        WEBCAM FEED               │   (collapsible)      │
│        (dominant, ~65% width)    │                      │
│                                  │   Emotion Badge      │
│        [MediaPipe overlay]       │   ● HAPPY 93%        │
│        [TRACKING badge]          │                      │
├──────────────────────────────────┴──────────────────────┤
│  Gloss Ticker:  [STORE] [I] [GO] [TO]  ···             │
├─────────────────────────────────────────────────────────┤
│  Caption Bar:                                           │
│  😊 "I am going to the store."                    🔊   │
│  😌 "The weather is nice today."                  🔊   │
└─────────────────────────────────────────────────────────┘
```

- **Video Panel**: 65% width, 16px rounded corners, soft shadow
- **MediaPipe overlay**: Soft Teal lines at 40% opacity, toggleable
- **TRACKING badge**: Teal pill when hands detected, gray "Waiting…" when idle
- **Gloss Ticker**: White pills with soft blue border, 200ms slide-in
- **Caption Bar**: Sticky bottom, 24px Inter, emotion color chips, **word-by-word text reveal** (300ms)
- **Status Orb**: Animated floating orb in header — changes color/pulse based on system state (replacing simple signal dot)
- **Participants Panel**: Collapsible right sidebar with frosted glass, room ID + member list

### D. SageMaker Warming Overlay
- Semi-transparent white overlay (85% opacity) with blur
- Centered animated nimbus glow (concentric expanding rings in Gold at low opacity)
- "Warming up the AI model…" + "Usually takes 30–90 seconds"
- Gold shimmer particles floating upward
- Auto-dismisses on first GLOSS event (500ms fade-out)

### E. Settings
- Modal or dedicated page on sky gradient background
- Sections: Voice, Captions (size + position), Theme (dark/light), Zoom integration
- Each section in a **Spotlight Card** that responds to cursor
- All changes persist to `NIMBUS_PROD_UserPreferences`

---

## 4. Component Inventory

### Core UI Components

| Component | Props / State | Variants |
|---|---|---|
| `NimbusButton` | `variant`, `size`, `glow`, `loading` | primary (Gold), secondary (outlined), danger (Coral), ghost |
| `MovingBorderButton` | `duration`, `borderColor` | Animated gradient border that orbits the button edge |
| `SpotlightCard` | `children`, `className` | White card with cursor-tracking radial light highlight |
| `GlassCard` | `blur`, `opacity`, `glow` | Frosted white glass (not dark) |
| `ConnectionBadge` | `status` | connected, disconnected, reconnecting |
| `StatusOrb` | `state` | active (teal pulse), warming (gold breathe), error (coral flicker), idle (mist) |
| `SignalIndicator` | `latencyMs` | strong, degraded, poor, offline |

### Cloud & Effect Components

| Component | Props / State | Description |
|---|---|---|
| `CloudLayers` | `intensity`, `parallax` | Layered opaque SVG clouds from both sides with mouse-tracked parallax |
| `SkyGradient` | — | Full-screen white → sky-blue → lavender gradient background |
| `NimbusGlow` | `color`, `size`, `pulse` | Soft radial glow behind focal elements |
| `WarmthParticles` | — | Rising gold particles for warming overlay |

### Session Components

| Component | Props / State | Variants |
|---|---|---|
| `GlossTokenPill` | `token`, `confidence` | normal, error (`[UNKNOWN_SIGN]`) |
| `GlossTicker` | `tokens[]` | Horizontal scrolling pill container |
| `CaptionBar` | `captions[]` | With word-by-word text reveal animation |
| `EmotionChip` | `emotion`, `confidence` | all 8 emotions |
| `VideoFeed` | `showOverlay`, `isTracking` | with/without MediaPipe skeleton |
| `ParticipantsPanel` | `participants[]` | expanded, collapsed |
| `WarmingOverlay` | `visible` | shown, dismissing |
| `TextReveal` | `text`, `delay` | Word-by-word fade-in effect for captions |

### Notification Components

| Component | Props / State | Variants |
|---|---|---|
| `ToastNotification` | `message`, `type`, `duration` | info, error, warning |
| `ReconnectBanner` | `attempt`, `maxAttempts` | reconnecting, failed |

---

## 5. Real-Time Data Flow (WebSocket → UI)

| Event Type | Drives Component | Frequency |
|---|---|---|
| `GLOSS` | Gloss Token Ticker — appends new pills | ~10/s at peak |
| `CAPTION` | Caption Bar — appends new row with text reveal, clears ticker | On sentence boundary |
| `EMOTION` | Emotion Display + current caption badge | ~1/s (every 10th frame) |
| `SIGNAL (ENDPOINT_WARMING)` | Warming Overlay + Status Orb → gold breathe | Once per cold start |
| `SIGNAL (NEW_CAPTION)` | Caption Bar — other participants' captions | Per remote caption |
| `SIGNAL (JOIN_ROOM/LEAVE_ROOM)` | Participants Panel — add/remove member | On room change |
| `ERROR` | Toast + inline fallbacks + Status Orb → coral flicker | On failure |

---

## 6. Design Tokens

### Colors — Light Mode (Default)

| Token | Hex | Usage |
|---|---|---|
| `bg-primary` | `#F8FAFF` | Main background — near-white with blue tint |
| `bg-elevated` | `#FFFFFF` | Cards, panels, pills — pure white |
| `bg-surface` | `#EDF2FA` | Inputs, hover states — soft blue-gray |
| `accent-primary` | `#E8B931` | Nimbus Gold — CTAs, own captions |
| `accent-secondary` | `#4ECDC4` | Soft Teal — connected states, tracking |
| `text-primary` | `#1A2035` | Dark slate — headings, captions |
| `text-secondary` | `#64748B` | Slate gray — labels, timestamps |
| `signal-green` | `#22C55E` | Latency < 800ms |
| `signal-amber` | `#F59E0B` | Latency 800–1500ms |
| `signal-red` | `#EF4444` | Latency > 1500ms |
| `signal-gray` | `#94A3B8` | Offline / no response |
| `error` | `#EF4444` | Error Red |
| `cloud-1` | `#FFFFFF` | Foreground cloud layer — pure white |
| `cloud-2` | `#E8EDF6` | Midground cloud — soft lavender |
| `cloud-3` | `#D4DCF0` | Background cloud — blue-gray |
| `sky-top` | `#F8FAFF` | Sky gradient start |
| `sky-mid` | `#E0EAFC` | Sky gradient middle |
| `sky-bottom` | `#CFDEF3` | Sky gradient end |

### Colors — Dark Mode (Optional)

| Token | Hex |
|---|---|
| `bg-primary` | `#0F1629` |
| `bg-elevated` | `#1A2035` |
| `bg-surface` | `#232841` |
| `text-primary` | `#F0EDE8` |
| `text-secondary` | `#8B8FA3` |
| Accents remain the same |

### Emotion Color Chips

| Emotion | Chip Color |
|---|---|
| HAPPY | `#FDE68A` |
| SAD | `#93C5FD` |
| ANGRY | `#FCA5A5` |
| CALM | `#A7F3D0` |
| SURPRISED | `#C4B5FD` |
| FEAR | `#FCD34D` |
| DISGUSTED | `#BEF264` |
| CONFUSED | `#DDD6FE` |

### Typography

- **Primary**: Inter (system fallback: -apple-system, BlinkMacSystemFont, Segoe UI)
- **Monospace** (fallback captions): JetBrains Mono
- **Scale**: 12 / 14 / 16 / 20 / 24 / 32 / 40px
- **Caption default**: 24px ("medium"), user-selectable 20px / 32px

### Spacing Scale (4px base)

| Token | Value |
|---|---|
| `xs` | 4px |
| `sm` | 8px |
| `md` | 16px |
| `lg` | 24px |
| `xl` | 32px |
| `xxl` | 48px |
| `huge` | 64px |

### Shadows

| Token | Value | Usage |
|---|---|---|
| `shadow-sm` | `0 1px 3px rgba(0,0,0,0.04)` | Subtle card edges |
| `shadow-md` | `0 4px 16px rgba(0,0,0,0.06)` | Elevated cards |
| `shadow-lg` | `0 8px 32px rgba(0,0,0,0.08)` | Modals, overlays |
| `shadow-glow-gold` | `0 0 30px rgba(232,185,49,0.15)` | Gold CTA hover |
| `shadow-glow-teal` | `0 0 20px rgba(78,205,196,0.12)` | Teal accents |
| `shadow-cloud` | `0 8px 40px rgba(0,0,0,0.05)` | Cloud layer depth |

---

## 7. Accessibility

- **ARIA-live regions**: Caption Bar uses `aria-live="polite"` for screen reader announcements
- **Focus management**: All interactive elements have visible focus rings (2px Nimbus Gold outline)
- **Contrast**: All text meets WCAG 2.1 AA (4.5:1 for body text, 3:1 for large text). Light palette ensures dark-on-light readability.
- **No audio-only cues**: Every TTS event has a visual pulse indicator on the speaker icon
- **Keyboard navigation**: Full tab order through all controls, Escape closes modals/overlays
- **Reduced motion**: Respects `prefers-reduced-motion` — disables cloud parallax/drift, replaces transitions with instant state changes

---

## 8. Animation & Motion

| Animation | Duration | Easing | Trigger |
|---|---|---|---|
| Gloss pill slide-in | 200ms | `cubic-bezier(0.4, 0, 0.2, 1)` | New GLOSS token |
| Caption word-by-word reveal | 40ms per word | ease-out | New CAPTION |
| Emotion chip crossfade | 300ms | ease-in-out | EMOTION change |
| Warming overlay fade-in/out | 500ms | ease-in-out | ENDPOINT_WARMING signal |
| Status orb pulse | 2000ms | ease-in-out | Continuous when active |
| Status orb breathe | 3000ms | ease-in-out | Warming state |
| Cloud layer drift | 40–60s | linear | Continuous |
| Cloud parallax | instant | — | Mouse move (throttled 16ms) |
| Moving border orbit | 4000ms | linear | Continuous on CTA |
| Spotlight card follow | instant | — | Mouse move on card |
| 3D card tilt | instant | spring(0.1) | Mouse move on card |
| Nimbus glow halo | 3000ms | ease-in-out | Hover on primary CTA |
| Toast slide-in/out | 200ms | ease-out | Error/info events |

---

## 9. Responsive Breakpoints

| Breakpoint | Layout |
|---|---|
| **Desktop** (≥1920px) | 3-column: Feed \| Participants \| Emotions. Full cloud layers visible. |
| **Laptop** (≥1280px) | 2-column: Feed \| Emotions, Participants as collapsible drawer. Cloud layers scaled. |
| **Tablet** (≥768px) | Vertical stack: Feed top, Captions bottom, Participants in sheet. Clouds hidden. |
| **Minimum** | 1280×720 — below this, show "Please use a larger screen" message |

---

## 10. Error State Catalog

| Error | Visual Treatment |
|---|---|
| WebSocket Disconnected | Slim amber banner below header: "Reconnecting… (Attempt 2/5)" with spinner. Status Orb → coral flicker. After 5 fails → red: "Connection lost." + Retry button |
| SageMaker Failed | `[UNKNOWN_SIGN]` pill in red in gloss ticker. Toast: "Sign not recognized." (3s) |
| Bedrock Timeout | Caption in JetBrains Mono italic at 70% opacity + "⚠ raw gloss" chip |
| Rekognition Failed | Silent. Emotion defaults to CALM. No user-facing indicator |
| Polly Failed | Caption text appears normally. Speaker icon → gray strikethrough. Toast: "Audio unavailable." (3s) |

---

## 11. Cloud Visual Effects — "Above the Clouds"

The app's signature visual identity is **layered, opaque clouds framing the content from both sides**.

### Layered Cloud System

- **Architecture**: 3 depth layers on each side (left + right = 6 total cloud groups)
  - **Layer 1 (foreground)**: Pure white clouds, largest, closest to content edge, slight blur
  - **Layer 2 (midground)**: Soft lavender `#E8EDF6` clouds, medium size, more blur
  - **Layer 3 (background)**: Blue-gray `#D4DCF0` clouds, smallest, most blur, most distant
- **Positioning**: Clouds are partially off-screen, protruding 20–40% of their width into the viewport
- **Animation**: Each layer drifts vertically at different speeds (40s, 50s, 60s cycles)
- **Parallax**: Mouse movement shifts layers at different rates (Layer 1: 3%, Layer 2: 2%, Layer 3: 1%) creating depth
- **SVG shapes**: Organic, rounded cloud silhouettes (not simple circles) — generated as `<path>` elements

### Sky Gradient

- Full-screen background: linear gradient from `#F8FAFF` (top) through `#E0EAFC` (middle) to `#CFDEF3` (bottom)
- Creates the feeling of looking up into an open sky

### Frosted Glass (Light)

- Cards use `backdrop-filter: blur(20px)` with `background: rgba(255, 255, 255, 0.8)`
- Borders: `1px solid rgba(255, 255, 255, 0.6)`
- Creates a "looking through clouds" effect on white, not dark

### Spotlight Cards

- White cards with a subtle radial gradient that follows the cursor
- On hover, a soft warm light (gold at 5% opacity) tracks the mouse position
- Creates a "sunlight breaking through clouds" effect

### Moving Border CTA

- The primary "Start Session" button has an animated gradient border
- A gold → teal → gold gradient orbits the button edge on a 4s loop
- Combined with soft gold outer glow on hover

### Status Orb

- Replaces the simple connection dot with an animated floating orb in the header
- **Active**: Soft teal glow with slow pulse
- **Warming**: Gold with expanding/contracting breathe animation
- **Error**: Coral with rapid flicker
- **Idle**: Mist gray, static

### Warmth Particles

- During the SageMaker warming overlay, gold particles slowly rise from bottom to top
- Overlay uses frosted white (not dark) to maintain the light aesthetic
