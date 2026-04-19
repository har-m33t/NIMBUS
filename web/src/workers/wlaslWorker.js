import * as ort from "onnxruntime-web";

const MODEL_URL = new URL("/asl_alphabet.onnx", self.location.origin).toString();
const INPUT_SHAPE = [1, 42];
const INPUT_SIZE = 42;
const CONFIDENCE_THRESHOLD = 0.4;
const TOP_K = 3;

// Inline A–Z labels to avoid a network fetch that fails on SPA fallback routes
const LABELS = {
  0:"A",1:"B",2:"C",3:"D",4:"E",5:"F",6:"G",7:"H",8:"I",9:"J",
  10:"K",11:"L",12:"M",13:"N",14:"O",15:"P",16:"Q",17:"R",18:"S",
  19:"T",20:"U",21:"V",22:"W",23:"X",24:"Y",25:"Z"
};

ort.env.wasm.wasmPaths = new URL("/", self.location.origin).toString();
ort.env.wasm.proxy = false;
ort.env.wasm.numThreads = 1;

let runtimePromise;

async function initializeRuntime() {
  if (!runtimePromise) {
    runtimePromise = ort.InferenceSession.create(MODEL_URL, {
      executionProviders: ["wasm"],
    }).then((session) => [LABELS, session])
    .catch((error) => {
      runtimePromise = undefined;
      throw error;
    });
  }

  return runtimePromise;
}

function softmax(logits) {
  let max = -Infinity;
  for (let i = 0; i < logits.length; i++) {
    if (logits[i] > max) max = logits[i];
  }
  const exps = new Float32Array(logits.length);
  let sum = 0;
  for (let i = 0; i < logits.length; i++) {
    exps[i] = Math.exp(logits[i] - max);
    sum += exps[i];
  }
  for (let i = 0; i < exps.length; i++) {
    exps[i] /= sum;
  }
  return exps;
}

function topK(probs, labels, k) {
  const indexed = Array.from(probs, (p, i) => ({ i, p }));
  indexed.sort((a, b) => b.p - a.p);
  return indexed.slice(0, k).map(({ i, p }) => ({
    label: resolveLabel(labels, i),
    confidence: p,
  }));
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
    const logits = results[outputName].data;
    const probs = softmax(logits);
    const top3 = topK(probs, labels, TOP_K);

    // Gate: only emit a token when the model is confident enough
    const best = top3[0];
    self.postMessage({
      token: best.confidence >= CONFIDENCE_THRESHOLD ? best.label : "",
      top3,
    });
  } catch (error) {
    console.error("WLASL worker inference failed.", error);
    self.postMessage({ token: "", top3: [] });
  }
};
