import os
import torch
import cv2
import numpy as np
from PIL import Image, ImageFilter
from diffusers import AutoPipelineForInpainting
from transformers import BlipForConditionalGeneration, BlipProcessor

# Full pipeline: outpaint a source photo's left/right edges with an AI image
# model (one static generation, no temporal-consistency risk), then pan a
# crop window across the widened result.
#
# Uses a generic SDXL inpainting checkpoint (not a purpose-built outpainting
# pipeline) — a RealVisXL + ControlNet-Union port was tried and reverted:
# even a tiny 512x384/4-step smoke test peaked at 9.5GB VRAM (UNet ~5GB +
# ControlNet-Union ~2.4GB must both be resident every denoising step, which
# enable_model_cpu_offload can't reduce), and enable_sequential_cpu_offload
# crashed on a custom attention layer in that ControlNet's ported code. This
# approach comfortably fits 8GB and is the confirmed-working one.

# --- Outpaint settings ---
SRC_IMAGE = "kabutoyama.jpg"
OUTPAINT_IMAGE = "output_videos/outpainted.png"
WORK_H = 688                  # working height for the outpaint model (divisible by 8)
# Extension can be asymmetric — a side with a complex man-made object near
# the edge (a vehicle, a person, architecture) gives the model a bad "seed"
# to mirror/extend from and tends to produce a mangled duplicate; a side
# that's just open scenery (sky, trees, track, ground) extends cleanly. Put
# more of the budget on whichever side is actually extendable per-photo.
EXTEND_LEFT_FRAC = 0.42
EXTEND_RIGHT_FRAC = 0.42
# For a photo where the dominant subject is a complex man-made object near an
# edge (a vehicle especially), outpainting tends to fabricate MORE of that
# subject rather than just extending the background around it, on whichever
# side gets meaningful room — reducing or moving the extension doesn't fix
# this, it just moves where the duplicate appears. kyoushieki.jpg (a train
# station photo) hit this; classic_pan.py (no AI extension) is the better
# tool for that kind of photo.
STEPS = 40
GUIDANCE = 8.0
# Neither a bigger negative prompt nor guidance_scale=12 stopped this model
# from inventing flanking walls for a symmetric monument/statue photo — a
# flat-gray seed in the masked region reads as "wall" regardless of text
# conditioning. STRENGTH<1.0 makes the model actually respect the mirrored
# real content now seeded into that region (see `outpaint`) instead of
# generating from scratch; 1.0 would ignore the seed entirely.
STRENGTH = 0.75
MASK_FEATHER_PX = 12          # fixed feather radius — a wide feather (proportional to extend width)
                               # leaks too much gray into the edge and the model reads that as flat pillars

# The prompt is auto-generated per photo (see describe_scene) rather than
# hardcoded — a fixed prompt written for one photo makes the model hallucinate
# that OTHER scene's content when extending a different photo. CAPTION_SUFFIX
# is appended to whatever the captioning model sees; it's generic across any
# photo, not scene-specific.
CAPTION_SUFFIX = (
    ", open sky, natural daylight, wide-angle travel photography, the same scene "
    "continuing seamlessly to the left and right, photorealistic, matching lighting "
    "and perspective of the original photo"
)
# Kept broadly anti-architecture since outdoor photos are the common case here
# and the base model has a persistent bias toward inventing walls/buildings at
# the edges of an outpaint regardless of prompt wording — this negative prompt
# is what actually suppresses that, more than prompt wording alone.
NEGATIVE_PROMPT = (
    "wall, concrete wall, stone wall, brick wall, building, building facade, "
    "door, doorway, pillar, column, wooden frame, indoor, interior, room, "
    "furniture, architecture close-up, museum wall, gallery wall, "
    "duplicate object, duplicate vehicle, second train, extra train, "
    "disconnected object, floating debris, malformed, deformed, mangled, "
    "seam, border, collage, watermark, text, blurry, distorted, "
    "different lighting, different style, low quality"
)


