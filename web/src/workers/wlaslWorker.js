import * as ort from "onnxruntime-web";

const MODEL_URL = new URL("/wlasl_asl100.onnx", self.location.origin).toString();
const LABELS_URL = new URL("/wlasl_labels.json", self.location.origin).toString();
const INPUT_SHAPE = [1, 55, 100];
const INPUT_SIZE = INPUT_SHAPE[1] * INPUT_SHAPE[2];

ort.env.wasm.proxy = false;
ort.env.wasm.numThreads = 1;

let runtimePromise;

async function loadLabels() {
  const response = await fetch(LABELS_URL);

  if (!response.ok) {
    throw new Error(`Failed to load WLASL labels: ${response.status} ${response.statusText}`);
  }

  return response.json();
}

async function initializeRuntime() {
  if (!runtimePromise) {
    runtimePromise = Promise.all([
      loadLabels(),
      ort.InferenceSession.create(MODEL_URL, {
        executionProviders: ["wasm"],
      }),
    ]).catch((error) => {
      runtimePromise = undefined;
      throw error;
    });
  }

  return runtimePromise;
}

function argmax(values) {
  if (!values.length) {
    throw new Error("Model output was empty.");
  }

  let maxIndex = 0;
  let maxValue = values[0];

  for (let index = 1; index < values.length; index += 1) {
    if (values[index] > maxValue) {
      maxValue = values[index];
      maxIndex = index;
    }
  }

  return maxIndex;
}

function resolveLabel(labels, predictedIndex) {
  return labels[predictedIndex] ?? labels[String(predictedIndex)] ?? "";
}

initializeRuntime().catch(() => {});

self.onmessage = async (event) => {
  try {
    const flatArray = event.data instanceof Float32Array ? event.data : new Float32Array(event.data);

    if (flatArray.length !== INPUT_SIZE) {
      throw new Error(`Expected input tensor length ${INPUT_SIZE}, received ${flatArray.length}.`);
    }

    const [labels, session] = await initializeRuntime();
    const inputName = session.inputNames[0];
    const outputName = session.outputNames[0];
    const inputTensor = new ort.Tensor("float32", flatArray, INPUT_SHAPE);
    const results = await session.run({ [inputName]: inputTensor });
    const predictedIndex = argmax(results[outputName].data);

    self.postMessage(resolveLabel(labels, predictedIndex));
  } catch (error) {
    console.error("WLASL worker inference failed.", error);
    self.postMessage("");
  }
};
