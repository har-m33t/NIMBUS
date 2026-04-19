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
