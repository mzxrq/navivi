// The models and engines Navivi can download for the user. Licenses are the ones on each model's Hugging Face / GitHub page (checked 2026-10-06).
// Shown in Settings > Setup next to the thing being installed and under Settings > About.
export interface ModelCredit {
  id: "kokoro" | "qwen3" | "irodori" | "wan" | "ltx" | "comfyui";
  name: string;
  by: string;
  license: string;
  url: string;
}

export const MODEL_CREDITS: Record<ModelCredit["id"], ModelCredit> = {
  kokoro: { id: "kokoro", name: "Kokoro-82M", by: "hexgrad", license: "Apache-2.0", url: "https://huggingface.co/hexgrad/Kokoro-82M" },
  qwen3: { id: "qwen3", name: "Qwen3-TTS 0.6B", by: "Alibaba Qwen team", license: "Apache-2.0", url: "https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base" },
  irodori: { id: "irodori", name: "Irodori-TTS v4 Small", by: "Aratako", license: "MIT", url: "https://huggingface.co/Aratako/Irodori-TTS-v4-Small" },
  wan: { id: "wan", name: "Wan 2.2 TI2V 5B Turbo (GGUF)", by: "Alibaba Wan-AI, quanhaol, hum-ma", license: "Apache-2.0", url: "https://huggingface.co/hum-ma/Wan2.2-TI2V-5B-Turbo-GGUF" },
  ltx: { id: "ltx", name: "LTX-Video 13B distilled (GGUF)", by: "Lightricks, QuantStack", license: "LTX-Video license", url: "https://huggingface.co/Lightricks/LTX-Video-0.9.8-13B-distilled" },
  comfyui: { id: "comfyui", name: "ComfyUI", by: "comfyanonymous and contributors", license: "GPL-3.0", url: "https://github.com/comfyanonymous/ComfyUI" },
};

export const creditLine = (id: ModelCredit["id"]) => `${MODEL_CREDITS[id].name} · ${MODEL_CREDITS[id].by} · ${MODEL_CREDITS[id].license}`;