# [Core] [Translation] Auto-captions the source photo (BLIP) so the outpaint prompt is grounded in its actual content
def describe_scene(pil_img: Image.Image) -> str:
    """One-shot image captioning (BLIP) so the outpaint prompt is grounded in
    whatever is actually in THIS photo, instead of a hand-written prompt that
    silently goes stale the moment SRC_IMAGE changes."""
    print("Captioning source photo...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
    model = BlipForConditionalGeneration.from_pretrained(
        "Salesforce/blip-image-captioning-base"
    ).to(device)

    inputs = processor(pil_img, return_tensors="pt").to(device)
    out = model.generate(**inputs, max_new_tokens=40)
    caption = processor.decode(out[0], skip_special_tokens=True).strip()
    print(f"Caption: {caption}")

    del model, processor
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return caption

# --- Pan settings ---
OUT_VIDEO = "output_videos/outpaint_pan.mp4"
OUT_W, OUT_H = 1280, 720
DURATION_SEC = 7.0
FPS = 30
EASE = True
ZOOM = 1.0                     # 1.0 = no crop-in; pan uses only the extra outpainted width


# [Core] [Animation] Runs the SDXL inpainting pipeline to widen the source photo's canvas for panning across
def outpaint(src_image: str) -> Image.Image:
    raw = Image.open(src_image).convert("RGB")

    prompt = describe_scene(raw) + CAPTION_SUFFIX
    print(f"Outpaint prompt: {prompt}")

    print("Loading SDXL inpainting pipeline...")
    pipe = AutoPipelineForInpainting.from_pretrained(
        "diffusers/stable-diffusion-xl-1.0-inpainting-0.1",
        torch_dtype=torch.bfloat16,
    )
    pipe.enable_model_cpu_offload()
    pipe.vae.enable_slicing()

    src_aspect = raw.width / raw.height
    fit_h = WORK_H
    fit_w = int(fit_h * src_aspect)
    fitted = raw.resize((fit_w, fit_h))

    ext_l = int(fit_w * EXTEND_LEFT_FRAC)
    ext_r = int(fit_w * EXTEND_RIGHT_FRAC)
    canvas_w = fit_w + ext_l + ext_r
    canvas_h = fit_h

    # [HACK] [Animation] Seed the extension area with mirrored real content instead of flat
    # gray. A large flat-colored rectangle reads as a "wall" to the diffusion
    # model regardless of prompt/negative-prompt/guidance — that's what was
    # producing pillar hallucinations even at very high guidance_scale. A
    # mirrored edge at least starts the model from real texture (trees) to
    # blend/complete rather than invent from scratch.
    fitted_np = np.array(fitted)
    parts = []
    if ext_l > 0:
        parts.append(fitted_np[:, :ext_l][:, ::-1])
    parts.append(fitted_np)
    if ext_r > 0:
        parts.append(fitted_np[:, -ext_r:][:, ::-1])
    canvas_np = np.concatenate(parts, axis=1)
    canvas = Image.fromarray(canvas_np)

    # [NOTE] [Animation] Mask: white = generate, black = keep as-is. A fixed (not extend-width-
    # proportional) feather radius gives the model a gradual transition band
    # instead of a hard edge.
    mask = Image.new("L", (canvas_w, canvas_h), 255)
    mask.paste(Image.new("L", (fit_w, fit_h), 0), (ext_l, 0))
    mask = mask.filter(ImageFilter.GaussianBlur(radius=MASK_FEATHER_PX))

    canvas_w8 = (canvas_w // 8) * 8
    canvas_h8 = (canvas_h // 8) * 8
    canvas = canvas.resize((canvas_w8, canvas_h8))
    mask = mask.resize((canvas_w8, canvas_h8))

    print(f"Outpainting to {canvas_w8}x{canvas_h8} ({STEPS} steps)...")
    result = pipe(
        prompt=prompt,
        negative_prompt=NEGATIVE_PROMPT,
        image=canvas,
        mask_image=mask,
        width=canvas_w8,
        height=canvas_h8,
        num_inference_steps=STEPS,
        guidance_scale=GUIDANCE,
        strength=STRENGTH,
    ).images[0]

    del pipe
    torch.cuda.empty_cache()

    os.makedirs("output_videos", exist_ok=True)
    result.save(OUTPAINT_IMAGE)
    print(f"Saved {OUTPAINT_IMAGE}")
    return result


def ease_in_out(t: float) -> float:
    return 0.5 - 0.5 * np.cos(np.pi * t)


# [Core] [Animation] Pans a crop window across the outpainted, widened image and encodes it to video
def pan(image: Image.Image) -> None:
    src = np.array(image.convert("RGB"))
    sh, sw = src.shape[:2]
    out_aspect = OUT_W / OUT_H

    if sw / sh > out_aspect:
        fit_h = sh
        fit_w = int(fit_h * out_aspect)
    else:
        fit_w = sw
        fit_h = int(fit_w / out_aspect)

    win_w = max(1, int(fit_w * ZOOM))
    win_h = max(1, int(fit_h * ZOOM))

    max_x = sw - win_w
    max_y = sh - win_h
    pan_axis = "x" if max_x >= max_y else "y"
    if max_x <= 0 and max_y <= 0:
        print("No room to pan at this ZOOM — output will be a static shot.")

    num_frames = int(DURATION_SEC * FPS)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(OUT_VIDEO, fourcc, FPS, (OUT_W, OUT_H))

    for i in range(num_frames):
        t = i / max(1, num_frames - 1)
        if EASE:
            t = ease_in_out(t)

        if pan_axis == "x":
            x0 = int(max_x * t)
            y0 = max_y // 2
        else:
            x0 = max_x // 2
            y0 = int(max_y * t)

        crop = src[y0:y0 + win_h, x0:x0 + win_w]
        frame = cv2.resize(crop, (OUT_W, OUT_H), interpolation=cv2.INTER_LANCZOS4)
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        writer.write(frame_bgr)

    writer.release()
    print(f"Saved {num_frames} frames to {OUT_VIDEO}")


if __name__ == "__main__":
    outpainted = outpaint(SRC_IMAGE)
    pan(outpainted)
