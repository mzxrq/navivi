"""SDXL inpainting + BLIP captioning, loaded once and shared: jump_cut.py's AI outpaint uses them and
ltx_keyframed.py releases them between stages. The old outpaint-and-pan clip generator that lived here
was replaced by the ComfyUI / parallax / still-clip paths (img2vdo.py).
"""

from PIL import Image

from services.logger.logger import setup_logger

logger = setup_logger("LocalPanGenerator")


def _cuda_available() -> bool:
    """False when there is no GPU or no PyTorch at all.

    [NOTE] [Animation] torch, diffusers and transformers are imported only where the AI outpaint needs them: the installed app's
    Python has none of them (several GB), and the plain pan over the original photo, which is the fallback, must still work."""
    try:
        import torch

        return torch.cuda.is_available()
    except ImportError:
        return False


def _free_gpu_memory() -> None:
    if _cuda_available():
        import torch

        torch.cuda.empty_cache()

# [HACK] [Animation] Loaded once and reused across every waypoint in a batch, instead of a fresh
# from_pretrained() + del per call. Reloading per waypoint (the original
# design) turned out to both balloon system RAM over a run — accelerate's
# enable_model_cpu_offload() hooks leave reference cycles that `del` +
# empty_cache() don't fully release, so each reload leaked on top of the
# last — and made later waypoints dramatically slower (one call went from
# ~20s to ~8 minutes partway through a 15-waypoint run), consistent with the
# CUDA/CPU allocators fighting fragmentation from the repeated churn. A
# single long-lived pipeline avoids both.
_pipe = None
_blip_model = None
_blip_processor = None
_MEMORY_FRACTION_SET = False


def _cap_memory_fraction() -> None:
    """Caps PyTorch's own CUDA allocator once per process so it raises a
    clean, catchable torch.cuda.OutOfMemoryError instead of the point where
    Windows' WDDM driver would otherwise silently spill into slow/unstable
    shared system memory — cheap insurance against a repeat of the VRAM-
    linked instability seen during earlier exploration."""
    global _MEMORY_FRACTION_SET
    if not _MEMORY_FRACTION_SET and _cuda_available():
        import torch

        torch.cuda.set_per_process_memory_fraction(0.85, 0)
        _MEMORY_FRACTION_SET = True


def _get_pipe():
    global _pipe
    if _pipe is None:
        import torch
        from diffusers import AutoPipelineForInpainting

        _cap_memory_fraction()
        logger.info("Loading SDXL inpainting pipeline (once, reused for the whole batch)...")
        _pipe = AutoPipelineForInpainting.from_pretrained(
            "diffusers/stable-diffusion-xl-1.0-inpainting-0.1",
            torch_dtype=torch.bfloat16,
        )
        # enable_model_cpu_offload() shuttles modules between CPU and GPU
        # VRAM as each is needed — meaningless (and raises "requires
        # accelerator, but not found") with no CUDA device to offload TO.
        # Observed in the wild: ComfyUI's own subprocess had a rough run
        # (a stalled/reset connection — see comfyui_i2v_client.py's
        # _wait_for_result) right before this fallback kicked in, and by
        # the time it did, torch.cuda.is_available() came back False here —
        # this used to hard-fail the outpaint step outright (silently
        # degrading to a plain, non-outpainted pan) instead of just running
        # the pipeline directly on whatever device is actually available.
        if torch.cuda.is_available():
            _pipe.enable_model_cpu_offload()
        else:
            logger.warning(
                "No CUDA device available — running the SDXL inpainting "
                "pipeline on CPU directly (slow) instead of GPU-offloaded."
            )
            _pipe.to("cpu")
        _pipe.vae.enable_slicing()
    return _pipe


def release_models() -> None:
    """Drops the SDXL pipe and BLIP so another GPU job gets the memory."""
    global _pipe, _blip_model, _blip_processor
    if _pipe is None and _blip_model is None:
        return
    import gc

    _pipe = _blip_model = _blip_processor = None
    gc.collect()
    _free_gpu_memory()
    logger.info("Released the SDXL inpainting and BLIP models.")


def _get_blip():
    global _blip_model, _blip_processor
    if _blip_model is None:
        from transformers import BlipForConditionalGeneration, BlipProcessor

        _cap_memory_fraction()
        logger.info("Loading BLIP captioner (once, reused for the whole batch)...")
        device = "cuda" if _cuda_available() else "cpu"
        _blip_processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
        _blip_model = BlipForConditionalGeneration.from_pretrained(
            "Salesforce/blip-image-captioning-base"
        ).to(device)
    return _blip_model, _blip_processor


STEPS = 30
GUIDANCE = 8.0
NEGATIVE_PROMPT = (
    "wall, concrete wall, stone wall, brick wall, building, building facade, "
    "door, doorway, pillar, column, wooden frame, indoor, interior, room, "
    "furniture, architecture close-up, museum wall, gallery wall, "
    "duplicate object, duplicate vehicle, second train, extra train, "
    "disconnected object, floating debris, malformed, deformed, mangled, "
    "seam, border, collage, watermark, text, blurry, distorted, "
    "different lighting, different style, low quality"
)


def _describe_scene(pil_img: Image.Image) -> str:
    """One-shot BLIP captioning so the outpaint prompt is grounded in
    whatever is actually in THIS photo, not a hand-written/stale prompt."""
    model, processor = _get_blip()
    device = "cuda" if _cuda_available() else "cpu"
    inputs = processor(pil_img, return_tensors="pt").to(device)
    out = model.generate(**inputs, max_new_tokens=40)
    return processor.decode(out[0], skip_special_tokens=True).strip()
