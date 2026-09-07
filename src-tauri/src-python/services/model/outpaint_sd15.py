import os
import torch
import numpy as np
from PIL import Image
from diffusers import StableDiffusionControlNetInpaintPipeline, ControlNetModel, DDIMScheduler

# Lighter outpaint alternative: SD1.5 + a purpose-built ControlNet-inpaint
# checkpoint, instead of RealVisXL (SDXL) + ControlNet-Union. SD1.5's UNet is
# ~3x smaller than SDXL's, so base+controlnet+VAE totals roughly 4-5GB rather
# than the ~9.5GB+ that made the SDXL ControlNet-Union combo unsafe on an 8GB
# card. Still gets real ControlNet-guided generation (not naive masked
# img2img), which should meaningfully reduce the "flat region reads as wall"
# bias the mirror-seed approach (outpaint_pan.py) works around by other means.
#
# Both the base model and the ControlNet here are official, standard diffusers
# checkpoints with an official pipeline class — no custom ported files needed
# (an earlier RealVisXL + ControlNet-Union port was tried and removed: it
# didn't fit 8GB in fp16, and quantizing it either corrupted the output
# (4-bit) or still OOM'd (8-bit)).

SRC_IMAGE = "kabutoyama.jpg"
OUTPAINT_IMAGE = "output_videos/outpainted.png"
WORK_H = 512                  # SD1.5's native training resolution
EXTEND_FRAC = 0.42
STEPS = 25
GUIDANCE = 7.5

# Caps PyTorch's own CUDA allocator so it raises a clean, catchable
# torch.cuda.OutOfMemoryError well before the point where the Windows WDDM
# driver would otherwise silently spill the overflow into slow/unstable
# shared system memory — that silent spillover (not a clean OOM) is what an
# earlier heavier pipeline hit, and is suspected in two unrelated system
# shutdowns. This trades "might silently destabilize the system" for "fails
# loudly and falls back" (see outpaint_safe below).
MEMORY_FRACTION = 0.82

NEGATIVE_PROMPT = (
    "wall, concrete wall, brick wall, building, building facade, door, pillar, "
    "column, indoor, interior, room, seam, border, collage, watermark, text, "
    "blurry, distorted, low quality"
)


def make_inpaint_condition(image: Image.Image, mask: Image.Image) -> torch.Tensor:
    """Standard preprocessing for lllyasviel/control_v11p_sd15_inpaint: the
    control image is the real photo with masked pixels set to -1 (not 0/black
    — that's a valid pixel value and would look like real dark content to the
    model)."""
    image_np = np.array(image.convert("RGB")).astype(np.float32) / 255.0
    mask_np = np.array(mask.convert("L")).astype(np.float32) / 255.0
    assert image_np.shape[:2] == mask_np.shape[:2]
    image_np[mask_np > 0.5] = -1.0
    image_np = np.expand_dims(image_np, 0).transpose(0, 3, 1, 2)
    return torch.from_numpy(image_np)


def outpaint_sd15(src_image: str) -> Image.Image:
    if torch.cuda.is_available():
        torch.cuda.set_per_process_memory_fraction(MEMORY_FRACTION, 0)

    raw = Image.open(src_image).convert("RGB")

    from outpaint_pan import describe_scene  # reuse the BLIP captioner
    prompt = describe_scene(raw) + ", high quality, photorealistic, seamless continuation of the scene"
    print(f"Outpaint prompt: {prompt}")

    src_aspect = raw.width / raw.height
    fit_h = WORK_H
    fit_w = (int(fit_h * src_aspect) // 8) * 8
    fitted = raw.resize((fit_w, fit_h), Image.LANCZOS)

    ext = max(8, (int(fit_w * EXTEND_FRAC) // 8) * 8)
    canvas_w = fit_w + ext * 2
    canvas_h = fit_h

    # Mirror-seed the extension (same reasoning as outpaint_pan.py: a flat
    # fill color reads as "wall" to the model) — still worth doing even with
    # ControlNet guidance, it's a cheap extra nudge toward real texture.
    fitted_np = np.array(fitted)
    left_ext = fitted_np[:, :ext][:, ::-1]
    right_ext = fitted_np[:, -ext:][:, ::-1]
    canvas_np = np.concatenate([left_ext, fitted_np, right_ext], axis=1)
    canvas = Image.fromarray(canvas_np)

    mask = Image.new("L", (canvas_w, canvas_h), 255)
    mask.paste(Image.new("L", (fit_w, fit_h), 0), (ext, 0))

    control_image = make_inpaint_condition(canvas, mask)

    print("Loading SD1.5 + ControlNet-inpaint...")
    controlnet = ControlNetModel.from_pretrained(
        "lllyasviel/control_v11p_sd15_inpaint", torch_dtype=torch.float16
    )
    pipe = StableDiffusionControlNetInpaintPipeline.from_pretrained(
        "runwayml/stable-diffusion-v1-5",
        controlnet=controlnet,
        torch_dtype=torch.float16,
        safety_checker=None,
    )
    pipe.scheduler = DDIMScheduler.from_config(pipe.scheduler.config)
    pipe.enable_model_cpu_offload()
    pipe.enable_attention_slicing()
    pipe.vae.enable_slicing()

    print(f"Outpainting (SD1.5+ControlNet) to {canvas_w}x{canvas_h} ({STEPS} steps)...")
    result = pipe(
        prompt=prompt,
        negative_prompt=NEGATIVE_PROMPT,
        image=canvas,
        mask_image=mask,
        control_image=control_image,
        num_inference_steps=STEPS,
        guidance_scale=GUIDANCE,
    ).images[0]

    del pipe, controlnet
    torch.cuda.empty_cache()

    result = result.convert("RGB").resize((canvas_w, canvas_h))
    os.makedirs("output_videos", exist_ok=True)
    result.save(OUTPAINT_IMAGE)
    print(f"Saved {OUTPAINT_IMAGE}")
    return result


def outpaint_safe(src_image: str) -> Image.Image:
    """Try the lighter SD1.5+ControlNet outpaint first; on any OOM or other
    failure, fall back to the confirmed-working SDXL mirror-seed approach
    (outpaint_pan.outpaint) rather than propagating the error."""
    try:
        return outpaint_sd15(src_image)
    except torch.cuda.OutOfMemoryError as e:
        print(f"SD1.5 outpaint hit OOM ({e}) — falling back to the SDXL mirror-seed approach.")
    except Exception as e:
        print(f"SD1.5 outpaint failed ({type(e).__name__}: {e}) — falling back to the SDXL mirror-seed approach.")
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.set_per_process_memory_fraction(1.0, 0)  # release the cap for the fallback pipeline
    from outpaint_pan import outpaint as outpaint_fallback
    return outpaint_fallback(src_image)


if __name__ == "__main__":
    outpaint_safe(SRC_IMAGE)
