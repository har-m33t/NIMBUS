# Edge Vision Pipeline (MediaPipe in Browser) — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a browser-native MediaPipe keypoint extractor in the React web client (`web/`) that reads from the user's webcam, produces a 55-point (x,y) skeleton ready for Phase 2 TGCN ONNX inference, and overlays the skeleton on the existing `VideoFeed` component.

**Architecture:** The existing `VideoFeed.tsx` owns a `<video>` element driven by `useLocalMedia` plus an empty `<canvas>` placeholder. Phase 1 replaces the placeholder with a real MediaPipe pipeline: two `tasks-vision` landmarkers (`PoseLandmarker` + `HandLandmarker`) run in `VIDEO` mode against the local `MediaStream`, a pure slicer reduces their output to the 55 (x,y) points the Phase 2 TGCN model expects, and a draw helper paints the skeleton onto the overlay canvas. The pipeline is owned by a new `useMediaPipeTracking` hook so future phases can subscribe to keypoints without touching the component tree. No backend calls are added in this phase.

**Tech Stack:** React 19, Vite, TypeScript (strict, `verbatimModuleSyntax: true`), `@mediapipe/tasks-vision` (CDN-hosted WASM + local `.task` model files), `vitest` + `jsdom` for unit tests.

---

## Scope boundary (read before starting)

- **In scope:** installing deps, slicer, tracking hook, skeleton overlay, `VideoFeed` refactor, tests for the pure slicer, wiring `isTracking` to the existing badge.
- **Out of scope:** ONNX model loading, TGCN inference, retiring SageMaker, sending `INFER` messages over WebSocket, face crop extraction, gloss-buffer flushing, any backend change. These belong to Phase 2+.
- **Architecture decision already made:** Browser ONNX inference is the target (see memory 32). The existing Python desktop extractor (`frontend/src/capture/mediapipe_extractor.py`) and the SageMaker endpoint are **not** modified; they remain the production path until Phase 2 proves browser ONNX accuracy. This plan only adds capability to the web frontend.
- **PROTOCOLS.md compatibility:** The existing `INFER` schema expects 21+21+33 `{x,y,z[,visibility]}` landmarks — **not** a 55-point 2D array. Because Phase 1 does not send anything upstream, there is no conflict. When Phase 2 wires ONNX→GLOSS, the hook will gain a second adapter that re-exports the full 3D landmarks for `INFER`. Today we expose a `rawLandmarks` object internally so a future adapter can reach it without re-running MediaPipe.
- **Model expectation:** TGCN wants **55 (x,y) points** = pose landmarks `0..12` (upper-body, 13 points) + left hand (21) + right hand (21). Confirmed with ML team.

---

## File structure

**Create**

- `web/src/lib/mediapipe/types.ts` — shared `Landmark2D`, `Landmark3D`, `Sliced55`, `RawLandmarks` types.
- `web/src/lib/mediapipe/slicer.ts` — pure `sliceTo55Points(pose, leftHand, rightHand)` function (no React, no DOM).
- `web/src/lib/mediapipe/__tests__/slicer.test.ts` — vitest unit tests.
- `web/src/lib/mediapipe/drawOverlay.ts` — pure `drawSkeleton(ctx, raw, mirrored)` helper.
- `web/src/lib/mediapipe/landmarkers.ts` — factory: `createLandmarkers()` returning `{ pose, hand, close }`.
- `web/src/hooks/useMediaPipeTracking.ts` — React hook that drives the per-frame loop at 10 FPS and returns `{ isTracking, keypoints55, rawLandmarks, lastUpdateMs }`.
- `web/vitest.config.ts` — vitest config (jsdom env, alias parity with `vite.config.ts`).
- `web/public/models/.gitkeep` — placeholder directory for `.task` files (files themselves are fetched at runtime from CDN in Phase 1; local hosting deferred to deployment hardening).

**Modify**

- `web/package.json` — add runtime dep `@mediapipe/tasks-vision`; add dev deps `vitest`, `jsdom`, `@types/jsdom`; add `"test"` and `"test:run"` scripts.
- `web/src/components/session/VideoFeed.tsx` — accept a new optional `enabled` prop, call `useMediaPipeTracking`, paint overlay on each frame, drive the existing `isTracking` badge from the hook rather than the `isTracking` prop.
- `web/src/pages/Session.tsx` — pass `enabled={aslEnabled}` to `<VideoFeed />` (the only live call site that should drive tracking) and drop the now-unused local `isTracking` prop value.

