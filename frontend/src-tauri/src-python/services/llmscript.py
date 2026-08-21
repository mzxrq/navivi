"""
services/ai_recommender.py
---------------------------------------------------------------------------
Ollama custom Modelfile integration for Navivi travel image analysis
with automatic dataset logging for future training.
---------------------------------------------------------------------------
"""

import os
import sys
import json
import ollama
from pydantic import BaseModel
from typing import Literal, Dict, Any


class TravelRecommendation(BaseModel):
    image_type: Literal["map", "attraction_photo", "unknown"]
    detected_location: str
    recommendation: str


def save_to_training_dataset(image_path: str, result_data: dict, dataset_path: str = "training_data.jsonl"):
    """Appends the prompt, image path, and result to a JSONL training dataset file."""
    # Format following standard instruction/output training pairs
    training_entry = {
        "image_path": image_path,
        "output": result_data
    }
    
    with open(dataset_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(training_entry, ensure_ascii=False) + "\n")
    
    print(f"[Kaizen] Saved result to training dataset: {dataset_path}", file=sys.stderr)


def analyze_travel_image(image_path: str, model_name: str = "navivi-jp") -> Dict[str, Any]:
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

    print(f"[Ollama] Analyzing image '{image_path}' using custom model '{model_name}'...", file=sys.stderr)

    response = ollama.chat(
        model=model_name,
        messages=[{
            "role": "user",
            "content": prompt,
            "images": [image_path],
        }],
        format=TravelRecommendation.model_json_schema(),
        stream=True
    )

    full_content_builder = []

    for chunk in response:
        token = chunk['message']['content']
        print(token, end='', flush=True)  # Streams live to stdout
        full_content_builder.append(token)

    print("", file=sys.stderr)

    complete_response_text = "".join(full_content_builder)
    validated_data = TravelRecommendation.model_validate_json(complete_response_text)
    
    result_dict = validated_data.model_dump()

    # Automatically log the successful run for your dataset!
    save_to_training_dataset(image_path, result_dict)

    return result_dict