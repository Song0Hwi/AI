#!/usr/bin/env python3
"""
계약 자가 점검. (INTERFACE.md 8번)

    python chart/check_contract.py         # 전체
    python chart/check_contract.py --b     # B(세인) 영역만
    python chart/check_contract.py --c     # C(민규) 영역만
    python chart/check_contract.py --a     # A(영휘) 영역만

무엇을 보는가
    "아직 안 만든 것" 은 실패로 치지 않는다. [SKIP] 으로 넘어간다.
    "만들었는데 약속과 다른 것" 만 [FAIL] 로 잡는다.

    B/C가 이미 통과시킨 자기 기능 테스트를 다시 돌리는 게 아니다.
    A가 그 함수를 실제로 부를 때 깨지는 지점만 본다.

수요일 전달 조건: 자기 영역에 [FAIL] 이 없을 것.
"""

import argparse
import inspect
import json
import sys
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

from modules.paths import (DATA_CLEAN_DIR, ModuleNotProvided,  # noqa: E402
                           load_b_cleaner, load_b_importer, load_c_analyzer,
                           load_c_extractor, load_c_reporter)


PASS = 0
FAIL = 0
SKIP = 0
TODO = 0


def ok(title):
    global PASS
    PASS += 1
    print(f"[OK]   {title}")


def fail(title, problems):
    global FAIL
    FAIL += 1
    print(f"[FAIL] {title} - 문제 {len(problems)}건")

    for problem in problems:
        print(f"         - {problem}")


def skip(title, reason):
    global SKIP
    SKIP += 1
    print(f"[SKIP] {title} - {reason}")


def todo(title, reason):
    """
    '약속과 다른 것' 이 아니라 '아직 부탁하지 않은 것'.

    [FAIL] 과 섞으면 안 된다. 수요일 전달 조건이 "자기 영역에 FAIL 없을 것"
    이라, 새로 부탁하는 항목이 FAIL 로 찍히면 다 만든 사람도 빨간불이 뜬다.
    그러면 FAIL 을 보고도 아무도 안 움직이게 된다.
    """

    global TODO
    TODO += 1
    print(f"[TODO] {title}")
    print(f"         - {reason}")


def check(title, problems):
    if problems:
        fail(title, problems)
    else:
        ok(title)


def has_params(function, names):
    """함수가 주어진 이름의 인자를 받는지 본다."""

    try:
        signature = inspect.signature(function)

    except (TypeError, ValueError):
        return []

    missing = [
        name for name in names if name not in signature.parameters
    ]

    return [
        f"{function.__name__}() 에 인자 {name} 이(가) 없습니다. "
        f"현재 시그니처: {signature}"
        for name in missing
    ]


def sample_reviews(limit=5):
    """B의 clean 데이터에서 표본을 뽑는다. 없으면 내장 표본."""

    path = DATA_CLEAN_DIR / "reviews.jsonl"

    if path.exists():
        records = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        if records:
            return records[:limit]

    return [
        {"rating": 5, "review_text": "흡수가 빠르고 촉촉해서 좋아요.",
         "review_date": "2025-05-03", "product_name": "토너",
         "skin_type": "건성"},
        {"rating": 2, "review_text": "제 피부에는 너무 무겁게 느껴졌어요.",
         "review_date": "2025-05-04", "product_name": "토너",
         "skin_type": "지성"},
    ]


# ============================================================
# A 점검용 대역
# ============================================================
#
# modules/mock_ai.py 를 걷어내면서 자가 점검이 쓰던 대역을 이 파일 안으로
# 옮겼다. 대역이 modules/ 에 있으면 그건 제품 코드고, 언젠가 실행 경로로
# 새어 들어간다. 점검 파일 안에 있으면 점검 말고는 쓸 수가 없다.
#
# --a 에서 보려는 것은 "C가 감정을 잘 맞추는가" 가 아니라
# "C가 약속한 모양으로 돌려줬을 때 A의 저장·집계·차트·리포트가 이어지는가" 다.
# 그래서 실제 Gemini 를 부르지 않는다. 점검 한 번에 20건씩 과금될 이유가 없고,
# 네트워크가 흔들린다고 A의 [FAIL] 이 뜨면 그 신호는 못 믿게 된다.
#
# C 자신의 계약은 --c 에서 확인한다. 거기서도 API 는 부르지 않는다.

