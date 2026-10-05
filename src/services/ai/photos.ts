// Stop photos can be several MB each; the online APIs cap an image (Anthropic at 5 MB) and bill by its size, and a script
// needs no more than a look at the place.
export const MAX_ONLINE_PHOTOS = 4;
const LONG_EDGE = 1280;
const QUALITY = 0.85;

// Never larger than `LONG_EDGE` px on the long side, as JPEG; null when it cannot be decoded.
export async function shrinkForUpload(bytes: Uint8Array): Promise<string | null> {
  try {
    const bitmap = await createImageBitmap(new Blob([bytes as BlobPart]));
    const scale = Math.min(1, LONG_EDGE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const jpeg = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", QUALITY));
    if (!jpeg) return null;
    const url = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(jpeg);
    });
    return url.slice(url.indexOf(",") + 1);
  } catch {
    return null;
  }
}