**Do not touch**

- `backend/**`, `frontend/**` (Python desktop), `infrastructure/**`, `PROTOCOLS.md`, anything under `web/src/hooks/useSessionSocket.ts` or `useWebRTC.ts`.

---

## Task 0: Pre-flight sanity check

**Files:**
- Read: `web/package.json`, `web/vite.config.ts`, `web/tsconfig.json`

- [ ] **Step 1: Confirm you are on a feature worktree, not `main` and not `infrastructure-and-signaling` directly**

Run: `git status && git branch --show-current`
Expected: branch name like `feat/edge-mediapipe-pipeline` (or whatever the executing agent created). If still on `infrastructure-and-signaling` or `main`, stop and create a new branch/worktree first — CLAUDE.md forbids direct `main` commits and this plan expects isolation.

- [ ] **Step 2: Confirm node toolchain**

Run: `node --version && npm --version`
Expected: node ≥ 18 (Vite 8 requires ≥ 18.17). If lower, stop and surface to the user.

- [ ] **Step 3: Baseline build**

Run: `cd web && npm install && npm run build`
Expected: build completes without errors. This is the baseline we must not regress.

---

## Task 1: Install dependencies and configure vitest

**Files:**
- Modify: `web/package.json`
- Create: `web/vitest.config.ts`

- [ ] **Step 1: Install MediaPipe runtime dependency**

Run (from `web/`):
```bash
npm install @mediapipe/tasks-vision@^0.10.22
```
Expected: `@mediapipe/tasks-vision` appears in `dependencies` in `web/package.json`.

- [ ] **Step 2: Install test toolchain**

Run (from `web/`):
```bash
npm install -D vitest@^3 jsdom@^25 @types/jsdom@^21
```
Expected: these appear in `devDependencies`.

- [ ] **Step 3: Add npm scripts**

Edit `web/package.json` `scripts` block to add:
```json
"test": "vitest",
"test:run": "vitest run"
```
Leave existing `dev`, `build`, `preview` untouched.

- [ ] **Step 4: Create vitest config**

Create `web/vitest.config.ts` with:
```ts
import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: false,
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
```

- [ ] **Step 5: Verify empty test run works**

Run (from `web/`): `npm run test:run`
Expected: exit code 0 with "No test files found" message (there are no tests yet). If it errors on config, fix and re-run.

- [ ] **Step 6: Commit**

```bash
git add web/package.json web/package-lock.json web/vitest.config.ts
git commit -m "chore(web): add @mediapipe/tasks-vision and vitest toolchain"
```

---

## Task 2: Type definitions

**Files:**
- Create: `web/src/lib/mediapipe/types.ts`

- [ ] **Step 1: Write the types file**

Create `web/src/lib/mediapipe/types.ts`:
```ts
export interface Landmark3D {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

export interface Landmark2D {
  x: number;
  y: number;
}

// Raw output of the two landmarkers for one video frame.
// `pose` is a single array of 33 landmarks (first person only).
// Hands are either the detected 21-landmark array or null when absent.
export interface RawLandmarks {
  pose: Landmark3D[] | null;
  leftHand: Landmark3D[] | null;
  rightHand: Landmark3D[] | null;
}

// Flat output consumed by the (future) TGCN model: exactly 55 (x,y) points.
export type Sliced55 = Landmark2D[] & { length: 55 };

export const SLICED_POSE_COUNT = 13; // indices 0..12 (upper body)
export const SLICED_HAND_COUNT = 21;
export const SLICED_TOTAL = SLICED_POSE_COUNT + SLICED_HAND_COUNT * 2; // 55
```

- [ ] **Step 2: Confirm TypeScript accepts the file**

