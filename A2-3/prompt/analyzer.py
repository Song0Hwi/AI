import json
import logging

from dotenv import load_dotenv
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-3.6-flash"

ALLOWED_SENTIMENTS = {
    "positive",
    "negative",
    "neutral",
}

load_dotenv()


def validate_analysis_result(result):
    if not isinstance(result, dict):
        raise ValueError("분석 결과가 딕셔너리 형식이 아닙니다.")

    sentiment = result.get("sentiment")
    confidence = result.get("confidence")

    if sentiment not in ALLOWED_SENTIMENTS:
        raise ValueError(f"허용되지 않은 감정값입니다: {sentiment}")

    if not isinstance(confidence, (int, float)):
        raise ValueError("confidence는 숫자여야 합니다.")

    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence는 0.0부터 1.0 사이여야 합니다.")

    return result

def validate_batch_analysis_result(result, expected_ids):
    """배치 감정 분석 결과의 구조와 ID를 검증한다."""

    if not isinstance(result, dict):
        raise ValueError("배치 분석 결과가 딕셔너리 형식이 아닙니다.")

    batch_results = result.get("results")

    if not isinstance(batch_results, list):
        raise ValueError("results는 리스트여야 합니다.")

    expected_id_set = set(expected_ids)
    returned_ids = set()

    for item in batch_results:
        if not isinstance(item, dict):
            raise ValueError(
                "각 배치 분석 결과는 딕셔너리여야 합니다."
            )

        review_id = item.get("id")

        if not isinstance(review_id, int):
            raise ValueError("분석 결과의 id는 정수여야 합니다.")

        if review_id not in expected_id_set:
            raise ValueError(
                f"요청하지 않은 리뷰 id가 반환되었습니다: {review_id}"
            )

        if review_id in returned_ids:
            raise ValueError(
                f"중복된 리뷰 id가 반환되었습니다: {review_id}"
            )

        validate_analysis_result(item)
        returned_ids.add(review_id)

    if returned_ids != expected_id_set:
        missing_ids = sorted(expected_id_set - returned_ids)

        raise ValueError(
            f"배치 분석 결과에서 일부 id가 누락되었습니다: "
            f"{missing_ids}"
        )

    return batch_results

def analyze_review(review_text):
    if not isinstance(review_text, str) or not review_text.strip():
        raise ValueError("review_text는 비어 있지 않은 문자열이어야 합니다.")
    
    client = genai.Client()

    prompt = f"""
    다음 상품 리뷰의 텍스트만 보고 감정을 분석하세요.
    별점이나 다른 정보는 사용하지 않습니다.

    리뷰:
    {review_text}

    감정은 반드시 다음 세 가지 중 하나로 분류하세요.

    - positive:
      만족, 칭찬, 추천, 장점 등 긍정적인 평가가 명확한 경우

    - negative:
      불만, 문제, 결함, 아쉬움, 불편함 등 부정적인 평가가 명확한 경우

    - neutral:
      긍정이나 부정이 뚜렷하지 않은 단순 사실 전달이거나,
      긍정과 부정이 함께 존재하여 어느 한쪽이 명확하게 우세하지 않은 경우

    confidence는 위 감정 분류에 대한 확신 정도를
    0.0부터 1.0 사이의 숫자로 반환하세요.

    표현이 명확할수록 confidence를 높게,
    의미가 혼합되어 있거나 애매할수록 낮게 판단하세요.
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
                            "sentiment": {
                                "type": "string",
                                "enum": [
                                    "positive",
                                    "negative",
                                    "neutral",
                                ],
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                        },
                        "required": [
                            "sentiment",
                            "confidence",
                        ],
                    },
                ),
            )

            result = json.loads(response.text)

            return validate_analysis_result(result)

        except Exception as error:
            if attempt == 0:
                logger.warning(
                    "Gemini 감정 분석 실패. 1회 재시도합니다: %s",
                    error,
                )
            else:
                logger.error(
                    "Gemini 감정 분석이 재시도 후에도 실패했습니다: %s",
                    error,
                )
                raise

def analyze_review_batch(reviews):
    """여러 리뷰를 Gemini 한 번의 요청으로 감정 분석한다."""

    if not reviews:
        return []

    client = genai.Client()

    expected_ids = [
        review["id"]
        for review in reviews
    ]

    reviews_json = json.dumps(
        reviews,
        ensure_ascii=False,
    )

    prompt = f"""
