const FRAME_COUNT = 50;
const KEYPOINT_COUNT = 55;
const VALUES_PER_KEYPOINT = 2;
const PACKED_TENSOR_SIZE = FRAME_COUNT * KEYPOINT_COUNT * VALUES_PER_KEYPOINT;

export function packTensorInterleaved(buffer) {
  if (!Array.isArray(buffer) || buffer.length !== FRAME_COUNT) {
    throw new Error(`Expected ${FRAME_COUNT} frames, received ${Array.isArray(buffer) ? buffer.length : "non-array"}.`);
  }

  const packed = new Float32Array(PACKED_TENSOR_SIZE);
  let offset = 0;

  for (let keypointIndex = 0; keypointIndex < KEYPOINT_COUNT; keypointIndex += 1) {
    for (let frameIndex = 0; frameIndex < FRAME_COUNT; frameIndex += 1) {
      const point = buffer[frameIndex]?.[keypointIndex];

      packed[offset] = Number.isFinite(point?.x) ? point.x : 0;
      packed[offset + 1] = Number.isFinite(point?.y) ? point.y : 0;
      offset += VALUES_PER_KEYPOINT;
    }
  }

  return packed;
}
