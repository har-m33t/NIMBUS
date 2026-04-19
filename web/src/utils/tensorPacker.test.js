import { describe, expect, it } from "vitest";

import { packTensorInterleaved } from "./tensorPacker";

const FRAME_COUNT = 50;
const KEYPOINT_COUNT = 55;
const PACKED_TENSOR_SIZE = 5500;

function createFrameBuffer() {
  return Array.from({ length: FRAME_COUNT }, () =>
    Array.from({ length: KEYPOINT_COUNT }, () => ({ x: 0, y: 0 })),
  );
}

describe("packTensorInterleaved", () => {
  it("throws when fewer than 50 frames are provided", () => {
    const shortBuffer = Array.from({ length: FRAME_COUNT - 1 }, () => []);

    expect(() => packTensorInterleaved(shortBuffer)).toThrow(/Expected 50 frames/);
  });

  it("returns a Float32Array with the expected 5500 values", () => {
    const packed = packTensorInterleaved(createFrameBuffer());

    expect(packed).toBeInstanceOf(Float32Array);
    expect(packed.length).toBe(PACKED_TENSOR_SIZE);
  });

  it("interleaves keypoints first and frames second for the TGCN layout", () => {
    const buffer = createFrameBuffer();

    buffer[0][0] = { x: 1, y: 2 };
    buffer[1][0] = { x: 3, y: 4 };
    buffer[0][1] = { x: 9, y: 10 };

    const packed = packTensorInterleaved(buffer);

    expect(Array.from(packed.slice(0, 4))).toEqual([1, 2, 3, 4]);
    expect(Array.from(packed.slice(100, 102))).toEqual([9, 10]);
  });

  it("maps missing or off-screen keypoints to zero without crashing", () => {
    const buffer = createFrameBuffer();

    buffer[0][0] = { x: undefined, y: null };
    buffer[1][0] = { x: 5, y: undefined };
    buffer[2][0] = null;
    buffer[3][0] = undefined;

    const packed = packTensorInterleaved(buffer);

    expect(Array.from(packed.slice(0, 8))).toEqual([0, 0, 5, 0, 0, 0, 0, 0]);
    expect(packed.length).toBe(PACKED_TENSOR_SIZE);
  });
});
