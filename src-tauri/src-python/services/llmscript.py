"""
services/ai_recommender.py
---------------------------------------------------------------------------
Ollama custom Modelfile integration for Navivi travel image analysis
with automatic dataset logging for future training.
---------------------------------------------------------------------------
"""

import re
import os
import sys
import json
import ollama
import urllib.request
import urllib.parse
from pydantic import BaseModel
from typing import Literal, Dict, Any


class TravelRecommendation(BaseModel):
    image_type: Literal["map", "attraction_photo", "unknown"]
    detected_location: str
    recommendation: str


def save_to_training_dataset(
    image_path: str, result_data: dict, dataset_path: str = "training_data.jsonl"
):
    """Appends the prompt, image path, and result to a JSONL training dataset file."""
    # Format following standard instruction/output training pairs
    training_entry = {"image_path": image_path, "output": result_data}

    with open(dataset_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(training_entry, ensure_ascii=False) + "\n")

    print(f"[Kaizen] Saved result to training dataset: {dataset_path}", file=sys.stderr)


def analyze_travel_image(
    image_path: str, model_name: str = "navivi-jp"
) -> Dict[str, Any]:
    """Analyzes an input map or attraction image and logs it for future training."""
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Target image file not found: {image_path}")

    prompt = (
        "提供された画像を分析してください。\n"
        "1. 画像が「地図（map）」か「観光地の写真（attraction_photo）」か、または「不明（unknown）」かを判定してください。\n"
        "2. 画像に示されている具体的な場所、ランドマーク、または地域を特定してください。\n"
        "3. 以下の基準に従って、すべて日本語で実用的なおすすめ情報を作成してください：\n"
        "   - 地図の場合：ステップバイステップの論理的なルート（徒歩や車）を提案してください。\n"
        "   - 観光地写真の場合：その場所の説明や雰囲気、および近くのおすすめスポットを2箇所紹介してください。\n"
        "   - 不明な場合：見えるものを説明し、一般的な旅行のアドバイスを提供してください。"
    )

    print(
        f"[Ollama] Analyzing image '{image_path}' using custom model '{model_name}'...",
        file=sys.stderr,
    )

    response = ollama.chat(
        model=model_name,
        messages=[
            {
                "role": "user",
                "content": prompt,
                "images": [image_path],
            }
        ],
        format=TravelRecommendation.model_json_schema(),
        stream=True,
    )

    full_content_builder = []

    for chunk in response:
        token = chunk["message"]["content"]
        print(token, end="", flush=True)  # Streams live to stdout
        full_content_builder.append(token)

    print("", file=sys.stderr)

    complete_response_text = "".join(full_content_builder)
    validated_data = TravelRecommendation.model_validate_json(complete_response_text)

    result_dict = validated_data.model_dump()

    # Automatically log the successful run for your dataset!
    save_to_training_dataset(image_path, result_dict)

    return result_dict


class VoiceoverScript(BaseModel):
    narration: str


def detect_language(text: str) -> str:
    """Detects if the text contains Japanese characters."""
    if re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", text):
        return "ja"
    return "en"