STUB_SENTIMENTS = ["positive", "neutral", "negative"]


def stub_analysis(payload):
    """C의 analyze_reviews() 가 돌려줄 모양을 그대로 흉내 낸다."""

    results = []
    failed_ids = []

    for index, review in enumerate(payload):
        text = review.get("review_text")

        if not isinstance(text, str) or not text.strip():
            failed_ids.append(review["id"])
            continue

        results.append({
            "id": review["id"],
            # 감정을 돌려가며 넣는다. 세 값이 모두 나와야
            # 감정 분포·추이·별점별 구성 차트가 전부 그려진다.
            "sentiment": STUB_SENTIMENTS[index % 3],
            "confidence": round(0.6 + 0.1 * (index % 4), 2),
        })

    return {"results": results, "failed_ids": failed_ids}


STUB_INSIGHTS = {
    "positive_keywords": ["보습", "흡수"],
    "negative_keywords": ["끈적임"],
    "summary": "점검용 고정 인사이트입니다.",
    "improvements": ["가벼운 제형 검토", "향 강도 조정"],
}


# reporter 에 넘길 stats 표본.
#
# 예전에는 여기에 {"전체 리뷰 수": "99건"} 같은 평면 dict 를 넘겼다.
# 그건 어댑터가 stats 를 납작하게 펴서 주던 시절의 모양이고,
# 지금 계약은 5칸짜리다. 그래서 이 점검이 늘 [FAIL] 로 떴는데
# C 코드가 아니라 표본이 옛날 것이었다.
# 자가 점검이 틀린 곳을 가리키면 아무도 안 보게 된다.
SAMPLE_STATS = {
    "meta": {
        "schema_version": 3,
        "generated_at": "2026-08-12 00:00:00",
        "filters": {"product": None, "skin_type": None,
                    "date_from": None, "date_to": None},
    },
    "summary": {
        "total": 4,
        "analyzed": 4,
        "unanalyzed": 0,
        "analysis_rate": 1.0,
        "avg_rating": 3.5,
        "avg_confidence": 0.8,
        "sentiment_counts": {"positive": 2, "neutral": 1, "negative": 1},
        "sentiment_ratios": {"positive": 0.5, "neutral": 0.25,
                             "negative": 0.25},
        "rating_counts": {1: 1, 2: 0, 3: 1, 4: 1, 5: 1},
    },
    "chart_data": {},
    "quality": {
        "rating_sentiment_agreement": 0.75,
        "data_completeness": 1.0,
        "avg_review_length": 42.0,
    },
    "top_n": {
        "worst_reviews": [{
            "id": 1, "product_name": "토너",
            "review_text": "제 피부에는 너무 무겁게 느껴졌어요.",
            "rating": 1, "review_date": "2025-05-04",
            "skin_type": "지성", "sentiment": "negative", "confidence": 0.8,
        }],
        "product_counts": [("토너", 4)],
        "skin_type_counts": [("건성", 2), ("지성", 2)],
    },
}


# ============================================================
# B (세인)
# ============================================================

