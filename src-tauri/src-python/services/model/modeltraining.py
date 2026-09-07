import os
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch

# Nightly PyTorch on Blackwell (RTX 50-series, sm_120) has known flash/mem-efficient
# SDPA kernel bugs that corrupt hidden states over long sequences, producing a
# "clean first frame -> melting/rippling" collapse. Force the safe math kernel.
torch.backends.cuda.enable_flash_sdp(False)
torch.backends.cuda.enable_mem_efficient_sdp(False)
torch.backends.cuda.enable_math_sdp(True)

from PIL import Image
from diffusers import LTXImageToVideoPipeline
from diffusers.utils import export_to_video

print("Loading official LTX-Video pipeline...")

# 1. Load the official 2B model in bfloat16
pipe = LTXImageToVideoPipeline.from_pretrained(
    "Lightricks/LTX-Video-0.9.5",
    torch_dtype=torch.bfloat16
)

# 2. Enable 8GB VRAM memory management
# NOTE: vae.enable_tiling() causes a "melting chrome" temporal artifact on LTX-Video
# once there is real motion (tile boundaries lose frame-to-frame consistency).
# enable_slicing() is memory-safe without that failure mode.
pipe.enable_model_cpu_offload()
pipe.vae.enable_slicing()

# 3. Pre-crop starting image to the target aspect ratio (no stretching), then
#    zoom in slightly and shift left so the camera has room to reveal the right side.
TARGET_W, TARGET_H = 704, 416
TARGET_ASPECT = TARGET_W / TARGET_H

raw_img = Image.open("narapark.jpg").convert("RGB")
w, h = raw_img.size

# First crop the source to the target aspect ratio without distortion.
if w / h > TARGET_ASPECT:
    new_w = int(h * TARGET_ASPECT)
    x0 = (w - new_w) // 2
    fitted = raw_img.crop((x0, 0, x0 + new_w, h))
else:
    new_h = int(w / TARGET_ASPECT)
    y0 = (h - new_h) // 2
    fitted = raw_img.crop((0, y0, w, y0 + new_h))

# Zoom in to ~80% width, biased to the left, to leave room for a rightward pan.
fw, fh = fitted.size
zoom_w = int(fw * 0.80)
cropped_img = fitted.crop((0, 0, zoom_w, fh))

# Resize to pipeline dimensions (must be divisible by 32) — aspect is already correct.
input_image = cropped_img.resize((TARGET_W, TARGET_H))

prompt = (
    "A smooth continuous rightward camera pan across a landscape. "
    "The camera physically moves and sweeps horizontally, continuously revealing new background "
    "on the right side of the frame as it travels. Fluid dynamic motion throughout the entire video, "
    "cinematic tracking shot."
)
negative_prompt = (
    "static, still image, still frame, frozen, no motion, no movement, motionless, "
    "stationary camera, paused, freeze frame, morphing, distorted, low quality"
)

print("Generating video in chunks... Please wait.")

# 4. Chunked ("sliding window") generation.
# Generating all 81 frames in a single call keeps the full temporal latent tensor
# resident in memory for the whole denoising loop, which is what overloads an 8GB
# card. Instead generate short segments and feed each segment's last frame back in
# as the next segment's starting image — this caps peak VRAM per step regardless of
# total video length, and a per-chunk OOM only costs that chunk, not the whole run.
TOTAL_FRAMES = 81          # ~3.3s at 24fps — must be 8n+1
FRAMES_PER_CHUNK = 25       # 8n+1; lower this further if you still see OOM
NUM_INFERENCE_STEPS = 50
GUIDANCE_SCALE = 3.0        # LTX-Video: high guidance suppresses motion, keep near default

assert (TOTAL_FRAMES - 1) % 8 == 0, "TOTAL_FRAMES must be 8n+1"
assert (FRAMES_PER_CHUNK - 1) % 8 == 0, "FRAMES_PER_CHUNK must be 8n+1"


def generate_chunk(cond_image, num_frames, steps, seed):
    """Generate one chunk, retrying with a smaller footprint on CUDA OOM."""
    attempt_frames, attempt_steps = num_frames, steps
    for attempt in range(4):
        try:
            gen = torch.Generator(device="cuda").manual_seed(seed)
            result = pipe(
                image=cond_image,
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=TARGET_W,
                height=TARGET_H,
                num_frames=attempt_frames,
                num_inference_steps=attempt_steps,
                guidance_scale=GUIDANCE_SCALE,
                generator=gen,
            ).frames[0]
            return result
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            if attempt_frames > 9:
                # Shrink to the next smaller valid (8n+1) frame count.
                attempt_frames = ((attempt_frames - 1) // 8) * 8 - 8 + 1
                attempt_frames = max(attempt_frames, 9)
            else:
                attempt_steps = max(20, attempt_steps - 10)
            print(f"  OOM — retrying chunk with num_frames={attempt_frames}, "
                  f"num_inference_steps={attempt_steps}")
    raise RuntimeError("Chunk generation failed after repeated OOM retries")


all_frames = []
current_image = input_image
num_chunks = (TOTAL_FRAMES - 1) // (FRAMES_PER_CHUNK - 1)

for chunk_idx in range(num_chunks):
    print(f"Chunk {chunk_idx + 1}/{num_chunks}...")
    chunk_frames = generate_chunk(
        current_image, FRAMES_PER_CHUNK, NUM_INFERENCE_STEPS, seed=100 + chunk_idx
    )

    # Drop the first frame of every chunk after the first — it duplicates the
    # previous chunk's last frame (the conditioning image).
    all_frames.extend(chunk_frames if chunk_idx == 0 else chunk_frames[1:])
    current_image = chunk_frames[-1]

    # Release the chunk's activations before starting the next one.
    torch.cuda.empty_cache()

# 5. Export output
os.makedirs("output_videos", exist_ok=True)
export_to_video(all_frames, "output_videos/ltx_pan_working.mp4", fps=24)
print("Saved to output_videos/ltx_pan_working.mp4!")