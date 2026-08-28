"""
Translation Service Module (translator.py)
---------------------------------------------------------------------------
100% offline local machine translation service utilizing Helsinki-NLP models,
enhanced with a dynamic JSON glossary to protect place names and proper nouns.
---------------------------------------------------------------------------
"""

import json
from pathlib import Path
from typing import Any

from services.logger import setup_logger

logger = setup_logger("ScriptTranslator")

# Check for the availability of transformers and torch libraries
try:
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

    _TRANSFORMERS_AVAILABLE = True
except ImportError as e:
    AutoTokenizer = None
    AutoModelForSeq2SeqLM = None
    _TRANSFORMERS_AVAILABLE = False
    logger.warning(
        "transformers/torch not available (%s) — offline translation will "
        "be UNAVAILABLE and will fall through to returning original text. "
        "Run: pip install transformers torch sentencepiece",
        e,
    )

# [Config] Default path to the glossary.json file
_DEFAULT_GLOSSARY_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "glossary.json"
)


# [Core] ScriptTranslator Class
class ScriptTranslator:
    _tokenizers = {}
    _models = {}
    _glossary = None
    last_call_failed: bool = False

    # [Config] Load glossary.json dynamically if it exists
    @classmethod
    def load_glossary(cls, glossary_path: Path = _DEFAULT_GLOSSARY_PATH):
        """Loads the glossary.json file dynamically if it exists."""
        if cls._glossary is None:
            if glossary_path.exists():
                try:
                    with open(glossary_path, "r", encoding="utf-8") as f:
                        cls._glossary = json.load(f)
                    logger.info(
                        f"📖 Loaded {len(cls._glossary)} terms from {glossary_path}"
                    )
                except Exception as e:
                    logger.error(f"Failed to load glossary from {glossary_path}: {e}")
                    cls._glossary = {}
            else:
                logger.info(
                    f"No glossary found at {glossary_path} — proceeding without one."
                )
                cls._glossary = {}
        return cls._glossary

    # [Validation] Resolves glossary values whether they are simple strings or language-mapped dicts
    @staticmethod
    def _resolve_glossary_replacement(
        jp_name: str, raw_value: Any, target_lang: str = "en"
    ) -> str:
        """Resolves glossary values whether they are simple strings or language-mapped dicts."""
        if isinstance(raw_value, str):
            return raw_value
        if isinstance(raw_value, dict):
            lang_key = target_lang.lower()
            return raw_value.get(lang_key, raw_value.get("en", jp_name))
        return str(raw_value)

    # [Config] Dynamically loads and caches the correct language pair model for translation
    @classmethod
    def get_model_and_tokenizer(cls, target_lang: str = "en"):
        """Dynamically loads and caches the correct language pair model.
        Loads from local cache if available; downloads only if missing.
        """
        if not _TRANSFORMERS_AVAILABLE:
            raise RuntimeError(
                "transformers/torch is not installed; cannot load offline "
                "translation model."
            )

        lang_map = {
            "english": "en",
            "en": "en",
            "chinese": "zh",
            "zh": "zh",
            "mandarin": "zh",
            "spanish": "es",
            "es": "es",
            "french": "fr",
            "fr": "fr",
            "german": "de",
            "de": "de",
            "korean": "ko",
            "ko": "ko",
            "thai": "th",
            "th": "th",
        }

        lang_code = lang_map.get(target_lang.lower(), "en")

        if lang_code not in cls._models:
            model_name = f"Helsinki-NLP/opus-mt-ja-{lang_code}"

            try:
                # 1. Try loading strictly from local cache (0% internet checking)
                logger.info(f"🔍 Checking local cache for {model_name}...")
                cls._tokenizers[lang_code] = AutoTokenizer.from_pretrained(model_name, local_files_only=True)  # type: ignore
                cls._models[lang_code] = AutoModelForSeq2SeqLM.from_pretrained(model_name, local_files_only=True)  # type: ignore
                logger.info(f"Loaded {model_name} successfully from local cache!")

            except Exception:
                # 2. If it's not downloaded yet, fall back to downloading it
                logger.info(
                    f"Model not found locally. Downloading {model_name} (internet required for first run)..."
                )
                cls._tokenizers[lang_code] = AutoTokenizer.from_pretrained(model_name, local_files_only=False)  # type: ignore
                cls._models[lang_code] = AutoModelForSeq2SeqLM.from_pretrained(model_name, local_files_only=False)  # type: ignore
                logger.info(f"Download complete and cached locally.")

        return cls._tokenizers[lang_code], cls._models[lang_code]

    # [Translation] Translates text to the target language, applying glossary replacements before and after translation
    @staticmethod
    def translate(text: str, target_lang: str = "en") -> str:
        if not text:
            ScriptTranslator.last_call_failed = False
            return text

        ScriptTranslator.last_call_failed = False

        try:
            glossary = ScriptTranslator.load_glossary()
            processed_text = text
            placeholder_map = {}

            # 1. Pre-process: Swap glossary terms with placeholders
            for i, (jp_name, raw_value) in enumerate(glossary.items()):
                if jp_name in processed_text:
                    placeholder = f"__PLACE_{i}__"
                    resolved_value = ScriptTranslator._resolve_glossary_replacement(
                        jp_name, raw_value, target_lang
                    )
                    placeholder_map[i] = resolved_value
                    processed_text = processed_text.replace(jp_name, placeholder)

            tokenizer, model = ScriptTranslator.get_model_and_tokenizer(target_lang)

            inputs = tokenizer(
                processed_text,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512,
            )
            translated_tokens = model.generate(**inputs)
            translated_text = tokenizer.decode(
                translated_tokens[0], skip_special_tokens=True
            )

            # 2. Post-process: Swap placeholders back and guarantee proper spacing
            import re

            def replace_placeholder(match):
                index = int(match.group(1))
                replacement = placeholder_map.get(index, match.group(0))
                # 💡 FORCE a space before and after the replacement
                return f" {replacement} "

            # Use optional underscores (*) in case the AI messed up the formatting
            pattern = re.compile(
                r"_*\s*p\s*l\s*a\s*c\s*e\s*[-_\s]*(\d+)\s*_*", re.IGNORECASE
            )
            translated_text = pattern.sub(replace_placeholder, translated_text)

            # 3. Clean up formatting: merge double spaces into one, and fix punctuation gaps
            translated_text = re.sub(r"\s+", " ", translated_text)
            translated_text = re.sub(r"\s+([.,!?])", r"\1", translated_text).strip()

            return translated_text

        except Exception as e:
            ScriptTranslator.last_call_failed = True
            logger.error(
                f"Offline translation to '{target_lang}' failed: {e}", exc_info=True
            )
            return text
