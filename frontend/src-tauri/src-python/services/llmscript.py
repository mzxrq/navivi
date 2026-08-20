"""
services/ai_recommender.py
---------------------------------------------------------------------------
Ollama llava integration for auto-detecting maps vs. attraction
photos and generating structured travel itineraries/routes.
---------------------------------------------------------------------------
"""

import os
import sys
import ollama
from pydantic import BaseModel
from typing import Literal, Dict, Any


class TravelRecommendation(BaseModel):
    image_type: Literal["map", "attraction_photo", "unknown"]
    detected_location: str
    recommendation: str


def analyze_travel_image(image_path: str, model_name: str = "navivi-jp") -> Dict[str, Any]:
    """Analyzes an input map or attraction image and returns structured route/place advice."""
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Target image file not found: {image_path}")

    prompt = (
        "あなたは専門のAI旅行アシスタントです。提供された画像を分析してください。\n"
        "1. 画像が「地図（map）」か「観光地の写真（attraction_photo）」か、または「不明（unknown）」かを判定してください。\n"
        "2. 画像に示されている具体的な場所、ランドマーク、または地域を特定してください。\n"
        "3. 以下の基準に従って、すべて日本語で実用的なおすすめ情報を作成してください：\n"
        "   - 地図の場合：ステップバイステップの論理的なルート（徒歩や車）を提案してください。\n"
        "   - 観光地写真の場合：その場所の説明や雰囲気、および近くのおすすめスポットを2箇所紹介してください。\n"
        "   - 不明な場合：見えるものを説明し、一般的な旅行のアドバイスを提供してください。\n"
        "出力は必ず有効なJSON形式（Markdownのコードブロックは使わず、純粋なJSONのみ）で行ってください。"
    )

    print(f"[Ollama] Analyzing image '{image_path}' using {model_name}...", file=sys.stderr)

    response = ollama.chat(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": "あなたは専門のAI旅行アシスタントです。すべての出力（detected_locationおよびrecommendationを含む）は、必ず自然な日本語で行ってください。英語は絶対に使用しないでください。"
            },
            {
                "role": "user",
                "content": prompt,
                "images": [image_path],  # <--- Image lives here in the user role!
            }
        ],
        format=TravelRecommendation.model_json_schema(),
        options={"temperature": 0.0},
        stream=True
    )

    # Collect chunks as they stream in
    full_content_builder = []

    for chunk in response:
        token = chunk['message']['content']
        print(token, end='', flush=True)  # Streams live
        full_content_builder.append(token)

    # Print a newline so the JSON success message starts cleanly on the next line
    print("", file=sys.stderr)

    complete_response_text = "".join(full_content_builder)
    validated_data = TravelRecommendation.model_validate_json(complete_response_text)

    return validated_data.model_dump()