const GB = 1024 ** 3;

// A local model whose weights take more than this share of the PC's memory swaps and crawls (Gemma 4 26B, 17 GB, on a 15 GB PC:
// 2 tokens/s and a minute to load). Returns null when either number is unknown.
const TOO_BIG_SHARE = 0.6;

export function modelFit(sizeBytes: number | undefined, ramTotalGb: number | undefined) {
  if (!sizeBytes || !ramTotalGb) return null;
  const sizeGb = sizeBytes / GB;
  return { tooBig: sizeGb > ramTotalGb * TOO_BIG_SHARE, sizeGb, ramGb: ramTotalGb };
}
