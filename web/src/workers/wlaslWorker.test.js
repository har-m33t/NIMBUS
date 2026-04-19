import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const INPUT_SHAPE = [1, 55, 100];
const INPUT_SIZE = INPUT_SHAPE[1] * INPUT_SHAPE[2];

const mockCreate = vi.fn();
const mockTensor = vi.fn(function MockTensor(type, data, dims) {
  this.type = type;
  this.data = data;
  this.dims = dims;
});
const mockEnv = {
  wasm: {
    proxy: true,
    numThreads: 4,
  },
};

vi.mock("onnxruntime-web", () => ({
  env: mockEnv,
  InferenceSession: {
    create: mockCreate,
  },
  Tensor: mockTensor,
}));

function createWorkerScope() {
  return {
    location: { origin: "http://localhost:5173" },
    onmessage: undefined,
    postMessage: vi.fn(),
  };
}

function createFetchResponse(labels) {
  return {
    ok: true,
    json: vi.fn().mockResolvedValue(labels),
  };
}

describe("wlaslWorker", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    mockEnv.wasm.proxy = true;
    mockEnv.wasm.numThreads = 4;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("runs inference, picks the argmax class, and maps it to a label", async () => {
    const labels = { "14": "WATER" };
    const output = Float32Array.from({ length: 15 }, (_, index) => (index === 14 ? 0.99 : 0.01));
    const run = vi.fn().mockResolvedValue({
      output: { data: output },
    });

    mockCreate.mockResolvedValue({
      inputNames: ["input"],
      outputNames: ["output"],
      run,
    });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(createFetchResponse(labels)));
    const workerScope = createWorkerScope();
    vi.stubGlobal("self", workerScope);

    await import("./wlaslWorker.js");

    const input = new Float32Array(INPUT_SIZE).fill(1);
    await workerScope.onmessage({ data: input });

    expect(mockEnv.wasm.proxy).toBe(false);
    expect(mockEnv.wasm.numThreads).toBe(1);
    expect(mockCreate).toHaveBeenCalledWith("http://localhost:5173/wlasl_asl100.onnx", {
      executionProviders: ["wasm"],
    });
    expect(mockTensor).toHaveBeenCalledWith("float32", input, INPUT_SHAPE);
    expect(run).toHaveBeenCalledTimes(1);
    expect(run.mock.calls[0][0].input.data).toBe(input);
    expect(run.mock.calls[0][0].input.dims).toEqual(INPUT_SHAPE);
    expect(workerScope.postMessage).toHaveBeenCalledWith("WATER");
  });

  it("returns an empty string when the incoming tensor length is invalid", async () => {
    const run = vi.fn();

    mockCreate.mockResolvedValue({
      inputNames: ["input"],
      outputNames: ["output"],
      run,
    });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(createFetchResponse({ "0": "IGNORED" })));
    const workerScope = createWorkerScope();
    vi.stubGlobal("self", workerScope);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    await import("./wlaslWorker.js");
    await workerScope.onmessage({ data: new Float32Array(INPUT_SIZE - 1) });

    expect(run).not.toHaveBeenCalled();
    expect(workerScope.postMessage).toHaveBeenCalledWith("");
    expect(consoleError).toHaveBeenCalled();
  });
});