Run (from `web/`): `npx tsc --noEmit`
Expected: no new errors in `src/lib/mediapipe/types.ts`.

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/mediapipe/types.ts
git commit -m "feat(web): add MediaPipe landmark type definitions"
```

---

## Task 3: Slicer — TDD

**Files:**
- Create: `web/src/lib/mediapipe/__tests__/slicer.test.ts`
- Create: `web/src/lib/mediapipe/slicer.ts`

- [ ] **Step 1: Write the failing test**

Create `web/src/lib/mediapipe/__tests__/slicer.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { sliceTo55Points } from "../slicer";
import type { Landmark3D, RawLandmarks } from "../types";

const mkPose = (): Landmark3D[] =>
  Array.from({ length: 33 }, (_, i) => ({ x: i / 100, y: i / 50, z: 0, visibility: 1 }));

const mkHand = (seed: number): Landmark3D[] =>
  Array.from({ length: 21 }, (_, i) => ({ x: seed + i / 100, y: seed + i / 50, z: 0 }));

const full = (): RawLandmarks => ({
  pose: mkPose(),
  leftHand: mkHand(0.1),
  rightHand: mkHand(0.5),
});

describe("sliceTo55Points", () => {
  it("always returns exactly 55 points", () => {
    expect(sliceTo55Points(full())).toHaveLength(55);
    expect(sliceTo55Points({ pose: null, leftHand: null, rightHand: null })).toHaveLength(55);
  });

  it("strips z and visibility, keeping only x and y", () => {
    const out = sliceTo55Points(full());
    for (const pt of out) {
      expect(Object.keys(pt).sort()).toEqual(["x", "y"]);
    }
  });

  it("takes exactly pose indices 0..12 for the first 13 points", () => {
    const raw = full();
    const out = sliceTo55Points(raw);
    for (let i = 0; i < 13; i++) {
      expect(out[i].x).toBe(raw.pose![i].x);
      expect(out[i].y).toBe(raw.pose![i].y);
    }
    // Index 13 must not equal pose[13] — it is the first left-hand point.
    expect(out[13].x).toBe(raw.leftHand![0].x);
  });

  it("places left hand at indices 13..33 and right hand at 34..54", () => {
    const raw = full();
    const out = sliceTo55Points(raw);
    for (let i = 0; i < 21; i++) {
      expect(out[13 + i].x).toBe(raw.leftHand![i].x);
      expect(out[34 + i].x).toBe(raw.rightHand![i].x);
    }
  });

  it("zero-fills a missing pose (13 zeros at the front)", () => {
    const out = sliceTo55Points({ ...full(), pose: null });
    for (let i = 0; i < 13; i++) {
      expect(out[i]).toEqual({ x: 0, y: 0 });
    }
  });

  it("zero-fills a missing left hand (21 zeros at 13..33)", () => {
    const out = sliceTo55Points({ ...full(), leftHand: null });
    for (let i = 13; i < 34; i++) {
      expect(out[i]).toEqual({ x: 0, y: 0 });
    }
  });

  it("zero-fills a missing right hand (21 zeros at 34..54)", () => {
    const out = sliceTo55Points({ ...full(), rightHand: null });
    for (let i = 34; i < 55; i++) {
      expect(out[i]).toEqual({ x: 0, y: 0 });
    }
  });

  it("zero-fills a pose shorter than 13 landmarks", () => {
    const shortPose = mkPose().slice(0, 7);
    const out = sliceTo55Points({ ...full(), pose: shortPose });
    for (let i = 0; i < 7; i++) {
      expect(out[i].x).toBe(shortPose[i].x);
    }
    for (let i = 7; i < 13; i++) {
      expect(out[i]).toEqual({ x: 0, y: 0 });
    }
  });
});
```

- [ ] **Step 2: Run the test to confirm it fails**

Run (from `web/`): `npm run test:run -- slicer`
Expected: failure — "Cannot find module '../slicer'" or equivalent.

- [ ] **Step 3: Write the minimal slicer**

Create `web/src/lib/mediapipe/slicer.ts`:
```ts
import type { Landmark2D, Landmark3D, RawLandmarks, Sliced55 } from "./types";
import { SLICED_HAND_COUNT, SLICED_POSE_COUNT, SLICED_TOTAL } from "./types";

const ZERO: Landmark2D = { x: 0, y: 0 };