def check_b():
    print("\n=== B (세인) · source/src ===")

    # ---- importer
    try:
        importer = load_b_importer()

    except ModuleNotProvided as error:
        skip("importer.import_reviews()", str(error))

    else:
        function = getattr(importer, "import_reviews", None)

        if function is None:
            fail("importer.import_reviews()",
                 ["import_reviews() 가 없습니다."])

        else:
            check(
                "importer.import_reviews() 시그니처",
                has_params(function, ["file_path", "output_path"]),
            )

    # ---- cleaner
    try:
        cleaner = load_b_cleaner()

    except ModuleNotProvided as error:
        skip("cleaner.clean_reviews()", str(error))

    else:
        function = getattr(cleaner, "clean_reviews", None)

        if function is None:
            fail("cleaner.clean_reviews()", ["clean_reviews() 가 없습니다."])

        else:
            problems = has_params(function, ["input_path", "output_path"])

            # 실제로 한 번 돌려본다. 반환 레코드의 키가 합의한 5개인가.
            with tempfile.TemporaryDirectory() as tmp:
                raw = Path(tmp) / "raw.jsonl"
                clean = Path(tmp) / "clean.jsonl"

                raw.write_text(
                    "\n".join(
                        json.dumps(record, ensure_ascii=False)
                        for record in sample_reviews()
                    ),
                    encoding="utf-8",
                )

                try:
                    records = function(str(raw), str(clean))

                except Exception as error:
                    problems.append(f"clean_reviews() 실행 중 오류: {error}")

                else:

                    if not records:
                        problems.append("clean_reviews() 가 0건을 돌려줬습니다.")

                    else:
                        expected = {"rating", "review_text", "review_date",
                                    "product_name", "skin_type"}
                        actual = set(records[0])

                        if actual != expected:
                            problems.append(
                                f"clean 레코드 필드가 합의와 다릅니다. "
                                f"없음={sorted(expected - actual)} "
                                f"추가={sorted(actual - expected)} "
                                f"(A의 DB 컬럼과 맞춰야 합니다)"
                            )

                        if not isinstance(records[0].get("rating"), int):
                            problems.append(
                                "rating 이 int 가 아닙니다. "
                                "문자열이면 별점 집계가 전부 어긋납니다."
                            )

            check("cleaner.clean_reviews() 동작과 반환 형태", problems)

    print("  · 차트/export 는 A로 이관되었습니다. --a 에서 점검합니다.")


# ============================================================
# C (민규)
# ============================================================

def check_c():
    print("\n=== C (민규) · prompt ===")

    # ---- analyzer
    try:
        analyzer = load_c_analyzer()

    except ModuleNotProvided as error:
        skip("analyzer.analyze_reviews()", str(error))

    except Exception as error:
        # 라이브러리 미설치는 '계약 위반' 이 아니라 '환경 미구성' 이다.
        # FAIL 로 잡으면 수요일 전달 조건("자기 영역에 FAIL 없을 것")을
        # 코드가 아니라 pip 상태가 좌우하게 된다.
        skip("analyzer 모듈 로드",
             f"{error} → pip install -r chart/requirements.txt")

    else:
        problems = []

        for name in ("analyze_review", "analyze_reviews",
                     "validate_analysis_result"):

            if not callable(getattr(analyzer, name, None)):
                problems.append(f"{name}() 가 없습니다.")

        check("analyzer 공개 함수", problems)

        # 검증기는 API 호출 없이 돌려볼 수 있다.
        validate = getattr(analyzer, "validate_analysis_result", None)

        if callable(validate):
            problems = []

            try:
                validate({"sentiment": "positive", "confidence": 0.9})

            except Exception as error:
                problems.append(f"정상 결과를 거부했습니다: {error}")

            for bad in ({"sentiment": "좋음", "confidence": 0.9},
                        {"sentiment": "positive", "confidence": 1.5},
                        {"sentiment": "positive", "confidence": "높음"}):

                try:
                    validate(bad)
                    problems.append(f"잘못된 결과를 통과시켰습니다: {bad}")

                except Exception:
                    pass

            check("analyzer.validate_analysis_result()", problems)

        # analyze_reviews() 의 계약 중 API 를 부르기 전에 갈리는 두 갈래는
        # 키 없이도 확인할 수 있다. C가 Gemini 를 부르기 전에
        # id 검사와 빈 본문 검사를 먼저 하기 때문이다.
        #
        #   id 가 없는 dict  -> 부르는 쪽(A)의 버그      -> 예외
        #   본문이 빈 문자열 -> 이 한 건의 실패          -> failed_ids
        #
        # 이 둘이 뒤바뀌면 어느 리뷰가 빠졌는지 아무도 모르게 된다.
        batch = getattr(analyzer, "analyze_reviews", None)

        if callable(batch):
            problems = []

            try:
                batch([{"review_text": "id 가 없다"}])
                problems.append(
                    "id 없는 dict 를 통과시켰습니다. 예외를 던져야 합니다."
                )

            except ValueError:
                pass

            except Exception as error:
                problems.append(
                    f"id 없는 dict 에 ValueError 가 아닌 예외: {error!r}"
                )

            try:
                output = batch([{"id": 1, "review_text": "   "}])

                if output.get("failed_ids") != [1]:
                    problems.append(
                        f"빈 본문이 failed_ids 로 가지 않았습니다: {output}"
                    )

                if output.get("results"):
                    problems.append(
                        f"빈 본문인데 results 가 있습니다: {output['results']}"
                    )

            except Exception as error:
                problems.append(
                    f"빈 본문 한 건에 예외를 던졌습니다: {error!r} "
                    f"(그 id 만 failed_ids 로 보내야 합니다)"
                )

            check("analyzer.analyze_reviews() 실패 처리 (API 호출 없음)",
                  problems)

    # ---- extractor
    try:
        extractor = load_c_extractor()

    except ModuleNotProvided as error:
        skip("extractor.extract_insights()", str(error))

    except Exception as error:
        skip("extractor 모듈 로드",
             f"{error} → pip install -r chart/requirements.txt")

    else:
        problems = []

        if not callable(getattr(extractor, "extract_insights", None)):
            problems.append("extract_insights() 가 없습니다.")

        validate = getattr(extractor, "validate_insight_result", None)

        if callable(validate):

            # 계약(C_인터페이스.md 2번)은 네 키의 타입만 정한다.
            # 개수 하한은 합의에 없다. 여기서 걸리면 C의 검증기가
            # 합의보다 엄격하다는 뜻이고, 그러면 모델이 개선 제안을
            # 1개만 준 날 extract 가 통째로 None 이 되어 실패한다.
            try:
                validate({
                    "positive_keywords": ["보습"],
                    "negative_keywords": [],
                    "summary": "요약",
                    "improvements": ["가벼운 제형 검토"],
                })

            except Exception as error:
                problems.append(
                    f"계약상 정상인 인사이트를 거부했습니다: {error} "
                    f"(합의에 없는 조건입니다. 계약을 고치거나 "
                    f"검증기를 맞춰야 합니다)"
                )

        check("extractor 공개 함수", problems)

    # ---- reporter
    try:
        reporter = load_c_reporter()

    except ModuleNotProvided as error:
        skip("reporter.generate_markdown_report()", str(error))

    else:
        function = getattr(reporter, "generate_markdown_report", None)

        if function is None:
            fail("reporter.generate_markdown_report()",
                 ["generate_markdown_report() 가 없습니다."])

        else:
            problems = has_params(
                function, ["stats", "insights", "chart_paths", "output_path"]
            )

            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "report.md"

                try:
                    text = function(
                        SAMPLE_STATS, STUB_INSIGHTS, ["chart.png"], str(path)
                    )

                    if not path.exists():
                        problems.append(
                            "output_path 를 줬는데 파일이 생기지 않았습니다."
                        )

                    if not isinstance(text, str):
                        problems.append(
                            "Markdown 문자열을 돌려주지 않았습니다."
                        )

                    elif "![" not in text:
                        problems.append(
                            "chart_paths 를 줬는데 이미지 링크가 없습니다."
                        )

                except Exception as error:
                    problems.append(
                        f"generate_markdown_report() 실행 중 오류: {error}"
                    )

            check("reporter.generate_markdown_report() 동작", problems)

            check_report_requests(function)


