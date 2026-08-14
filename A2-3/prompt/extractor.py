import json
import logging

from dotenv import load_dotenv
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-3.6-flash"

load_dotenv()

def validate_insight_result(result):
    if not isinstance(result, dict):
        raise ValueError("인사이트 결과가 딕셔너리 형식이 아닙니다.")

    required_keys = {
        "positive_keywords",
        "negative_keywords",
        "summary",
        "improvements",
    }

    if not required_keys.issubset(result):
        missing_keys = required_keys - result.keys()
        raise ValueError(f"필수 인사이트 항목이 누락되었습니다: {missing_keys}")

    if not isinstance(result["positive_keywords"], list):
        raise ValueError("positive_keywords는 리스트여야 합니다.")

    if not isinstance(result["negative_keywords"], list):
        raise ValueError("negative_keywords는 리스트여야 합니다.")

    if not isinstance(result["summary"], str):
        raise ValueError("summary는 문자열이어야 합니다.")

    if not isinstance(result["improvements"], list):
        raise ValueError("improvements는 리스트여야 합니다.")

    if len(result["improvements"]) < 2:
        raise ValueError("improvements는 2개 이상이어야 합니다.")

    return result

def extract_insights(reviews):
    if not isinstance(reviews, list) or not reviews:
        raise ValueError("reviews는 하나 이상의 리뷰가 포함된 리스트여야 합니다.")

    for review in reviews:
        if not isinstance(review, str) or not review.strip():
            raise ValueError("각 리뷰는 비어 있지 않은 문자열이어야 합니다.")

    client = genai.Client()

    review_text = "\n".join(
        f"- {review}" for review in reviews
    )

    prompt = f"""
    다음 상품 리뷰들을 종합해서 핵심 인사이트를 추출하세요.

    리뷰:
    {review_text}

    다음 내용을 정리하세요.

    1. positive_keywords:
       고객이 반복적으로 긍정적으로 언급한 핵심 키워드

    2. negative_keywords:
       고객이 반복적으로 부정적으로 언급한 핵심 키워드

    3. summary:
       전체 리뷰에서 나타나는 주요 의견을 짧게 요약

    4. improvements:
        부정적인 의견과 고객의 아쉬움을 바탕으로 개선이 필요한 사항을
        서로 다른 내용으로 반드시 2개 이상 제안하세요.
    """

    max_attempts = 2

    for attempt in range(max_attempts):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema={
                        "type": "object",
                        "properties": {
                            "positive_keywords": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "negative_keywords": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "summary": {
                                "type": "string",
                            },
                            "improvements": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "positive_keywords",
                            "negative_keywords",
                            "summary",
                            "improvements",
                        ],
                    },
                ),
            )

            result = json.loads(response.text)

            return validate_insight_result(result)

        except Exception as error:
            if attempt == 0:
                logger.warning(
                    "Gemini 인사이트 추출 실패. 1회 재시도합니다: %s",
                    error,
                )
            else:
                logger.error(
                    "Gemini 인사이트 추출이 재시도 후에도 실패했습니다: %s",
                    error,
                )
                return None

if __name__ == "__main__":
    test_reviews = [
        "음질이 생각보다 좋아요",
        "배터리가 생각보다 오래가서 만족합니다",
        "충전 케이스가 조금 큰 것 같아요",
        "제품이 갑자기 꺼지는 문제가 있습니다",
        "고장난 제품이 배송되었습니다",
    ]

    result = extract_insights(test_reviews)
    print(result)