def get_wikipedia_facts(
    location_name: str, lat: float, lng: float, lang: str = "en"
) -> str:
    """Searches by Name, falls back to GPS, and seamlessly falls back to Japanese Wikipedia if English fails!"""

    def fetch_from_wiki(search_lang: str) -> str:
        try:
            # 1. Try exact text search first
            query = urllib.parse.quote(location_name)
            url = f"https://{search_lang}.wikipedia.org/w/api.php?action=query&list=search&srsearch={query}&utf8=&format=json&srlimit=1"
            req = urllib.request.Request(url, headers={"User-Agent": "NaviviApp/1.0"})
            with urllib.request.urlopen(req) as res:
                data = json.loads(res.read().decode("utf-8"))
                results = data.get("query", {}).get("search", [])

            page_ids = []
            if results:
                page_ids.append(str(results[0]["pageid"]))
            else:
                # 2. Fallback to GPS: Grab the Top 3 nearby articles within 300m
                geo_url = f"https://{search_lang}.wikipedia.org/w/api.php?action=query&list=geosearch&gscoord={lat}|{lng}&gsradius=300&gslimit=3&format=json"
                req_geo = urllib.request.Request(
                    geo_url, headers={"User-Agent": "NaviviApp/1.0"}
                )
                with urllib.request.urlopen(req_geo) as res_geo:
                    geo_data = json.loads(res_geo.read().decode("utf-8"))
                    geo_results = geo_data.get("query", {}).get("geosearch", [])
                    page_ids = [str(r["pageid"]) for r in geo_results]

            if not page_ids:
                return ""

            # 3. Fetch text for the found pages
            ids_str = "|".join(page_ids)
            ext_url = f"https://{search_lang}.wikipedia.org/w/api.php?action=query&prop=extracts&exintro&explaintext&pageids={ids_str}&format=json"
            req_ext = urllib.request.Request(
                ext_url, headers={"User-Agent": "NaviviApp/1.0"}
            )
            with urllib.request.urlopen(req_ext) as res_ext:
                ext_data = json.loads(res_ext.read().decode("utf-8"))
                pages = ext_data.get("query", {}).get("pages", {})

                facts_list = []
                for pid, pdata in pages.items():
                    title = pdata.get("title", "")
                    extract = pdata.get("extract", "")[
                        :250
                    ]  # Keep it short to save tokens
                    if title and extract:
                        facts_list.append(f"【Article: {title}】\n{extract}")
                return "\n\n".join(facts_list)
        except Exception as e:
            print(f"[Wiki {search_lang}] Error: {e}", file=sys.stderr)
            return ""

    # Try user's language first
    facts = fetch_from_wiki(lang)

    # THE MAGIC TRICK: If nothing was found, quietly search Japanese Wikipedia!
    if not facts and lang != "ja":
        facts = fetch_from_wiki("ja")

    return facts


def sanitize_location_name(name: str) -> str:
    if not name:
        return ""

    clean = name.strip()
    if re.match(r"^\d+$", clean) or len(clean) < 2:
        return ""
    invalid_placeholders = [
        "locating...",
        "unknown location",
        "waypoint",
        "null",
        "undefined",
    ]
    if clean.lower() in invalid_placeholders:
        return ""
    return clean


