"""Encodes a reference voice into the latent Irodori conditions on, once, so requests do not re-encode the wav every time (~5 s each
on a CPU). Run with the Irodori server's own Python (it has torch and irodori_tts): `python make_latent.py <voice file> <out.pt>`.

Uses what the server does for a wav reference: the same codec, fp32 on the CPU, loudness -16 dB with peak safety."""

import os
import sys

CODEC_REPO = "Aratako/Semantic-DACVAE-Japanese-32dim"
NORMALIZE_DB = -16.0


def main(voice_path: str, out_path: str) -> None:
    import torch
    from irodori_tts.codec import DACVAECodec
    from irodori_tts.inference_runtime import _load_audio

    codec = DACVAECodec.load(
        repo_id=CODEC_REPO, device="cpu", dtype=torch.float32, deterministic_encode=True, deterministic_decode=True
    )
    wav, sample_rate = _load_audio(voice_path)
    latent = codec.encode_waveform(
        wav.unsqueeze(0), sample_rate=int(sample_rate), normalize_db=NORMALIZE_DB, ensure_max=True
    ).cpu()
    tmp = out_path + ".part"
    torch.save(latent[0].contiguous(), tmp)
    os.replace(tmp, out_path)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
