#!/usr/bin/env python3
"""
고객 리뷰 감정 분석 대시보드 - CLI 진입점. (명세 4.1)

A(영휘) 담당. 이 파일은 '명령을 해석해서 알맞은 함수를 부르는' 역할만 한다.
B(세인)의 source/src/ 코드는 한 줄도 수정하지 않고, C(민규)의 prompt/ 는
A와 합의한 세 군데만 바뀌었다. 호출은
modules/bridge.py 한 곳을 거친다.

실행 예
    python main.py import --file source/input/cosmetics_reviews_100.csv
    python main.py analyze --unanalyzed --limit 20
    python main.py extract --sentiment negative
    python main.py dashboard
"""

import argparse
import os
import sys
from pathlib import Path


# source/ 를 import 경로에 넣는다.
# 레포 루트에서 `python main.py` 로 실행해도 modules 를 찾게 하려는 것.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from modules.config import ConfigError, load_config           # noqa: E402
from modules.database import StorageError                     # noqa: E402
from modules.logger import get_logger, setup_logging          # noqa: E402
from modules.paths import ensure_directories                  # noqa: E402


logger = get_logger("main")


SENTIMENT_LABEL = {
    "positive": "긍정",
    "negative": "부정",
    "neutral": "중립",
}


def build_parser():
    """argparse 서브커맨드 파서를 만든다."""

    parser = argparse.ArgumentParser(
        prog="main.py",
        description="고객 리뷰 감정 분석 대시보드 (A 통합 CLI)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "사용 예시\n"
            "  python main.py import "
            "--file source/input/cosmetics_reviews_100.csv\n"
            "  python main.py analyze --unanalyzed --limit 20\n"
            "  python main.py list --sentiment negative --page 1 --size 5\n"
            "  python main.py extract --sentiment negative\n"
            "  python main.py dashboard\n"
        ),
    )

    parser.add_argument("--verbose", "-v", action="store_true",
                        help="DEBUG 로그까지 출력")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="WARNING 이상만 출력")

    # 전역 플래그를 서브커맨드 뒤에도 쓸 수 있게 하는 부모 파서.
    #
    # default=SUPPRESS 가 중요하다. 이게 없으면 서브파서의 기본값(False)이
    # 상위 파서가 이미 넣은 True 를 덮어써서
    # `main.py --verbose status` 가 무시된다.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--verbose", "-v", action="store_true",
                        default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument("--quiet", "-q", action="store_true",
                        default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # ---------------- import
    p = sub.add_parser("import", parents=[common],
                       help="CSV·Excel 수집 -> 정제 -> DB 저장 (B 모듈 사용)")
    p.add_argument("--file", "-f", required=True,
                   help="CSV 또는 Excel(.xlsx/.xlsm/.xltx) 파일 경로")
    p.add_argument("--policy", choices=["skip", "upsert"],
                   help="중복 처리 정책 (config 기본값 재정의)")
    p.add_argument("--keep-raw", action="store_true",
                   help="기존 raw 저장소를 비우지 않고 덧붙임")

    # ---------------- add
    p = sub.add_parser("add", parents=[common], help="리뷰 1건 직접 추가")
    p.add_argument("--text", "-t", required=True, help="리뷰 본문")
    p.add_argument("--rating", "-r", type=int, help="별점 1~5")
    p.add_argument("--date", "-d", help="작성일 (YYYY-MM-DD)")
    p.add_argument("--product", "-p", help="제품명")
    p.add_argument("--skin-type", help="피부 타입")

    # ---------------- clean
    p = sub.add_parser("clean", parents=[common],
                       help="raw 저장소 데이터를 다시 정제 (B 모듈 사용)")
    p.add_argument("--policy", choices=["skip", "upsert"])

    # ---------------- analyze
    p = sub.add_parser("analyze", parents=[common], help="AI 감정 분석")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="전체 리뷰")
    group.add_argument("--unanalyzed", action="store_true",
                       help="미분석 리뷰만 (기본값)")
    group.add_argument("--id", type=int, help="특정 리뷰 ID만")
    p.add_argument("--limit", "-l", type=int, help="최대 처리 건수")
    p.add_argument("--force", action="store_true", help="이미 분석된 것도 재분석")

    # ---------------- extract
    p = sub.add_parser("extract", parents=[common], help="AI 키워드/요약 추출")
    p.add_argument("--sentiment", "-s",
                   choices=["positive", "negative", "neutral"])
    p.add_argument("--date-from", help="시작일 (YYYY-MM-DD)")
    p.add_argument("--date-to", help="종료일 (YYYY-MM-DD)")
    p.add_argument("--product", "-p", help="제품명")
    p.add_argument("--limit", "-l", type=int)

    # ---------------- list
    p = sub.add_parser("list", parents=[common], help="리뷰 목록 조회")
    p.add_argument("--sentiment", "-s",
                   choices=["positive", "negative", "neutral"])
    p.add_argument("--rating", "-r", type=int)
    p.add_argument("--rating-min", type=int)
    p.add_argument("--date-from")
    p.add_argument("--date-to")
    p.add_argument("--product", "-p")
    p.add_argument("--skin-type")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--size", type=int, default=10)
    p.add_argument("--sort", default="review_date",
                   choices=["id", "rating", "review_date",
                            "sentiment", "confidence"])
    p.add_argument("--desc", action="store_true", help="내림차순 정렬")

    # ---------------- show
    p = sub.add_parser("show", parents=[common], help="리뷰 상세 조회")
    p.add_argument("id", type=int, help="리뷰 ID")

    # ---------------- stats
    p = sub.add_parser("stats", parents=[common],
                       help="통계 요약 + 경고 + 개선 우선순위")
    p.add_argument("--product", "-p", help="제품명으로 범위 제한")
    p.add_argument("--skin-type")
    p.add_argument("--date-from")
    p.add_argument("--date-to")

    # ---------------- dashboard
    p = sub.add_parser("dashboard", parents=[common],
                       help="대시보드 차트 + 종합 리포트 (A 차트 + C 리포트)")
    p.add_argument("--product", "-p")
    p.add_argument("--skin-type")
    p.add_argument("--date-from")
    p.add_argument("--date-to")
    p.add_argument("--no-charts", action="store_true", help="차트 생성 건너뛰기")

    # ---------------- export
    p = sub.add_parser("export", parents=[common],
                       help="데이터 내보내기 (csv/jsonl/xlsx)")
    p.add_argument("--format", "-F", default="csv",
                   choices=["csv", "jsonl", "xlsx"])
    p.add_argument("--sentiment", "-s",
                   choices=["positive", "negative", "neutral"])
    p.add_argument("--rating-min", type=int)
    p.add_argument("--date-from")
    p.add_argument("--date-to")
    p.add_argument("--product", "-p")
    p.add_argument("--output", "-o", help="저장 경로")

    # ---------------- review (AI 결과 사람 검수)
    p = sub.add_parser(
        "review", parents=[common],
        help="AI 결과 사람 검수 (표본 → 라벨 → 점수)",
        description=(
            "감정 분석 정확도를 사람 라벨과 비교해 잽니다.\n"
            "  1) review sample  으로 표본 CSV 를 만들고\n"
            "  2) '검수라벨' 열을 채운 뒤\n"
            "  3) review load 로 반영하고 review score 로 점수를 봅니다"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    action = p.add_subparsers(dest="review_action", metavar="<action>")

    q = action.add_parser("sample", parents=[common],
                          help="검수용 표본 CSV 만들기")
    q.add_argument("--size", type=int, default=30, help="표본 수 (기본 30)")
    q.add_argument("--output", "-o", help="저장 경로")

    q = action.add_parser("load", parents=[common],
                          help="채워진 검수 CSV 를 DB에 반영")
    q.add_argument("--file", "-f", required=True, help="검수 완료 CSV 경로")
    q.add_argument("--reviewer", required=True, help="검수자 이름")

    q = action.add_parser("score", parents=[common],
                          help="일치율 · 혼동 방향 · 버전별 비교")
    q.add_argument("--batch", help="특정 회차만")
    q.add_argument("--list", action="store_true", dest="list_batches",
                   help="검수 회차 목록만 보기")

    # ---------------- status
    sub.add_parser("status", parents=[common], help="저장소 현황 확인")

    return parser


# ================================================================ 보조


def _negative_keywords(insights):
    """
    가장 최근 extract 결과에서 부정 키워드만 꺼낸다.

    C가 뽑은 키워드를 A가 DB 본문으로 되짚어 영향도를 재는 데 쓴다.
    (평가 #17 · stats._build_keyword_impact)

    extract 를 안 돌렸으면 None 이 오고, 그러면 우선순위 칸은 빈 리스트가
    된다. 인사이트는 '있으면 좋은' 값이지 필수가 아니라서
    이것 때문에 stats 나 dashboard 가 멈추면 안 된다.
    """

    if not insights:
        return []

    keywords = insights.get("negative_keywords") or []

    if not isinstance(keywords, list):
        logger.warning(
            "negative_keywords 가 리스트가 아닙니다: %r", type(keywords).__name__
        )
        return []

    return [str(word) for word in keywords if str(word).strip()]


# ================================================================ 핸들러


def cmd_import(args, config):
    """
    CSV/Excel -> (B) raw JSONL -> DB raw 저장 -> (B) 정제 -> DB clean 저장

    [경계]
      B: 파일 읽기 / 검증 / 정제  (source/src/importer.py, cleaner.py)
      A: 파일 형식 흡수(Excel -> 임시 CSV), raw 보관, 해시 계산,
         중복 정책, DB 저장
    """

    from modules import bridge
    from modules.database import clear_raw, init_db, save_clean, save_raw
    from modules.paths import ModuleNotProvided

    policy = args.policy or config["duplicate_policy"]

    init_db()

    # ---- B: 파일 -> raw JSONL ----
    try:
        raw_rows, raw_path = bridge.import_raw_file(args.file)

    except ModuleNotProvided as error:
        logger.error("%s", error)
        return 1

    except (FileNotFoundError, ValueError) as error:
        # B의 importer 가 던지는 예외를 그대로 받아 종료 코드로 바꾼다.
        logger.error("%s", error)
        return 1

    # ---- A: raw 보관 ----
    if not args.keep_raw:
        clear_raw()

    save_raw(raw_rows, source_file=str(args.file))

    # ---- B: 정제 ----
    print("\n=== 정제 시작 (B 모듈) ===")

    try:
        clean_records, clean_path = bridge.clean_raw_file(raw_path)

    except (FileNotFoundError, ValueError) as error:
        logger.error("%s", error)
        return 1

    if not clean_records:
        logger.error("정제 결과가 0건입니다. 입력 파일을 확인하세요.")
        return 1

    # ---- A: DB 저장 ----
    result = save_clean(
        clean_records,
        policy=policy,
        duplicate_keys=config["cleaning"]["duplicate_keys"],
        source_file=str(args.file),
    )

    print(
        f"\n총 {len(raw_rows)}건 감지, "
        f"유효 {len(clean_records)}건, "
        f"저장 {result['inserted']}건 "
        f"(갱신 {result['updated']}건, 중복 스킵 {result['skipped']}건)"
    )
    print(f"중복 정책: {policy}")
    print(f"B 산출물: {raw_path} / {clean_path}")

    return 0


def cmd_add(args, config):
    """리뷰 1건을 직접 추가한다. B의 cleaner 를 거치지 않는 A 단독 경로."""

    from datetime import datetime

    from modules.database import init_db, save_clean

    cleaning = config["cleaning"]

    if args.rating is not None:

        if not cleaning["rating_min"] <= args.rating <= cleaning["rating_max"]:
            logger.error(
                "별점은 %d~%d 사이여야 합니다 (입력: %d)",
                cleaning["rating_min"], cleaning["rating_max"], args.rating,
            )
            return 1

    text = " ".join(args.text.split())

    if len(text) < cleaning["min_review_length"]:
        logger.error(
            "리뷰가 너무 짧습니다 (최소 %d자, 입력 %d자)",
            cleaning["min_review_length"], len(text),
        )
        return 1

    record = {
        "review_text": text,
        "rating": args.rating,
        "review_date": args.date or datetime.now().strftime("%Y-%m-%d"),
        "product_name": args.product,
        "skin_type": args.skin_type,
    }

    init_db()

    result = save_clean(
        [record],
        policy=config["duplicate_policy"],
        duplicate_keys=cleaning["duplicate_keys"],
        source_file="cli:add",
    )

    if result["inserted"]:
        print("리뷰를 추가했습니다.")

    elif result["updated"]:
        print("기존 리뷰를 갱신했습니다.")

    else:
        print("이미 동일한 리뷰가 있어 건너뛰었습니다.")

    return 0


def cmd_clean(args, config):
    """
    raw 저장소에 쌓인 원본을 다시 정제해 clean 저장소에 반영한다.
    원본 CSV 없이 재처리할 수 있다.

    B의 clean_reviews 는 파일 경로만 받으므로
    DB의 raw 를 JSONL 로 한 번 되돌린 뒤 넘긴다.
    """

    from modules import bridge
    from modules.database import fetch_raw_records, init_db, save_clean
    from modules.paths import DATA_RAW_DIR

    policy = args.policy or config["duplicate_policy"]

    init_db()

    records = fetch_raw_records()

    if not records:
        logger.error("raw 저장소가 비어 있습니다. 먼저 `import` 를 실행하세요.")
        return 1

    logger.info("raw 저장소에서 %d건을 불러왔습니다.", len(records))

    reprocess_path = DATA_RAW_DIR / "reviews_reprocess.jsonl"
    bridge.write_raw_jsonl(records, reprocess_path)

    print("\n=== 재정제 (B 모듈) ===")

    try:
        clean_records, clean_path = bridge.clean_raw_file(reprocess_path)

    except (FileNotFoundError, ValueError) as error:
        logger.error("%s", error)
        return 1

    result = save_clean(
        clean_records,
        policy=policy,
        duplicate_keys=config["cleaning"]["duplicate_keys"],
        source_file="raw_reprocess",
    )

    print(
        f"\n저장 {result['inserted']}건, "
        f"갱신 {result['updated']}건, "
        f"스킵 {result['skipped']}건 (정책: {policy})"
    )
    print(f"B 산출물: {clean_path}")

    return 0


def cmd_analyze(args, config):
    """
    AI 감정 분석.

    [경계]
      A: argparse 해석, DB 조회, 이미 분석된 것 걸러내기,
         넘길 키 추리기, language 채우기, 결과 저장, 종료 코드
      C: [{id, review_text}] 를 받아 {results, failed_ids} 를 돌려주기만 함
         DB도 CLI도 모른다

    C는 조회를 하지 않는다. A가 조회해서 필요한 두 키만 넘긴다.
    """

    from modules import bridge
    from modules.config import get_api_key
    from modules.database import (get_all_reviews, get_clean_review_by_id,
                                  get_unanalyzed_reviews, init_db,
                                  save_sentiment_results)
    from modules.interfaces import validate_analysis_output
    from modules.paths import ModuleNotProvided

    init_db()

    if not get_api_key(config):
        logger.error(
            "%s 환경변수가 없습니다. chart/.env 에 키를 넣으세요. "
            "(chart/.env.example 참고)",
            config["ai"]["api_key_env"],
        )
        return 1

    limit = (
        args.limit
        if args.limit is not None
        else config["analysis"]["default_limit"]
    )

    # ---- A: 대상 조회 ----
    if args.id is not None:
        review = get_clean_review_by_id(args.id)

        if review is None:
            logger.error("ID %d 리뷰를 찾을 수 없습니다.", args.id)
            return 1

        reviews = [review]

    elif args.all:
        reviews = get_all_reviews(limit=limit)

    else:
        reviews = get_unanalyzed_reviews(limit=limit)

    if not reviews:
        print("분석할 리뷰가 없습니다.")
        return 0

    # ---- A: 이미 분석된 것 걸러내기 (명세 4.4) ----
    skipped = 0

    if not args.force:
        before = len(reviews)
        reviews = [r for r in reviews if r.get("sentiment") is None]
        skipped = before - len(reviews)

        if skipped:
            logger.info(
                "이미 분석된 리뷰 %d건을 건너뜁니다 (--force 로 재분석)", skipped
            )

    if not reviews:
        print("새로 분석할 리뷰가 없습니다.")
        return 0

    # ---- C: 분석 ----
    #
    # [변경점] C가 id 를 그대로 들고 다녀서 zip 이 사라졌다.
    #
    # 넘기는 키를 두 개로 추리는 게 이 줄의 핵심이다.
    # get_unanalyzed_reviews() 는 rating 을 포함한 13개 키를 돌려주는데,
    # 그대로 넘기면 감정 분석 프롬프트가 별점을 볼 수 있게 된다.
    # 그러면 모델이 별점을 따라가서 '별점-감정 일치도' 가 항상 100% 가 되고
    # 지표가 순환논리로 죽는다. 여기서 구조적으로 막는다.
    payload = [
        {"id": review["id"], "review_text": review["review_text"]}
        for review in reviews
    ]

    try:
        output = bridge.analyzer().analyze_reviews(payload)

    except (ModuleNotProvided, TypeError, ValueError) as error:
        logger.error("%s", error)
        return 1

    # language 는 C가 돌려주지 않는다. A가 본문을 보고 채운다.
    text_of = {review["id"]: review["review_text"] for review in reviews}

    for item in output.get("results", []):
        item["language"] = bridge.detect_language(text_of.get(item["id"]))

    # ---- A: 계약 검증 (C 코드가 바뀌었을 때 조기에 잡는다) ----
    problems = validate_analysis_output(output)

    if problems:
        logger.error("C의 analyze_reviews() 결과가 계약과 다릅니다:")

        for problem in problems:
            logger.error("  - %s", problem)

        return 1

    # ---- A: 저장 ----
    saved = save_sentiment_results(
        output["results"], model=config["ai"]["model"]
    )

    failed = len(output["failed_ids"])

    print(
        f"\n분석 완료: {saved}건 저장, {failed}건 실패"
        + (f", {skipped}건 스킵" if skipped else "")
    )

    if failed:
        print(f"실패한 ID: {output['failed_ids']}")

    # 일부만 실패한 경우 2를 돌려줘 셸에서 구분할 수 있게 한다. (명세 4.4)
    return 0 if failed == 0 else 2


def cmd_extract(args, config):
    """
    AI 키워드/요약 추출.

    [경계]
      A: 조건 해석, 대상 조회, 결과 저장
      C: 리뷰 텍스트 목록을 받아 인사이트를 돌려주기만 함
    """

    import json

    from modules import bridge
    from modules.config import get_api_key
    from modules.database import (get_reviews_for_extract, init_db,
                                  save_extraction)
    from modules.interfaces import validate_insights
    from modules.paths import ModuleNotProvided

    init_db()

    if not get_api_key(config):
        logger.error(
            "%s 환경변수가 없습니다. chart/.env 에 키를 넣으세요. "
            "(chart/.env.example 참고)",
            config["ai"]["api_key_env"],
        )
        return 1

    # ---- A: 대상 조회 ----
    reviews = get_reviews_for_extract(
        sentiment=args.sentiment,
        date_from=args.date_from,
        date_to=args.date_to,
        product=args.product,
        limit=args.limit,
    )

    if not reviews:
        logger.error("추출할 리뷰가 없습니다. 조건을 확인하세요.")
        return 1

    scope_parts = []

    if args.sentiment:
        scope_parts.append(f"감정={args.sentiment}")

    if args.product:
        scope_parts.append(f"제품={args.product}")

    if args.date_from or args.date_to:
        scope_parts.append(
            f"기간={args.date_from or '처음'}~{args.date_to or '끝'}"
        )

    scope_label = ", ".join(scope_parts) if scope_parts else "전체"

    # ---- C: 추출 ----
    #
    # 99건을 통째로 프롬프트에 넣으면 요약이 뭉개진다. 앞에서 자른다.
    texts = [review["review_text"] for review in reviews]
    cap = int(config["ai"].get("extract_max_reviews", 60))

    if len(texts) > cap:
        logger.warning(
            "리뷰 %d건 중 앞의 %d건만 사용합니다 "
            "(config.ai.extract_max_reviews)", len(texts), cap,
        )
        texts = texts[:cap]

    try:
        insights = bridge.extractor().extract_insights(texts)

    except (ModuleNotProvided, ValueError) as error:
        logger.error("%s", error)
        return 1

    if insights is None:
        logger.error("추출에 실패했습니다.")
        return 1

    # ---- A: 계약 검증 ----
    problems = validate_insights(insights)

    if problems:
        logger.error("extract 결과가 계약과 다릅니다:")

        for problem in problems:
            logger.error("  - %s", problem)

        return 1

    # ---- A: 저장 ----
    scope_json = json.dumps(
        {
            "label": scope_label,
            "sentiment": args.sentiment,
            "product": args.product,
            "date_from": args.date_from,
            "date_to": args.date_to,
        },
        ensure_ascii=False,
    )

    extraction_id = save_extraction(
        scope=scope_json,
        review_count=len(reviews),
        data=insights,
        model=config["ai"]["model"],
    )

    logger.info("추출 완료 (extraction_id=%d)", extraction_id)

    print(f"\n=== AI 인사이트 ({scope_label}, {len(reviews)}건) ===")
    print(
        "\n[긍정 키워드] "
        + (", ".join(insights["positive_keywords"]) or "없음")
    )
    print(
        "[부정 키워드] "
        + (", ".join(insights["negative_keywords"]) or "없음")
    )
    print(f"\n[요약]\n{insights['summary']}")

    if insights["improvements"]:
        print("\n[개선 제안]")

        for item in insights["improvements"]:
            print(f"- {item}")

    return 0


def cmd_list(args, config):
    """리뷰 목록 조회. 필터 / 정렬 / 페이지네이션."""

    from modules.database import count_reviews, fetch_reviews, init_db

    init_db()

    filters = {
        "sentiment": args.sentiment,
        "rating": args.rating,
        "rating_min": args.rating_min,
        "date_from": args.date_from,
        "date_to": args.date_to,
        "product": args.product,
        "skin_type": args.skin_type,
    }

    total = count_reviews(**filters)

    if total == 0:
        print("조건에 맞는 리뷰가 없습니다.")
        return 0

    size = max(1, args.size)
    total_pages = (total + size - 1) // size
    page = min(max(1, args.page), total_pages)

    rows = fetch_reviews(
        **filters,
        order_by=args.sort,
        order_dir="desc" if args.desc else "asc",
        limit=size,
        offset=(page - 1) * size,
    )

    scope = []

    if args.sentiment:
        scope.append(f"감정: {args.sentiment}")

    if args.rating is not None:
        scope.append(f"별점: {args.rating}")

    if args.product:
        scope.append(f"제품: {args.product}")

    if args.skin_type:
        scope.append(f"피부타입: {args.skin_type}")

    prefix = ", ".join(scope) + ", " if scope else ""

    print(
        f"\n=== 리뷰 목록 ({prefix}{page}/{total_pages} 페이지, "
        f"총 {total}건) ==="
    )

    for row in rows:

        rating = int(row["rating"]) if row["rating"] is not None else 0
        stars = "★" * rating + "☆" * (5 - rating)

        if row["sentiment"]:
            analysis = f"{row['sentiment']} ({float(row['confidence']):.2f})"
        else:
            analysis = "미분석"

        text = row["review_text"]
        preview = text if len(text) <= 30 else text[:30] + "…"

        print(
            f"[{row['id']:>3}] {stars} | "
            f"{row['review_date'] or '날짜없음'} | "
            f"{preview} | {analysis}"
        )

    if total_pages > 1:

        if page < total_pages:
            print(f"\n다음 페이지: --page {page + 1}")
        else:
            print("\n마지막 페이지입니다.")

    return 0


def cmd_show(args, config):
    """리뷰 1건의 상세 정보."""

    from modules.database import fetch_reviews, init_db

    init_db()

    rows = fetch_reviews(review_id=args.id)

    if not rows:
        logger.error("ID %d 리뷰를 찾을 수 없습니다.", args.id)
        return 1

    row = rows[0]
    rating = int(row["rating"]) if row["rating"] is not None else 0

    print(f"\n=== 리뷰 상세 (ID: {row['id']}) ===")
    print(f"제품명   : {row['product_name'] or '(미지정)'}")
    print(f"피부타입 : {row['skin_type'] or '(미지정)'}")
    print(f"별점     : {'★' * rating}{'☆' * (5 - rating)} ({rating}점)")
    print(f"작성일   : {row['review_date'] or '(없음)'}")
    print(f"등록일시 : {row['created_at']}")

    print(f"\n[리뷰 원문]\n{row['review_text']}")

    print("\n[AI 감정 분석]")

    if row["sentiment"]:
        print(
            f"  감정     : {row['sentiment']} "
            f"({SENTIMENT_LABEL.get(row['sentiment'], '')})"
        )
        print(f"  확신도   : {float(row['confidence']):.2f}")
        print(f"  언어     : {row['language'] or '(미상)'}")
        print(f"  모델     : {row['model'] or '(미상)'}")
        print(f"  분석일시 : {row['analyzed_at']}")

    else:
        print("  아직 분석되지 않았습니다.")
        print(f"  실행: python main.py analyze --id {row['id']}")

    print(f"\n해시: {row['review_hash'][:16]}…")

    return 0


def cmd_stats(args, config):
    """통계 요약 출력. (명세 4.6) A 단독으로 동작한다."""

    from modules.database import fetch_latest_extraction, init_db
    from modules.stats import calculate_stats, format_stats

    init_db()

    stats = calculate_stats(
        {
            "product": args.product,
            "skin_type": args.skin_type,
            "date_from": args.date_from,
            "date_to": args.date_to,
        },
        top_n=config["analysis"]["top_n"],
        keywords=_negative_keywords(fetch_latest_extraction()),
        thresholds=config.get("alerts"),
    )

    print(format_stats(stats))

    return 0


def cmd_dashboard(args, config):
    """
    차트 생성 + 종합 리포트. (명세 4.7 / 4.8)

    [연결 흐름 - 회의 자료 4장 그대로]
      A: stats       = calculate_stats(filters)
      A: chart_paths = generate_charts(stats["chart_data"], output_dir, config)
      C: report      = generate_markdown_report(stats, insights, chart_paths, path)
      A: 전체 연결

    C 모듈이 아직 없어도 A는 실행된다. 없으면 경고만 남기고 넘어가며,
    파일을 올리는 순간 코드 수정 없이 붙는다.

    차트는 대시보드 7장이다. 데이터가 없어 못 그린 장은 이름을 찍어준다.
    조용히 빠지면 리포트에서 그 자리가 비어도 아무도 눈치채지 못한다.
    """

    from datetime import datetime

    import os

    from modules import bridge
    from modules.database import fetch_latest_extraction, init_db
    from modules.interfaces import validate_chart_paths, validate_stats
    from modules.paths import OUTPUT_DIR, ModuleNotProvided
    from modules.stats import calculate_stats, format_stats

    init_db()

    # 인사이트를 집계보다 먼저 가져온다.
    # C가 뽑은 부정 키워드로 A가 영향도를 재기 때문이다. (평가 #17)
    insights = fetch_latest_extraction()

    # ---- A: 집계 ----
    stats = calculate_stats(
        {
            "product": args.product,
            "skin_type": args.skin_type,
            "date_from": args.date_from,
            "date_to": args.date_to,
        },
        top_n=config["analysis"]["top_n"],
        keywords=_negative_keywords(insights),
        thresholds=config.get("alerts"),
    )

    if stats["summary"]["total"] == 0:
        logger.error("리뷰가 없습니다. 먼저 `import` 를 실행하세요.")
        return 1

    problems = validate_stats(stats)

    if problems:
        logger.error("calculate_stats() 가 계약을 어겼습니다:")

        for problem in problems:
            logger.error("  - %s", problem)

        return 1

    print(format_stats(stats))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ---- A: 차트 ----
    chart_paths = {}

    if not args.no_charts:

        try:
            from modules.visualizer import generate_charts

            chart_paths = generate_charts(
                stats["chart_data"], OUTPUT_DIR, config
            )

        except ImportError as error:
            # matplotlib 이 없어도 통계와 리포트는 나와야 한다.
            logger.warning(
                "차트 건너뜀 - %s (설치: pip install matplotlib)", error
            )
            chart_paths = {}

        else:
            issues = validate_chart_paths(chart_paths)

            if issues:
                logger.error("B의 generate_charts() 가 계약을 어겼습니다:")

                for issue in issues:
                    logger.error("  - %s", issue)

                return 1

            from modules.visualizer import CHART_ORDER

            print(f"\n[생성된 차트] {len(chart_paths)}/{len(CHART_ORDER)}장")

            for name, chart_path in chart_paths.items():
                print(f"  - {chart_path}")

            missing = [
                name for name in CHART_ORDER if name not in chart_paths
            ]

            if missing:
                print(
                    f"  (건너뜀: {', '.join(missing)} "
                    f"- 해당 데이터가 없습니다. 자세한 이유는 로그 참고)"
                )

    # ---- C: 리포트 ----
    if insights is None:
        logger.warning(
            "AI 인사이트가 없습니다. `extract` 를 먼저 실행하면 "
            "리포트에 키워드/요약이 포함됩니다."
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = OUTPUT_DIR / f"report_{stamp}.md"

    # 차트 경로를 리포트 파일 기준 상대 경로로 바꾼다.
    # 절대 경로를 그대로 넣으면 내 PC 에서만 이미지가 보이고
    # GitHub 이나 다른 팀원 화면에서는 전부 깨진다.
    relative_charts = {
        name: os.path.relpath(str(path), str(OUTPUT_DIR)).replace(os.sep, "/")
        for name, path in (chart_paths or {}).items()
    }

    try:
        text = bridge.reporter().generate_markdown_report(
            stats, insights, relative_charts, report_path
        )

    except ModuleNotProvided as error:
        logger.warning("리포트 건너뜀 - %s", error)
        return 0

    print(f"\n[리포트] {report_path} ({len(text):,}자)")

    return 0


def cmd_export(args, config):
    """
    데이터 내보내기. (명세 4.9)

    [경계]
      A: 조건 해석, DB 조회
      B: 받은 리스트를 파일로 쓰기만 함
    """

    from modules.database import get_reviews_for_export, init_db
    from modules.exporter import export_reviews
    from modules.paths import OUTPUT_DIR

    init_db()

    # ---- A: 조회 ----
    records = get_reviews_for_export(
        sentiment=args.sentiment,
        rating_min=args.rating_min,
        date_from=args.date_from,
        date_to=args.date_to,
        product=args.product,
    )

    if not records:
        logger.error("내보낼 리뷰가 없습니다. 조건을 확인하세요.")
        return 1

    output_path = args.output or (
        OUTPUT_DIR / f"reviews_export.{args.format}"
    )

    # ---- A: 파일 쓰기 ----
    try:
        saved = export_reviews(records, args.format, output_path)

    except ValueError as error:
        logger.error("%s", error)
        return 1

    # xlsx 요청이 openpyxl 부재로 csv 로 떨어질 수 있어
    # 요청 경로가 아니라 '실제 저장된 경로' 를 출력한다.
    print(f"{len(records)}건을 내보냈습니다: {saved}")

    return 0


def cmd_review(args, config):
    """
    AI 결과를 사람이 검수한다. (평가 #16)

    [경계]
      A: 표본 추출 · CSV 입출력 · 라벨 저장 · 지표 산출
      사람: '검수라벨' 열을 채우는 것

    C의 프롬프트를 고치는 것은 C 영역이다. A는 고칠 근거가 되는
    숫자(일치율 · 혼동 방향 · 버전별 비교)를 내놓는 데까지 한다.
    """

    from modules import audit
    from modules.database import (fetch_human_labels, fetch_label_batches,
                                  get_reviews_with_analysis, init_db,
                                  save_human_labels)
    from modules.paths import OUTPUT_DIR

    init_db()

    action = getattr(args, "review_action", None)

    if not action:
        print(
            "\n검수는 세 단계입니다.\n"
            "  python main.py review sample --size 30\n"
            "  (만들어진 CSV 의 '검수라벨' 열을 채웁니다)\n"
            "  python main.py review load --file <경로> --reviewer <이름>\n"
            "  python main.py review score\n"
        )
        return 1

    # ---- 표본 뽑기 ----
    if action == "sample":
        reviews = get_reviews_with_analysis()

        if not reviews:
            logger.error(
                "감정 분석된 리뷰가 없습니다. 먼저 `analyze` 를 실행하세요."
            )
            return 1

        sample = audit.pick_sample(reviews, size=args.size)
        batch = audit.new_batch_id()

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = args.output or (OUTPUT_DIR / f"review_{batch}.csv")

        audit.write_sample_csv(sample, batch, output_path)

        print(f"\n검수 표본 {len(sample)}건: {output_path}")
        print(f"회차: {batch}")
        print(
            "\n'검수라벨' 열에 긍정 / 중립 / 부정 을 적고 저장한 뒤:\n"
            f"  python main.py review load --file \"{output_path}\" "
            f"--reviewer <이름>"
        )
        print(
            "\n두 사람이 따로 매기면 검수자 간 일치율까지 나옵니다. "
            "같은 파일을 복사해 각자 채우고 --reviewer 만 다르게 넣으세요."
        )

        return 0

    # ---- 라벨 반영 ----
    if action == "load":

        try:
            records, problems = audit.read_labeled_csv(
                args.file, args.reviewer
            )

        except (FileNotFoundError, ValueError) as error:
            logger.error("%s", error)
            return 1

        for problem in problems:
            logger.warning("%s", problem)

        if not records:
            logger.error(
                "반영할 라벨이 없습니다. '검수라벨' 열이 비어 있는지 확인하세요."
            )
            return 1

        result = save_human_labels(records)

        for review_id, reason in result["failed"]:
            logger.error("id %s 저장 실패: %s", review_id, reason)

        print(
            f"\n검수 라벨 {result['saved']}건 반영 "
            f"(검수자: {args.reviewer})"
        )

        if problems:
            print(f"알아보지 못한 라벨 {len(problems)}건은 건너뛰었습니다.")

        print("\n점수 보기: python main.py review score")

        # 못 알아본 라벨이 있으면 일부 실패로 알린다.
        return 0 if not problems and not result["failed"] else 2

    # ---- 점수 ----
    if args.list_batches:
        batches = fetch_label_batches()

        if not batches:
            print("검수 기록이 없습니다.")
            return 0

        print("\n=== 검수 회차 ===")

        for row in batches:
            print(
                f"{row['batch']}  리뷰 {row['reviews']}건 · "
                f"라벨 {row['labels']}개 · 검수자 {row['reviewers']}명 · "
                f"{row['labeled_at']}"
            )

        return 0

    labels = fetch_human_labels(batch=args.batch)
    result = audit.score(labels)

    print(audit.format_score(result))
    audit.log_score(result)

    if result is None:
        return 1

    # 일치율이 기준 미달이면 종료 코드 2. 셸에서 구분할 수 있게 한다.
    return 0 if result["agreement"] >= result["agreement_floor"] else 2


def cmd_status(args, config):
    """저장소 현황과 폴더 배치를 출력한다."""

    from modules.config import get_api_key
    from modules.database import database_summary, get_db_path, init_db
    from modules.paths import (ModuleNotProvided, describe_layout,
                               load_b_cleaner, load_b_importer,
                               load_c_analyzer, load_c_extractor,
                               load_c_reporter)

    init_db()

    summary = database_summary()

    print("\n=== 저장소 현황 ===")
    print(f"DB 경로       : {get_db_path()}")
    print(
        f"설정 파일     : {config['_config_path']} "
        f"({'있음' if config['_config_file_found'] else '없음 - 기본값 사용'})"
    )
    print(f"중복 정책     : {config['duplicate_policy']}")
    print(f"AI 모델       : {config['ai']['model']}")
    print(
        f"API 키        : "
        f"{'설정됨' if get_api_key(config) else '없음 (chart/.env 에 넣으세요)'}"
    )

    print("\n=== 폴더 배치 ===")

    for label, path in describe_layout().items():
        mark = "" if path.exists() else "  <- 없음"
        print(f"{label:<12}: {path}{mark}")

    print("\n=== 담당자 모듈 ===")

    def import_a(module_name):
        """A 소유 모듈은 평범한 import 로 확인한다."""

        import importlib

        return lambda: importlib.import_module(f"modules.{module_name}")

    checks = [
        ("B", "source/src/importer.import_reviews",
         load_b_importer, "import_reviews"),
        ("B", "source/src/cleaner.clean_reviews",
         load_b_cleaner, "clean_reviews"),
        ("C", "prompt/analyzer.analyze_reviews",
         load_c_analyzer, "analyze_reviews"),
        ("C", "prompt/extractor.extract_insights",
         load_c_extractor, "extract_insights"),
        ("C", "prompt/reporter.generate_markdown_report",
         load_c_reporter, "generate_markdown_report"),
        ("A", "modules/visualizer.generate_charts",
         import_a("visualizer"), "generate_charts"),
        ("A", "modules/exporter.export_reviews",
         import_a("exporter"), "export_reviews"),
    ]

    for owner, label, loader, function_name in checks:

        try:
            module = loader()

            if callable(getattr(module, function_name, None)):
                state = "OK"
            else:
                state = f"{function_name}() 없음"

        except (ModuleNotProvided, ImportError):
            state = "파일 없음"

        except Exception as error:
            state = f"로드 실패: {error}"

        print(f"[{owner}] {label:<42} {state}")

    font_name, korean_ok = __import__(
        "modules.visualizer", fromlist=["resolve_font"]
    ).resolve_font()

    print(
        f"\n차트 한글 폰트  : "
        f"{font_name if korean_ok else '없음 (영문 라벨로 대체)'}"
    )

    print("\n=== 데이터 ===")
    print(f"raw 리뷰      : {summary['raw_reviews']}건")
    print(f"clean 리뷰    : {summary['reviews']}건")
    print(f"감정 분석     : {summary['analyses']}건")
    print(f"키워드 추출   : {summary['extractions']}회")
    print(f"사람 검수 라벨: {summary['human_labels']}개")

    if summary["reviews"] and summary["analyses"] < summary["reviews"]:

        remaining = summary["reviews"] - summary["analyses"]

        print(
            f"\n미분석 {remaining}건 -> "
            f"python main.py analyze --unanalyzed --limit {remaining}"
        )

    return 0


HANDLERS = {
    "import": cmd_import,
    "add": cmd_add,
    "clean": cmd_clean,
    "analyze": cmd_analyze,
    "extract": cmd_extract,
    "list": cmd_list,
    "show": cmd_show,
    "stats": cmd_stats,
    "dashboard": cmd_dashboard,
    "export": cmd_export,
    "review": cmd_review,
    "status": cmd_status,
}


def main(argv=None):
    """CLI 진입점. 종료 코드를 반환한다."""

    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    try:
        config = load_config()

    except ConfigError as error:
        # 로거 설정 전이므로 stderr 로 직접 출력한다.
        print(f"[ERROR] 설정 오류: {error}", file=sys.stderr)
        return 1

    setup_logging(config, verbose=args.verbose, quiet=args.quiet)
    ensure_directories()

    if not config["_config_file_found"]:
        logger.warning(
            "config.json 이 없어 기본 설정으로 동작합니다: %s",
            config["_config_path"],
        )

    handler = HANDLERS[args.command]

    try:
        return handler(args, config)

    except StorageError as error:
        # 파일 시스템 때문에 DB가 안 열리는 경우.
        # 스택 트레이스 대신 해결 방법을 보여준다.
        for line in str(error).splitlines():
            print(f"[ERROR] {line}", file=sys.stderr)

        return 1

    except BrokenPipeError:
        # `main.py list | head` 처럼 파이프 상대가 먼저 닫히는 건 정상이다.
        # 그냥 두면 종료 시 stdout 을 flush 하다 또 터져 트레이스가 두 번 나온다.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 141

    except KeyboardInterrupt:
        logger.warning("사용자가 중단했습니다.")
        return 130

    except Exception as error:
        logger.exception("예상치 못한 오류: %s", error)
        return 1


if __name__ == "__main__":
    # 인자 없는 sys.exit() 는 종료 코드 0(성공)을 뜻한다.
    # 셸 체이닝(&&)이나 CI 에서 실패를 감지하려면 0이 아닌 값을 줘야 한다.
    sys.exit(main())
