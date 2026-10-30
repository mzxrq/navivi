"""The sentences one narration file is made of, kept in the project (.navivi/voice_pieces/<file>/).

pieces.json lists them in order: {"voice": the voice fingerprint, "pieces": [{"text", "takes": [file, ...]}]}; each take
is a WAV named by its content hash. A file voiced again reuses every sentence whose text and voice are unchanged, so
only edited sentences (or ones picked in the editor, see `redo`) are spoken again, on any computer the project is on."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.logger.logger import setup_logger
from services.projectfiles import write_json_atomic

logger = setup_logger("VoicePieces")

MANIFEST = "pieces.json"


def _manifest(folder: Path) -> Dict[str, Any]:
    try:
        data = json.loads((Path(folder) / MANIFEST).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load(folder: Path, voice: Optional[dict]) -> Dict[str, List[bytes]]:
    """{sentence text: its takes} for the kept sentences spoken with `voice`; {} when the voice changed."""
    data = _manifest(folder)
    if data.get("voice") != voice:
        return {}
    out: Dict[str, List[bytes]] = {}
    for piece in data.get("pieces") or []:
        try:
            out[piece["text"]] = [(Path(folder) / name).read_bytes() for name in piece["takes"]]
        except (OSError, KeyError, TypeError):
            continue
    return out


def save(folder: Path, voice: Optional[dict], pieces: List[tuple]) -> None:
    """Keeps `pieces` [(text, [take bytes])] as the file's sentences; takes no piece uses any more are removed."""
    folder = Path(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        entries, used = [], set()
        for text, takes in pieces:
            names = []
            for take in takes:
                name = f"{hashlib.sha256(take).hexdigest()[:20]}.wav"
                path = folder / name
                if not path.exists():
                    tmp = path.with_suffix(".part")
                    tmp.write_bytes(take)
                    os.replace(tmp, path)
                names.append(name)
                used.add(name)
            entries.append({"text": text, "takes": names})
        write_json_atomic(folder / MANIFEST, {"voice": voice, "pieces": entries})
        for path in folder.glob("*.wav"):
            if path.name not in used:
                path.unlink(missing_ok=True)
    except OSError as exc:  # only an optimisation: the narration file itself is already written
        logger.warning("Could not keep the narration's sentences in %s: %s", folder, exc)


def listing(folder: Path) -> List[Dict[str, Any]]:
    """The kept sentences in order: [{"text", "path"}] (path = the first take). The editor reads pieces.json itself
    (src/features/editor/VoicePiecesDialog.tsx) and mirrors this."""
    folder = Path(folder)
    return [
        {"text": p["text"], "path": str(folder / p["takes"][0])}
        for p in _manifest(folder).get("pieces") or []
        if p.get("takes")
    ]


def texts(folder: Path, indexes: List[int]) -> set:
    """The sentences at `indexes` of the kept list (what the editor showed)."""
    pieces = _manifest(folder).get("pieces") or []
    return {pieces[i]["text"] for i in indexes if 0 <= i < len(pieces)}