def check_report_requests(generate):
    """
    A가 이미 넘기고 있는데 리포트가 쓰지 않는 값 3가지.

    A쪽에서 더 넘길 것은 없다. 지금도 다 가고 있다.
    쓸지 말지가 리포트를 만드는 쪽의 몫이라 [TODO] 로만 남긴다.
    자세한 내용과 목표 출력 예시는 C_인터페이스.md 6번에 있다.
    """

    import copy

    # ---- ① chart_paths 의 키
    # 파일명에 키를 넣으면 안 된다. 경로만 찍어도 통과해 버린다.
    paths = {"kpi_summary": "a.png", "sentiment_distribution": "b.png"}
    text = generate(SAMPLE_STATS, STUB_INSIGHTS, paths, None)

    if all(name in text for name in paths):
        ok("리포트가 chart_paths 의 이름을 쓴다")

    else:
        todo(
            "리포트가 chart_paths 의 이름을 쓴다",
            "지금은 list(chart_paths.values()) 로 값만 뽑아 '차트 1, 차트 2' "
            "로 번호를 매깁니다. 데이터가 없어 한 장이 빠지면 그 뒤 번호가 "
            "전부 밀리고, 리포트만 봐서는 차트 6이 뭔지 알 수 없습니다.",
        )

    # ---- ② meta
    text = generate(SAMPLE_STATS, STUB_INSIGHTS, {}, None)
    generated_at = SAMPLE_STATS["meta"]["generated_at"]

    if generated_at in text:
        ok("리포트가 meta(생성 시각·필터)를 쓴다")

    else:
        todo(
            "리포트가 meta(생성 시각·필터)를 쓴다",
            "stats['meta'] 에 generated_at 과 filters 가 들어 있는데 "
            "한 번도 읽지 않습니다. 그래서 --product 로 뽑은 리포트와 "
            "전체 리포트가 파일 안에서 구분되지 않습니다.",
        )

    # ---- ③ 선택 필드가 None 인 리뷰
    nullable = copy.deepcopy(SAMPLE_STATS)
    nullable["top_n"]["worst_reviews"][0]["product_name"] = None

    text = generate(nullable, STUB_INSIGHTS, {}, None)

    if "None" not in text:
        ok("product_name 이 None 이어도 리포트에 'None' 이 안 찍힌다")

    else:
        todo(
            "product_name 이 None 이어도 리포트에 'None' 이 안 찍힌다",
            "product_name / review_date / skin_type 은 계약상 None 일 수 "
            "있습니다. f-string 에 그대로 넣으면 문자열 'None' 이 박힙니다. "
            "`add` 로 넣은 리뷰가 여기 해당합니다.",
        )