function take2D(src: Landmark3D[] | null, count: number, offset = 0): Landmark2D[] {
  const out: Landmark2D[] = [];
  for (let i = 0; i < count; i++) {
    const lm = src?.[offset + i];
    out.push(lm ? { x: lm.x, y: lm.y } : { ...ZERO });
  }
  return out;
}

export function sliceTo55Points(raw: RawLandmarks): Sliced55 {
  const out: Landmark2D[] = [
    ...take2D(raw.pose, SLICED_POSE_COUNT),
    ...take2D(raw.leftHand, SLICED_HAND_COUNT),
    ...take2D(raw.rightHand, SLICED_HAND_COUNT),
  ];
  if (out.length !== SLICED_TOTAL) {
    throw new Error(`sliceTo55Points produced ${out.length} points, expected ${SLICED_TOTAL}`);
  }
  return out as Sliced55;
}
```

- [ ] **Step 4: Run the test to confirm it passes**

Run (from `web/`): `npm run test:run -- slicer`
Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/mediapipe/slicer.ts web/src/lib/mediapipe/__tests__/slicer.test.ts
git commit -m "feat(web): add 55-point MediaPipe slicer for TGCN input"
```

---

## Task 4: Landmarker factory

**Files:**
- Create: `web/src/lib/mediapipe/landmarkers.ts`

- [ ] **Step 1: Write the factory**

Create `web/src/lib/mediapipe/landmarkers.ts`:
```ts
import {
  FilesetResolver,
  HandLandmarker,
  PoseLandmarker,
} from "@mediapipe/tasks-vision";

// Published model URLs. If CDN availability becomes a concern, copy these
// .task files into web/public/models/ and point modelAssetPath at /models/<file>.
const WASM_URL =
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.22/wasm";
const POSE_MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task";
const HAND_MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task";

export interface Landmarkers {
  pose: PoseLandmarker;
  hand: HandLandmarker;
  close: () => void;
}

export async function createLandmarkers(): Promise<Landmarkers> {
  const fileset = await FilesetResolver.forVisionTasks(WASM_URL);

  const [pose, hand] = await Promise.all([
    PoseLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: POSE_MODEL_URL, delegate: "GPU" },
      runningMode: "VIDEO",
      numPoses: 1,
    }),
    HandLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: HAND_MODEL_URL, delegate: "GPU" },
      runningMode: "VIDEO",
      numHands: 2,
    }),
  ]);

  return {
    pose,
    hand,
    close: () => {
      pose.close();
      hand.close();
    },
  };
}
```

- [ ] **Step 2: TypeScript check**

Run (from `web/`): `npx tsc --noEmit`
Expected: no errors. If `@mediapipe/tasks-vision` types are missing, re-run `npm install` in `web/` and retry.

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/mediapipe/landmarkers.ts
git commit -m "feat(web): add MediaPipe landmarker factory (pose + hand, VIDEO mode)"
```

---

## Task 5: Skeleton overlay drawer

**Files:**
- Create: `web/src/lib/mediapipe/drawOverlay.ts`

Rationale: the drawer is pure (takes a canvas context + landmarks, draws), so it lives beside the slicer. Kept minimal — lines + dots. No animation, no colour theming yet.

- [ ] **Step 1: Write the drawer**

Create `web/src/lib/mediapipe/drawOverlay.ts`:
```ts
import type { Landmark3D, RawLandmarks } from "./types";

// MediaPipe hand connections (21-landmark topology).
const HAND_CONNECTIONS: Array<[number, number]> = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [0, 17], [17, 18], [18, 19], [19, 20],
];

