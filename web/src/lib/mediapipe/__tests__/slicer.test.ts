import { describe, it, expect } from "vitest";
import { normalizeHandLandmarks } from "../slicer";
import type { Landmark3D, RawLandmarks } from "../types";

const mkHand = (seed: number): Landmark3D[] =>
  Array.from({ length: 21 }, (_, i) => ({ x: seed + i / 100, y: seed + i / 50, z: 0 }));

describe("normalizeHandLandmarks", () => {
  it("always returns exactly 21 points", () => {
    expect(normalizeHandLandmarks({ hand: mkHand(0.3) })).toHaveLength(21);
    expect(normalizeHandLandmarks({ hand: null })).toHaveLength(21);
  });

  it("strips z, keeping only x and y", () => {
    const out = normalizeHandLandmarks({ hand: mkHand(0.3) });
    for (const pt of out) {
      expect(Object.keys(pt).sort()).toEqual(["x", "y"]);
    }
  });

  it("centers on wrist (landmark 0 is at origin after normalization)", () => {
    const out = normalizeHandLandmarks({ hand: mkHand(0.3) });
    expect(out[0].x).toBeCloseTo(0, 10);
    expect(out[0].y).toBeCloseTo(0, 10);
  });

  it("scales by bounding-box diagonal", () => {
    const hand = mkHand(0.3);
    const raw: RawLandmarks = { hand };

    const wristX = hand[0].x;
    const wristY = hand[0].y;
    const centered = hand.map((p) => ({ x: p.x - wristX, y: p.y - wristY }));
    const xs = centered.map((p) => p.x);
    const ys = centered.map((p) => p.y);
    const xRange = Math.max(...xs) - Math.min(...xs);
    const yRange = Math.max(...ys) - Math.min(...ys);
    const diag = Math.sqrt(xRange * xRange + yRange * yRange);

    const out = normalizeHandLandmarks(raw);
    for (let i = 0; i < 21; i++) {
      expect(out[i].x).toBeCloseTo(centered[i].x / diag, 10);
      expect(out[i].y).toBeCloseTo(centered[i].y / diag, 10);
    }
  });

  it("returns zeros when hand is null", () => {
    const out = normalizeHandLandmarks({ hand: null });
    for (let i = 0; i < 21; i++) {
      expect(out[i]).toEqual({ x: 0, y: 0 });
    }
  });

  it("skips normalization when wrist is at origin (all zeros)", () => {
    const zeroHand: Landmark3D[] = Array.from({ length: 21 }, () => ({ x: 0, y: 0, z: 0 }));
    const out = normalizeHandLandmarks({ hand: zeroHand });
    for (let i = 0; i < 21; i++) {
      expect(out[i]).toEqual({ x: 0, y: 0 });
    }
  });
});
