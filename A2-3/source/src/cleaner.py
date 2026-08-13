import json
import re
from datetime import datetime
from pathlib import Path


MIN_REVIEW_LENGTH = 5


def normalize_text(text):
    if text is None:
        return ""

    text = str(text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def validate_rating(rating):
    try:
        rating = int(rating)
        return 1 <= rating <= 5
    except (ValueError, TypeError):
        return False


def normalize_date(date_text):
    if not date_text:
        return None

    date_text = str(date_text).strip()

    date_formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
    ]

    for date_format in date_formats:
        try:
            date = datetime.strptime(date_text, date_format)
            return date.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


def clean_review(review):
    review_text = normalize_text(review.get("review_text"))

    if not review_text:
        return None

    if len(review_text) < MIN_REVIEW_LENGTH:
        return None

    if not validate_rating(review.get("rating")):
        return None

    normalized_date = normalize_date(review.get("review_date"))

    if normalized_date is None:
        return None

    return {
        "rating": int(review["rating"]),
        "review_text": review_text,
        "review_date": normalized_date,
        "product_name": normalize_text(review.get("product_name")),
        "skin_type": normalize_text(review.get("skin_type")),
    }


def remove_duplicates(reviews):
    unique_reviews = []
    seen = set()

    for review in reviews:
        duplicate_key = (
            review["review_text"],
            review["product_name"],
            review["review_date"],
        )

        if duplicate_key in seen:
            continue

        seen.add(duplicate_key)
        unique_reviews.append(review)

    return unique_reviews


def clean_reviews(input_path, output_path):
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists():
        raise FileNotFoundError(
            f"raw 파일을 찾을 수 없습니다: {input_path}"
        )

    cleaned_reviews = []
    skipped = 0

    with open(input_path, "r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue

            review = json.loads(line)
            cleaned = clean_review(review)

            if cleaned is None:
                skipped += 1
                continue

            cleaned_reviews.append(cleaned)

    before_duplicate = len(cleaned_reviews)

    cleaned_reviews = remove_duplicates(cleaned_reviews)

    duplicate_count = before_duplicate - len(cleaned_reviews)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(output_path, "w", encoding="utf-8") as file:
        for review in cleaned_reviews:
            file.write(
                json.dumps(
                    review,
                    ensure_ascii=False
                ) + "\n"
            )

    total_count = len(cleaned_reviews) + skipped + duplicate_count

    print("========================================")
    print("          데이터 정제 결과")
    print("========================================")
    print(f"정제 대상: {total_count}건")
    print(f"정제 완료: {len(cleaned_reviews)}건")
    print(f"유효하지 않은 데이터: {skipped}건")
    print(f"중복 제거: {duplicate_count}건")
    print(f"최종 clean 데이터: {len(cleaned_reviews)}건")
    print(f"저장 위치: {output_path}")
    print("========================================")

    return cleaned_reviews