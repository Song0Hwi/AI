import csv
import json
from pathlib import Path


REQUIRED_COLUMNS = [
    "rating",
    "review_text",
    "review_date",
    "product_name",
    "skin_type",
]


def load_review_file(file_path):
    """CSV 파일을 읽는다."""
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

    if path.suffix.lower() != ".csv":
        raise ValueError("현재는 CSV 파일만 지원합니다.")

    with open(path, "r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = list(reader)

    return rows


def validate_columns(rows):
    """필수 컬럼이 존재하는지 확인한다."""
    if not rows:
        raise ValueError("CSV 파일에 데이터가 없습니다.")

    columns = rows[0].keys()

    missing_columns = [
        column for column in REQUIRED_COLUMNS
        if column not in columns
    ]

    if missing_columns:
        raise ValueError(
            f"필수 컬럼이 없습니다: {missing_columns}"
        )


def save_raw_data(rows, output_path):
    """원본 데이터를 JSONL 파일로 저장한다."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as file:
        for row in rows:
            file.write(
                json.dumps(row, ensure_ascii=False) + "\n"
            )


def import_reviews(file_path, output_path):
    """CSV를 읽고 검증한 뒤 raw 데이터로 저장한다."""
    print(f"[INFO] 파일 로드: {file_path}")

    rows = load_review_file(file_path)

    print(f"[INFO] 총 {len(rows)}건 감지")

    validate_columns(rows)

    save_raw_data(rows, output_path)

    print(f"[INFO] raw 데이터 저장 완료: {output_path}")

    return rows