다음 상품 리뷰들을 각각 독립적으로 감정 분석하세요.

중요한 규칙:
- 별점이나 다른 정보는 사용하지 않습니다.
- 각 review_text의 내용만 보고 판단합니다.
- 입력된 모든 리뷰를 빠짐없이 분석합니다.
- 입력 리뷰의 id를 결과에도 반드시 그대로 유지합니다.
- 각 id에 대해 결과를 정확히 하나씩 반환합니다.
- 리뷰끼리 서로 영향을 주지 않고 독립적으로 판단합니다.

리뷰 목록:
{reviews_json}

감정 분류 기준:

- positive:
  만족, 칭찬, 추천, 장점 등 긍정적인 평가가 명확한 경우

- negative:
  불만, 문제, 결함, 아쉬움, 불편함 등 부정적인 평가가 명확한 경우

- neutral:
  긍정이나 부정이 뚜렷하지 않은 단순 사실 전달이거나,
  긍정과 부정이 함께 존재하여 어느 한쪽이 명확하게 우세하지 않은 경우

confidence는 각 감정 분류에 대한 확신 정도를
0.0부터 1.0 사이의 숫자로 반환하세요.
"""

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema={
                "type": "object",
                "properties": {
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "integer",
                                },
                                "sentiment": {
                                    "type": "string",
                                    "enum": [
                                        "positive",
                                        "negative",
                                        "neutral",
                                    ],
                                },
                                "confidence": {
                                    "type": "number",
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                            },
                            "required": [
                                "id",
                                "sentiment",
                                "confidence",
                            ],
                        },
                    },
                },
                "required": [
                    "results",
                ],
            },
        ),
    )

    result = json.loads(response.text)

    return validate_batch_analysis_result(
        result,
        expected_ids,
    )

def analyze_reviews(reviews):
    """전체 리뷰를 한 번에 분석하고 실패 시 절반으로 나눠 재시도한다."""

    if not isinstance(reviews, list):
        raise TypeError("reviews는 리스트여야 합니다.")

    valid_reviews = []
    results = []
    failed_ids = []

    for review in reviews:
        if not isinstance(review, dict) or "id" not in review:
            raise ValueError(
                "각 리뷰는 id를 포함한 딕셔너리여야 합니다."
            )

        review_id = review["id"]
        review_text = review.get("review_text", "")

        if not isinstance(review_text, str) or not review_text.strip():
            failed_ids.append(review_id)
            continue

        valid_reviews.append({
            "id": review_id,
            "review_text": review_text,
        })

    if not valid_reviews:
        return {
            "results": results,
            "failed_ids": failed_ids,
        }

    try:
        # 1차: 유효한 리뷰 전체를 Gemini 한 번으로 분석
        batch_results = analyze_review_batch(valid_reviews)
        results.extend(batch_results)

    except Exception as error:
        logger.warning(
            "전체 리뷰 배치 분석에 실패했습니다. "
            "두 그룹으로 나누어 다시 시도합니다: %s",
            error,
        )

        midpoint = (len(valid_reviews) + 1) // 2

        batches = [
            valid_reviews[:midpoint],
            valid_reviews[midpoint:],
        ]

        for batch in batches:
            if not batch:
                continue

            try:
                batch_results = analyze_review_batch(batch)
                results.extend(batch_results)

            except Exception as batch_error:
                batch_ids = [
                    review["id"]
                    for review in batch
                ]

                logger.error(
                    "분할 배치 감정 분석 실패 "
                    "(id=%s): %s",
                    batch_ids,
                    batch_error,
                )

                failed_ids.extend(batch_ids)

    return {
        "results": results,
        "failed_ids": failed_ids,
    }

if __name__ == "__main__":
    test_reviews = [
        "음질이 생각보다 좋아요",
        "충전 케이스가 조금 큰 것 같아요",
        "고장난 제품이 배송되었습니다",
        "제품을 오늘 받아서 사용해봤습니다.",
        "배송은 빨랐지만 포장이 조금 찌그러져 왔어요",
    ]

    for review in test_reviews:
        result = analyze_review(review)

        print("리뷰:", review)
        print("분석 결과:", result)
        print()