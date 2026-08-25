# --- romaji.py :: guard the import instead of letting it crash the process -
"""
services/romaji.py
"""
import logging

logger = logging.getLogger(__name__)

# PATCH: guard the import itself. Previously `import pykakasi` at module
# level meant a missing package killed the ENTIRE process the instant
# main.py's `from services.romaji import RomajiConverter` line executed —
# before any try/except in the pipeline had a chance to intervene. Now the
# module imports successfully either way; the failure is deferred to
# actual USE (to_romaji), where it's already caught and logged.
try:
    import pykakasi
    _PYKAKASI_AVAILABLE = True
except ImportError:
    pykakasi = None
    _PYKAKASI_AVAILABLE = False
    logger.warning(
        "pykakasi is not installed — Romaji transliteration will be "
        "UNAVAILABLE and will fall through to returning original text. "
        "Run: pip install pykakasi"
    )


class RomajiConverter:
    _kks = None

    @classmethod
    def get_converter(cls):
        """Lazy loads the pykakasi converter instance."""
        if not _PYKAKASI_AVAILABLE:
            raise RuntimeError("pykakasi is not installed.")
        if cls._kks is None:
            cls._kks = pykakasi.kakasi()
        return cls._kks

    @staticmethod
    def to_romaji(text: str) -> str:
        """
        Transliterates Japanese text into capitalized Hepburn Romaji.
        Example: '大阪市' -> 'Osaka Shi'
        """
        if not text:
            return text

        try:
            kks = RomajiConverter.get_converter()
            result = kks.convert(text)
            romaji_tokens = [item['hepburn'] for item in result]
            formatted_romaji = " ".join(romaji_tokens).title()
            return formatted_romaji
        except Exception as e:
            logger.error(f"Romaji conversion failed for '{text}': {e}")
            return text