# ============================================================
# A (영휘)
# ============================================================

def check_a():
    print("\n=== A (영휘) · chart ===")

    from modules import bridge
    from modules.database import (fetch_reviews, init_db, save_clean,
                                  save_sentiment_results)
    from modules.interfaces import (validate_analysis_output,
                                    validate_insights, validate_stats)
    from modules.stats import calculate_stats

    config = {
        "ai": {"extract_max_reviews": 20},
        "cleaning": {"duplicate_keys":
                     ["product_name", "review_text", "review_date"]},
    }

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "check.db"
        init_db(db_path)

        records = sample_reviews(limit=20)

        save_clean(records, "skip", config["cleaning"]["duplicate_keys"],
                   db_path=db_path)

        rows = fetch_reviews(db_path=db_path, order_by="id")

        problems = []

        if len(rows) != len(records):
            problems.append(
                f"저장 {len(records)}건 중 {len(rows)}건만 조회됩니다."
            )

        if rows and rows[0].get("skin_type") != records[0].get("skin_type"):
            problems.append("skin_type 이 DB 왕복에서 사라졌습니다.")

        check("database 저장/조회 왕복", problems)

        # C의 결과 모양(id · failed_ids)을 A가 받아 넘기는 구간.
        # 여기서 부르는 것은 대역이다. 위 STUB 주석 참고.
        payload = [
            {"id": row["id"], "review_text": row["review_text"]}
            for row in rows
        ]
        output = stub_analysis(payload)

        problems = []

        if not isinstance(output, dict):
            problems.append(
                f"analyze_reviews() 는 dict 를 돌려줘야 합니다 "
                f"(현재: {type(output).__name__})"
            )
            output = {"results": [], "failed_ids": []}

        returned = {item["id"] for item in output.get("results", [])}
        returned |= set(output.get("failed_ids", []))
        missing = {row["id"] for row in rows} - returned

        if missing:
            problems.append(
                f"결과에도 failed_ids 에도 없는 id 가 있습니다: {sorted(missing)}"
            )

        for item in output.get("results", []):
            item["language"] = bridge.detect_language(
                next(r["review_text"] for r in rows if r["id"] == item["id"])
            )

        problems.extend(validate_analysis_output(output))
        check("analyze_reviews() 반환 형태 (id · failed_ids)", problems)

        save_sentiment_results(output["results"], model="check_contract",
                               db_path=db_path)

        stats = calculate_stats(db_path=db_path)
        check("stats.calculate_stats() 반환 형태", validate_stats(stats))

        insights = STUB_INSIGHTS
        check("extract_insights() 반환 형태", validate_insights(insights))

        report_path = Path(tmp) / "report.md"

        try:
            # A의 5칸 stats 를 그대로 넘긴다. 평면화는 C가 한다.
            text = bridge.reporter().generate_markdown_report(
                stats, insights, {}, report_path
            )
            problems = []

            if not Path(report_path).exists():
                problems.append("리포트 파일이 생기지 않았습니다.")

            if "chart_data" in text or "negative_ratio" in text:
                problems.append(
                    "차트 영역(chart_data)이 리포트로 새어 나갔습니다."
                )

            if "sentiment_ratios" in text:
                problems.append("영어 키가 리포트에 그대로 나왔습니다.")

        except ModuleNotProvided as error:
            problems = [str(error)]

        check("generate_markdown_report() 연결", problems)

        try:
            bridge.reporter().generate_markdown_report(
                stats, None, {}, report_path
            )
            ok("insights 가 None 이어도 리포트가 생성됨")

        except Exception as error:
            fail("insights 가 None 이어도 리포트가 생성됨", [str(error)])

        # ---- 차트 (A 이관) ----
        from modules.interfaces import validate_chart_paths

        problems = []

        try:
            from modules.visualizer import generate_charts, resolve_font

            problems = has_params(
                generate_charts, ["chart_data", "output_dir", "config"]
            )

            chart_dir = Path(tmp) / "charts"
            paths = generate_charts(
                stats["chart_data"], chart_dir,
                {"visualization": {"dpi": 80, "save_format": "png"}},
            )
            problems.extend(validate_chart_paths(paths))

            font_name, korean_ok = resolve_font()

            if not korean_ok:
                print("         (참고: 한글 폰트가 없어 영문 라벨로 그렸습니다)")

        except ImportError as error:
            skip("visualizer.generate_charts()",
                 f"matplotlib 이 없습니다: {error}")
            problems = None

        except Exception as error:
            problems = [f"generate_charts() 실행 중 오류: {error}"]

        if problems is not None:
            check("visualizer.generate_charts() 반환 형태", problems)

        # ---- export (A 이관) ----
        #
        # 선택 필드가 전부 None 인 리뷰를 처리하는지 본다.
        # int(record["rating"]) 을 무조건 부르면 여기서 터진다.
        from modules.exporter import export_reviews

        problems = has_params(
            export_reviews, ["records", "fmt", "output_path"]
        )

        none_record = [{
            "id": 1, "product_name": None, "review_text": "테스트 리뷰입니다",
            "rating": None, "review_date": None, "skin_type": None,
            "sentiment": None, "confidence": None, "language": None,
            "model": None, "analyzed_at": None,
        }]

        for fmt in ("csv", "jsonl", "xlsx"):

            try:
                saved = export_reviews(
                    none_record, fmt, Path(tmp) / f"none_test.{fmt}"
                )

                if not Path(saved).exists():
                    problems.append(f"{fmt}: 파일이 생기지 않았습니다.")

            except Exception as error:
                problems.append(
                    f"{fmt}: 실행 중 오류: {error} "
                    f"(선택 필드가 None 인 리뷰를 처리하는지 확인하세요)"
                )

        try:
            export_reviews([], "docx", Path(tmp) / "x.docx")
            problems.append("지원하지 않는 형식을 통과시켰습니다.")

        except ValueError:
            pass

        except Exception as error:
            problems.append(f"형식 검증이 ValueError 가 아닙니다: {error!r}")

        check("exporter.export_reviews() None 안전성 · 3포맷", problems)


def main():
    parser = argparse.ArgumentParser(description="계약 자가 점검")
    parser.add_argument("--a", action="store_true", help="A 영역만")
    parser.add_argument("--b", action="store_true", help="B 영역만")
    parser.add_argument("--c", action="store_true", help="C 영역만")

    args = parser.parse_args()

    selected = args.a or args.b or args.c

    print("=" * 56)
    print(" 계약 자가 점검 (INTERFACE.md 8번)")
    print(" 미구현은 [SKIP], 새로 부탁하는 것은 [TODO] 입니다.")
    print(" [FAIL] 만 고치면 전달 조건은 충족합니다.")
    print("=" * 56)

    if args.b or not selected:
        check_b()

    if args.c or not selected:
        check_c()

    if args.a or not selected:
        check_a()

    print("\n" + "=" * 56)
    print(f" 통과 {PASS} · 실패 {FAIL} · 미구현 {SKIP} · 요청 {TODO}")

    if TODO:
        print(" [TODO] 는 실패가 아닙니다. C_인터페이스.md 6번을 보세요.")

    print("=" * 56)

    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