// Upper-body pose connections (indices 0..12 only).
const POSE_UPPER_CONNECTIONS: Array<[number, number]> = [
  [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
  [11, 23], [12, 24], [11, 0], [12, 0],
].filter(([a, b]) => a <= 12 && b <= 12);

export interface DrawOptions {
  mirrored?: boolean; // true if the video is rendered with scaleX(-1)
  strokeStyle?: string;
  pointStyle?: string;
  lineWidth?: number;
  pointRadius?: number;
}

export function drawSkeleton(
  ctx: CanvasRenderingContext2D,
  raw: RawLandmarks,
  opts: DrawOptions = {},
): void {
  const {
    mirrored = true,
    strokeStyle = "#29E3C9",
    pointStyle = "#FFFFFF",
    lineWidth = 2,
    pointRadius = 3,
  } = opts;

  const { width: W, height: H } = ctx.canvas;
  ctx.clearRect(0, 0, W, H);

  ctx.save();
  if (mirrored) {
    ctx.translate(W, 0);
    ctx.scale(-1, 1);
  }
  ctx.lineWidth = lineWidth;
  ctx.strokeStyle = strokeStyle;
  ctx.fillStyle = pointStyle;

  const drawSet = (pts: Landmark3D[] | null, conns: Array<[number, number]>) => {
    if (!pts) return;
    ctx.beginPath();
    for (const [a, b] of conns) {
      const pa = pts[a];
      const pb = pts[b];
      if (!pa || !pb) continue;
      ctx.moveTo(pa.x * W, pa.y * H);
      ctx.lineTo(pb.x * W, pb.y * H);
    }
    ctx.stroke();
    for (const pt of pts) {
      ctx.beginPath();
      ctx.arc(pt.x * W, pt.y * H, pointRadius, 0, Math.PI * 2);
      ctx.fill();
    }
  };

  drawSet(raw.pose?.slice(0, 13) ?? null, POSE_UPPER_CONNECTIONS);
  drawSet(raw.leftHand, HAND_CONNECTIONS);
  drawSet(raw.rightHand, HAND_CONNECTIONS);

  ctx.restore();
}
```

- [ ] **Step 2: TypeScript check**

Run (from `web/`): `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/mediapipe/drawOverlay.ts
git commit -m "feat(web): add skeleton overlay drawer (upper body + hands)"
```

---

## Task 6: Tracking hook

**Files:**
- Create: `web/src/hooks/useMediaPipeTracking.ts`

The hook owns: landmarker lifecycle, the `requestVideoFrameCallback` / `requestAnimationFrame` loop, 10 FPS throttle, per-frame slicing, and `isTracking` derivation. It returns stable refs/state for the component.

- [ ] **Step 1: Write the hook**

Create `web/src/hooks/useMediaPipeTracking.ts`:
```ts
import { useEffect, useRef, useState } from "react";
import {
  createLandmarkers,
  type Landmarkers,
} from "../lib/mediapipe/landmarkers";
import { sliceTo55Points } from "../lib/mediapipe/slicer";
import type {
  Landmark3D,
  RawLandmarks,
  Sliced55,
} from "../lib/mediapipe/types";

export interface UseMediaPipeTrackingOptions {
  video: HTMLVideoElement | null;
  enabled: boolean;
  targetFps?: number; // defaults to 10 to match PROTOCOLS §3.1
}

export interface MediaPipeTrackingState {
  isTracking: boolean;
  keypoints55: Sliced55 | null;
  rawLandmarks: RawLandmarks | null;
  lastUpdateMs: number | null;
  error: string | null;
}

type NormalizedLandmark = { x: number; y: number; z: number; visibility?: number };
type HandedCategory = { categoryName?: string; displayName?: string };

function toLandmark3D(src: NormalizedLandmark[] | undefined): Landmark3D[] | null {
  if (!src || src.length === 0) return null;
  return src.map((p) => ({
    x: p.x,
    y: p.y,
    z: p.z,
    visibility: p.visibility,
  }));
}

// Hand landmarker returns up to `numHands` hands in detection order. Use the
// handedness label to route each result to left or right.
function partitionHands(
  landmarks: NormalizedLandmark[][] | undefined,
  handedness: HandedCategory[][] | undefined,
): { leftHand: Landmark3D[] | null; rightHand: Landmark3D[] | null } {
  let leftHand: Landmark3D[] | null = null;
  let rightHand: Landmark3D[] | null = null;
  if (!landmarks || !handedness) return { leftHand, rightHand };

  for (let i = 0; i < landmarks.length; i++) {
    const label = handedness[i]?.[0]?.categoryName ?? handedness[i]?.[0]?.displayName;
    const pts = toLandmark3D(landmarks[i]);
    if (!pts) continue;
    if (label === "Left") leftHand = pts;
    else if (label === "Right") rightHand = pts;
  }
  return { leftHand, rightHand };
}

export function useMediaPipeTracking({
  video,
  enabled,
  targetFps = 10,
}: UseMediaPipeTrackingOptions): MediaPipeTrackingState {
  const [state, setState] = useState<MediaPipeTrackingState>({
    isTracking: false,
    keypoints55: null,
    rawLandmarks: null,
    lastUpdateMs: null,
    error: null,
  });

  const landmarkersRef = useRef<Landmarkers | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastEmitRef = useRef<number>(0);
  const disposedRef = useRef(false);

  useEffect(() => {
    if (!enabled || !video) {
      setState((s) => ({ ...s, isTracking: false }));
      return;
    }

    disposedRef.current = false;
    const frameIntervalMs = 1000 / targetFps;

    async function boot() {
      try {
        const lm = await createLandmarkers();
        if (disposedRef.current) {
          lm.close();
          return;
        }
        landmarkersRef.current = lm;
        loop();
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setState((s) => ({ ...s, error: msg, isTracking: false }));
      }
    }

    function loop() {
      if (disposedRef.current) return;
      rafRef.current = requestAnimationFrame(loop);

      const lm = landmarkersRef.current;
      if (!lm || !video || video.readyState < 2) return;

      const now = performance.now();
      if (now - lastEmitRef.current < frameIntervalMs) return;
      lastEmitRef.current = now;

      const ts = Math.floor(now);
      const poseResult = lm.pose.detectForVideo(video, ts);
      const handResult = lm.hand.detectForVideo(video, ts);

      const pose = toLandmark3D(poseResult.landmarks?.[0]);
      const { leftHand, rightHand } = partitionHands(
        handResult.landmarks,
        handResult.handednesses,
      );

      const raw: RawLandmarks = { pose, leftHand, rightHand };
      const sliced = sliceTo55Points(raw);

      setState({
        isTracking: pose !== null || leftHand !== null || rightHand !== null,
        keypoints55: sliced,
        rawLandmarks: raw,
        lastUpdateMs: ts,
        error: null,
      });
    }

    boot();

    return () => {
      disposedRef.current = true;
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      landmarkersRef.current?.close();
      landmarkersRef.current = null;
      lastEmitRef.current = 0;
    };
  }, [enabled, video, targetFps]);

  return state;
}
```

- [ ] **Step 2: TypeScript check**

Run (from `web/`): `npx tsc --noEmit`
Expected: no errors. If the `tasks-vision` types surface different casing on `handednesses` (e.g. `handedness`), fix the field access and re-run. The SDK has used both over versions.

- [ ] **Step 3: Commit**

```bash
git add web/src/hooks/useMediaPipeTracking.ts
git commit -m "feat(web): add useMediaPipeTracking hook (10 FPS, pose + hands)"
```

---

## Task 7: Integrate hook into `VideoFeed`

**Files:**
- Modify: `web/src/components/session/VideoFeed.tsx`

Goal: drive the skeleton overlay and `isTracking` badge from the hook when `enabled` is true. The current `isTracking` prop becomes a manual override used only when tracking is disabled (so callers can still show "Waiting…" vs "Connected-but-idle" states without engaging MediaPipe).

- [ ] **Step 1: Rewrite `VideoFeed.tsx`**

Replace the full contents of `web/src/components/session/VideoFeed.tsx` with:
```tsx
import { useEffect, useRef } from "react";
import { useMediaPipeTracking } from "../../hooks/useMediaPipeTracking.ts";
import { drawSkeleton } from "../../lib/mediapipe/drawOverlay.ts";

export default function VideoFeed({
  stream = null,
  showOverlay = true,
  enabled = false,
  isTracking: isTrackingProp = false,
}: {
  stream?: MediaStream | null;
  showOverlay?: boolean;
  enabled?: boolean;
  isTracking?: boolean;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.srcObject = stream;
    }
  }, [stream]);

  const { isTracking, rawLandmarks, error } = useMediaPipeTracking({
    video: videoRef.current,
    enabled: enabled && !!stream,
  });

  // Paint the skeleton every time the hook emits new landmarks.
  useEffect(() => {
    const canvas = canvasRef.current;
    const video = videoRef.current;
    if (!canvas || !video || !rawLandmarks) return;

    // Keep the canvas backing store matched to the video's intrinsic size
    // so that landmark coords (normalized to the video frame) land correctly.
    const targetW = video.videoWidth || canvas.clientWidth;
    const targetH = video.videoHeight || canvas.clientHeight;
    if (canvas.width !== targetW) canvas.width = targetW;
    if (canvas.height !== targetH) canvas.height = targetH;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    drawSkeleton(ctx, rawLandmarks, { mirrored: true });
  }, [rawLandmarks]);

  // Clear the overlay when tracking turns off.
  useEffect(() => {
    if (enabled) return;
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (canvas && ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
  }, [enabled]);

  const badgeActive = enabled ? isTracking : isTrackingProp;

  return (
    <div className="relative w-full rounded-2xl overflow-hidden border border-nimbus-mist/10 bg-nimbus-elevated">
      <div className="relative w-full" style={{ paddingBottom: "56.25%" }}>
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className="absolute inset-0 w-full h-full object-cover"
          style={{ transform: "scaleX(-1)" }}
        />

        {showOverlay && (
          <canvas
            ref={canvasRef}
            className="absolute inset-0 w-full h-full pointer-events-none"
            aria-hidden="true"
          />
        )}

        <div className="absolute top-3 left-3">
          <div
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium backdrop-blur-sm ${
              badgeActive
                ? "bg-nimbus-teal/20 text-nimbus-teal border border-nimbus-teal/30"
                : "bg-nimbus-surface/60 text-nimbus-mist border border-nimbus-mist/20"
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${badgeActive ? "bg-nimbus-teal signal-pulse" : "bg-nimbus-mist"}`} />
            {badgeActive ? "Tracking" : enabled ? "Initializing…" : "Waiting…"}
          </div>
        </div>

        {showOverlay && (
          <div className="absolute top-3 right-3">
            <button
              className="p-1.5 rounded-lg bg-nimbus-surface/60 text-nimbus-mist hover:text-nimbus-text backdrop-blur-sm border border-nimbus-mist/20 transition-colors"
              title="Toggle skeleton overlay"
              aria-label="Toggle MediaPipe skeleton overlay"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
            </button>
          </div>
        )}

        {error && (
          <div className="absolute bottom-3 left-3 text-xs text-nimbus-coral bg-nimbus-surface/70 px-2 py-1 rounded-md backdrop-blur-sm">
            Tracking error: {error}
          </div>
        )}

        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background: "radial-gradient(ellipse at center, transparent 60%, rgba(15, 22, 41, 0.4) 100%)",
          }}
          aria-hidden="true"
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: TypeScript check**

Run (from `web/`): `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/session/VideoFeed.tsx
git commit -m "feat(web): wire VideoFeed to useMediaPipeTracking + canvas overlay"
```

---

## Task 8: Enable tracking from `Session.tsx`

**Files:**
- Modify: `web/src/pages/Session.tsx`

Only one call site needs updating — the `<VideoFeed …/>` rendered when `!hasRemote`. The inline local-PIP `<video>` under the `hasRemote` branch is left untouched (it is a thumbnail, not the tracked feed). Tracking engages when `aslEnabled` is true.

- [ ] **Step 1: Update the `<VideoFeed />` call**

In `web/src/pages/Session.tsx`, find the line:
```tsx
<VideoFeed stream={localStream} showOverlay={false} isTracking={!!localStream} />
```
and replace it with:
```tsx
<VideoFeed stream={localStream} showOverlay={aslEnabled} enabled={aslEnabled} />
```

Rationale: when ASL is off we don't run MediaPipe at all (cheaper + less camera heat). When ASL is on, overlay and tracker turn on together. `isTracking` is no longer passed; the component now computes it from the hook.

- [ ] **Step 2: TypeScript check**

Run (from `web/`): `npx tsc --noEmit`
Expected: no errors. If `noUnusedLocals` complains about something in `Session.tsx`, resolve inline.

- [ ] **Step 3: Commit**

```bash
git add web/src/pages/Session.tsx
git commit -m "feat(web): enable MediaPipe tracking when ASL toggle is on"
```

---

## Task 9: Build + manual smoke test

**Files:** none

- [ ] **Step 1: Production build**

Run (from `web/`): `npm run build`
Expected: build succeeds. `@mediapipe/tasks-vision` should NOT trigger a Vite "failed to resolve" error. If it does, check the `dependencies` entry in `package.json`.

- [ ] **Step 2: Unit tests pass**

Run (from `web/`): `npm run test:run`
Expected: 8/8 slicer tests pass.

- [ ] **Step 3: Dev server + manual verification**

Run (from `web/`): `npm run dev`
Open the URL in a Chromium-based browser, sign in, start a session.

Verify (write the result — pass/fail — next to each before checking the box):
- **Camera permission prompt appears**, and granting it shows live video (mirrored).
- With the ASL toggle **off**: no overlay is drawn, badge reads "Waiting…".
- Toggle ASL **on**: within ~2 seconds the badge flips to "Initializing…" → "Tracking", and a teal skeleton overlays the upper body + hands while you move.
- Turning ASL **off** again clears the overlay and stops the per-frame log (check DevTools Performance: CPU should drop back to idle).
- DevTools console shows **no** errors about MediaPipe WASM loading, CORS, or unresolved modules.
- Navigating away from `/session/:roomId` fully stops the camera (the existing `useLocalMedia` cleanup must still fire — verify the camera LED turns off).

- [ ] **Step 4: Document the result**

If all pass, proceed to Task 10. If anything fails, STOP, create a task describing the failure, and surface to the user before committing more work.

---

## Task 10: Handoff notes to Phase 2

**Files:**
- Modify: `docs/superpowers/plans/2026-04-18-edge-mediapipe-pipeline.md` (this file)

- [ ] **Step 1: Append the following section to the bottom of this plan**

```markdown
## Post-implementation handoff (Phase 2 kickoff notes)

- `useMediaPipeTracking` exposes `keypoints55` (ready for TGCN) and `rawLandmarks` (ready for PROTOCOLS-compatible `INFER` payloads if SageMaker is kept during transition).
- ONNX runtime + TGCN model will consume `keypoints55` at 10 FPS with the same timing as `lastUpdateMs`.
- The hand-partitioning by handedness label mirrors the video (`scaleX(-1)`); if Phase 2 needs camera-frame coordinates (not mirror coordinates), add a normalization step before ONNX input — the landmarks themselves are NOT mirrored by MediaPipe, only the displayed video is.
- Face crop capture (PROTOCOLS §3.2) is still unimplemented — belongs in Phase 3 (emotion pipeline) alongside `includeFaceCrop` gating.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-04-18-edge-mediapipe-pipeline.md
git commit -m "docs(plan): append Phase 2 handoff notes to edge-mediapipe plan"
```

---

## Self-review checklist (for the executing agent)

Before reporting the plan complete, confirm:

1. `npm run test:run` → 8/8 pass.
2. `npm run build` → clean, no warnings about unresolved MediaPipe deps.
3. `npx tsc --noEmit` → clean.
4. Manual smoke test (Task 9, Step 3) → all six checks pass.
5. No file in `backend/`, `frontend/`, `infrastructure/`, or `PROTOCOLS.md` was touched.
6. All commits are on a feature branch, not on `main` or `infrastructure-and-signaling`.

If any of the above fails, do not mark the plan complete — surface the specific failure to the user.

## Post-implementation handoff (Phase 2 kickoff notes)

- `useMediaPipeTracking` exposes `keypoints55` (ready for TGCN) and `rawLandmarks` (ready for PROTOCOLS-compatible `INFER` payloads if SageMaker is kept during transition).
- ONNX runtime + TGCN model will consume `keypoints55` at 10 FPS with the same timing as `lastUpdateMs`.
- The hand-partitioning by handedness label mirrors the video (`scaleX(-1)`); if Phase 2 needs camera-frame coordinates (not mirror coordinates), add a normalization step before ONNX input — the landmarks themselves are NOT mirrored by MediaPipe, only the displayed video is.
- Face crop capture (PROTOCOLS §3.2) is still unimplemented — belongs in Phase 3 (emotion pipeline) alongside `includeFaceCrop` gating.
