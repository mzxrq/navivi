import { t } from "@lingui/core/macro";

export interface SystemHardwareInfo {
  isHighSpec: boolean;
  gpuRenderer: string;
  hasDedicatedGpu: boolean;
  logicalCores: number;
  deviceMemoryGb?: number;
  details: string;
}

// ─── Module-level singleton ────────────────────────────────────────────────────
// We detect the GPU renderer exactly ONCE by creating a temporary WebGL canvas.
// Re-detecting on every React render would exhaust the browser's WebGL context
// limit (~16), evicting the Mapbox context and causing the cascade of
// "INVALID_OPERATION: object does not belong to this context" errors.
let _cachedAutoResult: Omit<SystemHardwareInfo, "details"> | null = null;

function getAutoHardwareInfo(): Omit<SystemHardwareInfo, "details"> {
  if (_cachedAutoResult) return _cachedAutoResult;

  let gpuRenderer = "Unknown GPU";
  const logicalCores = navigator.hardwareConcurrency || 4;
  const deviceMemoryGb: number | undefined = (navigator as any).deviceMemory;

  try {
    const canvas = document.createElement("canvas");
    // Request a low-power context so we don't steal a high-performance slot
    const gl =
      (canvas.getContext("webgl", { powerPreference: "low-power" }) as WebGLRenderingContext | null) ||
      (canvas.getContext("experimental-webgl", { powerPreference: "low-power" }) as WebGLRenderingContext | null);
    if (gl) {
      const ext = gl.getExtension("WEBGL_debug_renderer_info");
      if (ext) {
        gpuRenderer = gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || "Unknown GPU";
      }
      // Immediately lose the context so the browser reclaims it.
      const loseCtx = gl.getExtension("WEBGL_lose_context");
      loseCtx?.loseContext();
    }
    // Detach from the DOM (it was never attached, but this signals GC intent)
    canvas.width = 0;
    canvas.height = 0;
  } catch (e) {
    console.warn("Could not query WebGL renderer info:", e);
  }

  const lowerGpu = gpuRenderer.toLowerCase();

  // Integrated / APU / software renderers (Low-Spec)
  // Note: AMD Ryzen APUs with "Radeon Graphics" (e.g. Ryzen 5 5600GE) fall here
  const isIntegratedGpu =
    lowerGpu.includes("radeon graphics") ||
    lowerGpu.includes("radeon(tm) graphics") ||
    lowerGpu.includes("intel") ||
    lowerGpu.includes("uhd") ||
    lowerGpu.includes("hd graphics") ||
    lowerGpu.includes("iris") ||
    lowerGpu.includes("microsoft basic render") ||
    lowerGpu.includes("llvmpipe") ||
    lowerGpu.includes("swiftshader") ||
    lowerGpu.includes("mesa");

  // Dedicated GPUs (High-Spec)
  const hasDedicatedIdentifier =
    lowerGpu.includes("geforce") ||
    lowerGpu.includes("nvidia") ||
    lowerGpu.includes("rtx") ||
    lowerGpu.includes("gtx") ||
    lowerGpu.includes("radeon rx") ||
    lowerGpu.includes("radeon pro") ||
    lowerGpu.includes("quadro") ||
    lowerGpu.includes("arc a") ||
    lowerGpu.includes("apple m1 max") ||
    lowerGpu.includes("apple m2 max") ||
    lowerGpu.includes("apple m3 max") ||
    lowerGpu.includes("apple m4 max") ||
    lowerGpu.includes("apple m1 pro") ||
    lowerGpu.includes("apple m2 pro") ||
    lowerGpu.includes("apple m3 pro");

  const hasDedicatedGpu = hasDedicatedIdentifier && !isIntegratedGpu;

  // A system is considered High-Spec if it has a confirmed dedicated GPU
  // or very high physical memory and 12+ cores when renderer info is generic.
  const isHighSpec =
    hasDedicatedGpu ||
    (!isIntegratedGpu &&
      logicalCores >= 12 &&
      (deviceMemoryGb ? deviceMemoryGb >= 32 : false));

  _cachedAutoResult = {
    isHighSpec,
    gpuRenderer,
    hasDedicatedGpu,
    logicalCores,
    deviceMemoryGb,
  };

  return _cachedAutoResult;
}

export function detectHardwareSpec(
  override?: "auto" | "high" | "low"
): SystemHardwareInfo {
  if (override === "high") {
    return {
      isHighSpec: true,
      gpuRenderer: "Manual Override (High-Spec)",
      hasDedicatedGpu: true,
      logicalCores: navigator.hardwareConcurrency || 8,
      details: "Hardware spec manually overridden to High-Spec",
    };
  }
  if (override === "low") {
    return {
      isHighSpec: false,
      gpuRenderer: "Manual Override (Low-Spec)",
      hasDedicatedGpu: false,
      logicalCores: navigator.hardwareConcurrency || 4,
      details: "Hardware spec manually overridden to Low-Spec",
    };
  }

  const { isHighSpec, gpuRenderer, hasDedicatedGpu, logicalCores, deviceMemoryGb } =
    getAutoHardwareInfo();

  const details = isHighSpec
    ? t`High-spec system detected: ${gpuRenderer} (${logicalCores} CPU threads)`
    : t`Low-spec system detected: ${gpuRenderer} (Integrated graphics / no discrete GPU, ${logicalCores} CPU threads)`;

  return { isHighSpec, gpuRenderer, hasDedicatedGpu, logicalCores, deviceMemoryGb, details };
}
