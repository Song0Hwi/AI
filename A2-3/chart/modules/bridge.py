# ============================================================
# A 담당 · 외부 폴더(source/, prompt/) 호출 창구
#
# 이전 adapters.py 를 대체한다. 539줄 -> 이 파일.
#
# 무엇이 사라졌나
#   C(민규)와 합의해서 C 코드를 조금 고쳤더니, A쪽에서 하던 변환이
#   대부분 필요 없어졌다. 없앤 것들:
#
#     · id 매핑 73줄      -> C가 id 를 그대로 들고 다녀서 아예 불필요
#     · 부분 실패 흡수     -> C가 failed_ids 를 함께 돌려준다
#     · 배치 나누기        -> C가 직접 배치로 부른다 (아래 주석)
#     · stats 평면화 77줄  -> 리포트 형식은 리포트를 만드는 C가 정한다
#     · chart_paths 변환   -> C가 dict 도 받는다. 상대경로 계산만 A가 3줄
#     · insights None 방어 -> C가 기본값을 넣는다
#     · 차트/export 통과   -> A가 A를 부르는 껍데기였다. 직접 import 한다
#     · mock 분기         -> 아래 [2026-08-12] 참고
#
# 무엇이 남았나
#   · B(세인) 래퍼 — B의 함수는 파일 경로를 받고 파일을 쓴다.
#     A는 DB에 넣어야 해서 그 사이를 이어야 한다.
#     B와는 아직 이 합의를 하지 않았고, 지금 형태로도 잘 돌아간다.
#   · language 채우기 — C가 안 주는데 DB 컬럼에는 있다.
#
# [2026-08-12] mock 분기 제거
#   C의 Gemini 연결이 끝나서 대역(modules/mock_ai.py)을 걷어냈다.
#   대역을 남겨두면 "지금 도는 게 진짜 분석인가 대역인가" 를 실행할 때마다
#   플래그로 확인해야 하고, 규칙 기반 결과가 DB에 섞여 들어가도
#   model 컬럼을 열어보기 전까지는 아무도 모른다.
#   자가 점검과 테스트가 쓰던 대역은 각각 그 파일 안으로 옮겼다.
#   덕분에 analyzer() / extractor() 가 config 를 받을 이유도 없어졌다.
#
# 원칙은 그대로다. 의존 방향은 A -> B, A -> C 한 방향이다.
# B/C 는 A를 import 하지 않는다. 그래야 두 사람이 자기 폴더만으로
# 테스트할 수 있다.
# ============================================================

import re

from modules.logger import get_logger
from modules.paths import (DATA_CLEAN_DIR, DATA_RAW_DIR, ModuleNotProvided,
                           load_b_cleaner, load_b_importer, load_c_analyzer,
                           load_c_extractor, load_c_reporter)


logger = get_logger("bridge")

HANGUL = re.compile(r"[가-힣]")


def detect_language(text):
    """
    아주 단순한 언어 판별.

    C는 language 를 돌려주지 않는데 DB 스키마와 show 출력에는 칸이 있다.
    이것 하나 때문에 모델을 한 번 더 부르는 건 낭비라 한글 포함 여부만 본다.
    계약상 nullable 이라 틀려도 치명적이지 않다.
    """

    if not text:
        return None

    return "ko" if HANGUL.search(text) else "en"


# ============================================================
# B (세인) — source/src
# ============================================================
#
# B의 두 함수는 '파일 경로를 받아 파일을 쓰고 리스트를 돌려주는' 형태다.
# A는 DB에 넣어야 하니 경로를 만들어 주고 결과 리스트만 받는다.
# B가 만든 raw/clean JSONL 은 그대로 남아서, B가 혼자 돌릴 때와
# 산출물 위치가 달라지지 않는다.


def import_raw_file(file_path, output_path=None):
    """[B] CSV -> raw JSONL. (원본 dict 리스트, 저장 경로) 반환."""

    output_path = output_path or (DATA_RAW_DIR / "reviews.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # B는 FileNotFoundError / ValueError 를 던진다.
    # 그대로 올려보내고 main.py 가 종료 코드로 바꾼다.
    rows = load_b_importer().import_reviews(str(file_path), str(output_path))

    logger.info("B importer: %d건 읽음 -> %s", len(rows), output_path)

    return rows, output_path


def clean_raw_file(input_path=None, output_path=None):
    """[B] raw JSONL -> clean JSONL. (정제 dict 리스트, 저장 경로) 반환."""

    input_path = input_path or (DATA_RAW_DIR / "reviews.jsonl")
    output_path = output_path or (DATA_CLEAN_DIR / "reviews.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    records = load_b_cleaner().clean_reviews(str(input_path), str(output_path))

    logger.info("B cleaner: %d건 정제 -> %s", len(records), output_path)

    return records, output_path


def write_raw_jsonl(records, output_path):
    """
    DB의 raw 저장소를 B가 읽을 수 있는 JSONL 로 되돌린다.

    clean 명령(원본 CSV 없이 재정제)에서 쓴다.
    B의 clean_reviews 는 파일 경로만 받으므로 파일을 한 번 거쳐야 한다.
    """

    import json

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    return output_path


# ============================================================
# C (민규) — prompt
# ============================================================
#
# A가 배치를 나누지 않는 이유
#   C의 analyze_reviews() 가 한 프롬프트에 여러 건을 넣어 부르고,
#   실패하면 스스로 반으로 쪼개 다시 시도한다.
#   A가 앞에서 또 자르면 그 재시도 폭만 좁아질 뿐 이득이 없다.
#   진짜 배치는 C 영역에서만 가능하다.


def analyzer():
    """감정 분석 모듈 (prompt/analyzer.py)."""

    return load_c_analyzer()


def extractor():
    """인사이트 추출 모듈 (prompt/extractor.py)."""

    return load_c_extractor()


def reporter():
    """리포트 모듈 (prompt/reporter.py). 모델을 부르지 않는다."""

    return load_c_reporter()


__all__ = [
    "ModuleNotProvided",
    "detect_language",
    "import_raw_file",
    "clean_raw_file",
    "write_raw_jsonl",
    "analyzer",
    "extractor",
    "reporter",
]