def generate_voiceover_script(
    prompt: str, location_name: str, lat: float, lng: float, engine: str = "ollama"
) -> str:
    lang = detect_language(prompt + location_name)

    # Clean and validate location name
    valid_name = sanitize_location_name(location_name)
    has_user_prompt = bool(prompt and prompt.strip())
    # Get facts if we have location name
    facts = ""
    if valid_name:
        facts = get_wikipedia_facts(valid_name, lat, lng, lang)
    # Determine core subject
    if has_user_prompt and not valid_name:
        # If name is invalid and user gave prompt
        subject_header = (
            f"■ 目的地のテーマ・メモ: {prompt}\n■ 座標: ({lat:.4f}, {lng:.4f})"
        )
    elif has_user_prompt and valid_name:
        subject_header = (
            f"■ スポット名: {valid_name}\n■ ユーザー指定テーマ(最優先): {prompt}"
        )
    elif valid_name:
        subject_header = f"■ スポット名: {valid_name}"
    else:
        # Name bad, prompt empty go search
        subject_header = f"■ 目的地の座標: ({lat:.4f}, {lng:.4f})"

    if lang == "ja":
        system_instruction = f"""あなたは旅番組のプロの音声ガイドナレーターです。
        {subject_header}
        【重要指示】
        1. スポット名が数字や不完全な場合でも、決して2や座標といった番号をそのまま発音しないでください。
        2. ユーザー指定テーマがある場合はそれを中心に、移動中の背景や次の目的地へ向かうワクワク感と共にプロフェッショナル感を表現してください。
        3. 参考情報がある場合は活用し、自然な話言葉 (4~5分程度) で出力してください。
        4. トーン書きやBGMなどの記号は一切出力せず、ナレーション本文のみを出力してください。
        """
        user_msg = (
            "このスポットの魅力や移動の楽しさを伝えるナレーションを作成してください。"
        )
        fallback_text = "エラー発生しました。もう一度やり直してください。"
    else:
        system_instruction = f"""You are a professional travel video narrator.
        {subject_header}
        
        【Critical Rules】
        1. NEVER read out raw numbers (like "2") or coordinates as the place name.
        2. If a user note/prompt is provided, make it the main focus of the narration.
        3. Write 4-5 natural spoken sentences with formality but keeps the fun mood. Output ONLY the narration text.
        """
        user_msg = "Generate a smooth audio guide snippet for this stop."
        fallback_text = "(There was an error while trying to generate the script.)"
    try:
        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt + user_msg},
        ]

        if engine == "ollama":
            target_model = "gemma2"
            response = ollama.chat(model=target_model, messages=messages)
            clean_text = re.sub(r"（.*?）|\(.*?\)", "", response["message"]["content"])
            return clean_text.strip()

        elif engine == "gemini":
            api_key = os.environ.get("GEMINI_API_KEY", "")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
            payload = json.dumps(
                {
                    "system_instruction": {"parts": [{"text": system_instruction}]},
                    "contents": [{"parts": [{"text": user_msg}]}],
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                url, data=payload, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req) as res:
                data = json.loads(res.read().decode("utf-8"))
                clean_text = re.sub(
                    r"（.*?）|\(.*?\)",
                    "",
                    data["candidates"][0]["content"]["parts"][0]["text"],
                )
                return clean_text.strip()

        elif engine == "groq":
            api_key = os.environ.get("GROQ_API_KEY", "")
            url = "https://api.groq.com/openai/v1/chat/completions"
            payload = json.dumps(
                {"model": "llama3-8b-8192", "messages": messages}
            ).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
            with urllib.request.urlopen(req) as res:
                data = json.loads(res.read().decode("utf-8"))
                clean_text = re.sub(
                    r"（.*?）|\(.*?\)", "", data["choices"][0]["message"]["content"]
                )
                return clean_text.strip()

    except Exception as e:
        print(f"[AI Error] Engine {engine} failed: {e}", file=sys.stderr)
        return fallback_text


def generate_overview_script(waypoints: list[str], engine: str = "ollama") -> str:
    if not waypoints:
        return (
            "素晴らしい旅の始まりです。さあ、出発しましょう！"
            if engine == "ollama"
            else "Welcome to our journey. Let's get started!"
        )

    combined_names = "、".join(waypoints)
    lang = detect_language(combined_names)

    if lang == "ja":
        system_instruction = (
            f"あなたは旅行番組のオープニングを飾るプロのナレーターです。\n\n"
            f"今回のツアールート: {combined_names}\n\n"
            f"【作成ルール】\n"
            f"1. このルート全体を紹介する、ワクワクするようなオープニングナレーション（5〜6文程度）を作成してください。\n"
            f"2. （BGM）などのト書きやカッコ書きは絶対に含めないでください。\n"
            f"3. 訪れる場所の魅力を簡潔にまとめ、出発への期待を高めてください。"
        )
        user_msg = "このルートのオープニングナレーションを作成してください。"
        fallback = "素晴らしい旅の始まりです。さあ、出発しましょう！"
    else:
        system_instruction = (
            f"You are a professional travel show narrator introducing a tour.\n\n"
            f"Tour Stops: {combined_names}\n\n"
            f"【RULES】\n"
            f"1. Write an exciting 5-6 sentence opening narration summarizing this route.\n"
            f"2. DO NOT include any stage directions or parentheses.\n"
            f"3. Highlight the appeal of these stops and build excitement for the journey."
        )
        user_msg = "Create an opening narration for this route."
        fallback = "Welcome to our journey. Let's get started!"

    try:
        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_msg},
        ]

        if engine == "ollama":
            target_model = "gemma2"
            response = ollama.chat(model=target_model, messages=messages)
            return re.sub(
                r"（.*?）|\(.*?\)", "", response["message"]["content"]
            ).strip()

        elif engine == "gemini":
            api_key = os.environ.get("GEMINI_API_KEY", "")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
            payload = json.dumps(
                {
                    "system_instruction": {"parts": [{"text": system_instruction}]},
                    "contents": [{"parts": [{"text": user_msg}]}],
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                url, data=payload, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req) as res:
                data = json.loads(res.read().decode("utf-8"))
                return re.sub(
                    r"（.*?）|\(.*?\)",
                    "",
                    data["candidates"][0]["content"]["parts"][0]["text"],
                ).strip()

        elif engine == "groq":
            api_key = os.environ.get("GROQ_API_KEY", "")
            url = "https://api.groq.com/openai/v1/chat/completions"
            payload = json.dumps(
                {"model": "llama3-8b-8192", "messages": messages}
            ).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
            with urllib.request.urlopen(req) as res:
                data = json.loads(res.read().decode("utf-8"))
                return re.sub(
                    r"（.*?）|\(.*?\)", "", data["choices"][0]["message"]["content"]
                ).strip()

    except Exception as e:
        print(f"[Error (LLM)] Engine {engine} failed: {e}", file=sys.stderr)
        return fallback
