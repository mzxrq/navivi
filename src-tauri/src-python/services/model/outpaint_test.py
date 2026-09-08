import os
import torch
from PIL import Image, ImageFilter
from diffusers import AutoPipelineForInpainting

# Quick outpaint test: extend the source photo's left/right edges with
# AI-generated content so classic_pan.py has more real estate to pan across.
# One static-image generation (no temporal consistency needed), so it avoids
# the melting/drift problems we hit with LTX-Video entirely.

SRC_IMAGE = "narapark.jpg"
OUT_IMAGE = "output_videos/narapark_outpainted_test.png"

# Kept modest for a fast first look — bump WORK_W up and STEPS up once the
# framing/prompt look right.
WORK_W, WORK_H = 1024, 688          # divisible by 8
EXTEND_FRAC = 0.22                   # fraction of WORK_W added on each side (smaller = more reliable)
STEPS = 30
GUIDANCE = 7.0

PROMPT = (
    "outdoor photo of a stone-paved park walkway continuing into the distance, "
    "flanked by tall green trees on both sides, open sky above, natural daylight, "
    "wide-angle travel photography, same walkway continuing left and right, "
    "photorealistic, matching lighting and perspective of the original photo"
)
NEGATIVE_PROMPT = (
    "wall, door, doorway, pillar, column, wooden frame, indoor, interior, room, "
    "furniture, architecture close-up, building facade, seam, border, collage, "
    "watermark, text, blurry, distorted, different lighting, different style, low quality"
)


# [TODO] [Animation] Quick manual smoke-test script — hardcoded prompt/photo, no CLI args; superseded by outpaint_pan.py's describe_scene-driven prompt for real runs
def main():
    print("Loading SDXL inpainting pipeline...")
    pipe = AutoPipelineForInpainting.from_pretrained(
        "diffusers/stable-diffusion-xl-1.0-inpainting-0.1",
        torch_dtype=torch.bfloat16,
    )
    pipe.enable_model_cpu_offload()
    pipe.vae.enable_slicing()

    raw = Image.open(SRC_IMAGE).convert("RGB")
    src_aspect = raw.width / raw.height
    fit_h = WORK_H
    fit_w = int(fit_h * src_aspect)
    fitted = raw.resize((fit_w, fit_h))

    ext = int(WORK_W * EXTEND_FRAC)
    canvas_w = fit_w + ext * 2
    canvas_h = fit_h

    # [HACK] [Animation] Flat gray fill for the extension (unlike outpaint_pan.py's mirror-seed
    # approach) — this is the naive version that tends to hallucinate walls/pillars,
    # kept here as the baseline this test script was used to diagnose against.
    canvas = Image.new("RGB", (canvas_w, canvas_h), (128, 128, 128))
    canvas.paste(fitted, (ext, 0))

    # Mask: white = generate, black = keep as-is. Feather the seam so the
    # inpainting blends rather than showing a hard edge.
    mask = Image.new("L", (canvas_w, canvas_h), 255)
    mask.paste(Image.new("L", (fit_w, fit_h), 0), (ext, 0))
    mask = mask.filter(ImageFilter.GaussianBlur(radius=12))

    # Round to multiples of 8 for SDXL.
    canvas_w8 = (canvas_w // 8) * 8
    canvas_h8 = (canvas_h // 8) * 8
    canvas = canvas.resize((canvas_w8, canvas_h8))
    mask = mask.resize((canvas_w8, canvas_h8))

    print(f"Outpainting to {canvas_w8}x{canvas_h8} ({STEPS} steps)...")
    result = pipe(
        prompt=PROMPT,
        negative_prompt=NEGATIVE_PROMPT,
        image=canvas,
        mask_image=mask,
        width=canvas_w8,
        height=canvas_h8,
        num_inference_steps=STEPS,
        guidance_scale=GUIDANCE,
        strength=0.99,
    ).images[0]

    os.makedirs("output_videos", exist_ok=True)
    result.save(OUT_IMAGE)
    print(f"Saved {OUT_IMAGE}")


if __name__ == "__main__":
    main()
