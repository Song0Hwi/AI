#!/usr/bin/env python3
"""
A 담당 통합 테스트.

무엇을 검증하는가
    B/C 코드의 정확도가 아니라, "A가 두 사람의 실제 함수를 계약 형태로
    잘 이어붙였는가" 를 본다. B/C의 자기 기능 테스트는 각자 가지고 있다.

    특히 다음 4가지가 핵심이다.
      1. B의 파일 기반 import/clean 을 거쳐 DB에 정확히 들어가는가
      2. C가 흔들려도 부분 실패가 failed_ids 로 바뀌는가
      3. chart_paths dict 가 리포트에서 상대 경로 리스트로 바뀌는가
      4. A의 5칸 stats 가 C 리포트용 평면 dict 로 안전하게 접히는가

    시각화/내보내기는 A로 이관됐으므로 여기서 직접 부른다.

[2026-08-12] mock_ai 제거에 따른 변경
    예전에는 modules/mock_ai.py 를 불러 감정 분석을 대신했다.
    C의 Gemini 연결이 끝나 그 파일을 걷어내면서, 테스트가 쓰던 대역은
    이 파일 안의 StubAnalyzer 로 옮겼다. 대역이 modules/ 에 있으면 그건
    제품 코드고, 언젠가 실행 경로로 새어 들어간다.

    C의 계약 중 API 를 부르기 전에 갈리는 부분(id 검사 · 빈 본문 ·
    배치 실패 시 반으로 쪼개기)은 실제 prompt/analyzer.py 로 확인한다.
    대역을 상대로 확인하면 "대역이 대역답게 도는가" 를 볼 뿐이다.

    키가 필요한 검사는 GEMINI_API_KEY 가 있을 때만 돈다.
    테스트 한 번에 과금되면 아무도 테스트를 안 돌리게 된다.

실행
    python chart/tests/test_integration.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import bridge                                         # noqa: E402
from modules.database import (fetch_reviews, init_db,              # noqa: E402
                              make_review_hash, save_clean,
                              save_sentiment_results)
from modules.interfaces import (validate_analysis_output,           # noqa: E402
                                validate_chart_paths, validate_insights,
                                validate_stats)
from modules.paths import DATA_CLEAN_DIR, REPO_ROOT                 # noqa: E402
from modules.stats import calculate_stats                           # noqa: E402
from modules.visualizer import CHART_ORDER                          # noqa: E402


CONFIG = {
    "ai": {"extract_max_reviews": 20},
    "cleaning": {"duplicate_keys":
                 ["product_name", "review_text", "review_date"]},
}


def has_api_key():
    """키가 있을 때만 도는 검사를 가르기 위한 확인."""

    try:
        from dotenv import load_dotenv

        load_dotenv()

    except ImportError:
        pass

    return bool(
        os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    )


HAS_API_KEY = has_api_key()
NEEDS_KEY = "GEMINI_API_KEY 가 없어 건너뜁니다 (실제 API 를 부릅니다)."


def load_clean_fixture(limit=None):
    """B가 실제로 만든 clean JSONL 을 읽는다."""

    path = DATA_CLEAN_DIR / "reviews.jsonl"

    if not path.exists():
        raise unittest.SkipTest(f"clean 데이터가 없습니다: {path}")

    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    return records[:limit] if limit else records


class TempDB:
    """테스트마다 임시 DB 파일을 쓴다. 실제 DB를 건드리지 않는다."""

    def __enter__(self):
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "test.db"
        init_db(self.path)
        return self.path

    def __exit__(self, *exc):
        self._dir.cleanup()


class StubAnalyzer:
    """
    감정 분석 대역. C의 analyze_reviews() 와 반환 모양만 같다.

    감정을 맞히려는 물건이 아니다. 저장 -> 집계 -> 차트 -> 리포트 배선을
    API 없이 끝까지 통과시키기 위한 자리다.
    세 감정을 돌려가며 넣는 이유도 그래야 감정 분포·추이·별점별 구성
    차트가 모두 그려져서 배선 확인이 되기 때문이다.
    """

    SENTIMENTS = ["positive", "neutral", "negative"]

    @staticmethod
    def analyze_reviews(reviews):

        if not isinstance(reviews, list):
            raise TypeError("reviews는 리스트여야 합니다.")

        results = []
        failed_ids = []

        for index, review in enumerate(reviews):

            if not isinstance(review, dict) or "id" not in review:
                raise ValueError(f"각 리뷰는 id 를 가진 dict 여야 합니다: {review!r}")

            text = review.get("review_text")

            if not isinstance(text, str) or not text.strip():
                failed_ids.append(review["id"])
                continue

            results.append({
                "id": review["id"],
                "sentiment": StubAnalyzer.SENTIMENTS[index % 3],
                "confidence": round(0.6 + 0.1 * (index % 4), 2),
            })

        return {"results": results, "failed_ids": failed_ids}


STUB_INSIGHTS = {
    "positive_keywords": ["보습", "흡수"],
    "negative_keywords": ["끈적임"],
    "summary": "테스트용 고정 인사이트입니다.",
    "improvements": ["가벼운 제형 검토", "향 강도 조정"],
}


def payload_of(reviews):
    """main.py cmd_analyze 와 같은 방식으로 넘길 키만 추린다."""

    return [
        {"id": review["id"], "review_text": review["review_text"]}
        for review in reviews
    ]


def analyzed_stats(db_path, limit=40):
    """clean 픽스처를 넣고 대역으로 분석해 stats 까지 만든다."""

    save_clean(load_clean_fixture(limit), "skip",
               CONFIG["cleaning"]["duplicate_keys"], db_path=db_path)

    rows = fetch_reviews(db_path=db_path, order_by="id")
    output = StubAnalyzer.analyze_reviews(payload_of(rows))

    save_sentiment_results(output["results"], model="stub", db_path=db_path)

    return calculate_stats(db_path=db_path)


# ============================================================
# 1. B 연결
# ============================================================

class TestBIntegration(unittest.TestCase):

    def test_clean_data_has_five_fields(self):
        """B의 clean 레코드 필드가 합의한 5개인지 확인한다."""

        record = load_clean_fixture(1)[0]

        self.assertEqual(
            set(record),
            {"rating", "review_text", "review_date",
             "product_name", "skin_type"},
        )
        self.assertIsInstance(record["rating"], int)

    def test_skin_type_survives_db_roundtrip(self):
        """
        skin_type 이 DB를 거쳐도 살아남는지 확인한다.

        A의 1차 스키마에는 skin_type 컬럼이 없었다.
        컬럼을 안 만들면 B가 정제한 정보를 A가 조용히 버리게 된다.
        """

        records = load_clean_fixture(10)

        with TempDB() as db_path:
            save_clean(records, "skip", CONFIG["cleaning"]["duplicate_keys"],
                       source_file="test", db_path=db_path)

            rows = fetch_reviews(db_path=db_path, order_by="id")

            self.assertEqual(len(rows), 10)
            self.assertTrue(all(row["skin_type"] for row in rows))
            self.assertEqual(rows[0]["skin_type"], records[0]["skin_type"])

    def test_duplicate_policy_skip(self):
        """같은 데이터를 두 번 넣어도 행이 늘지 않는지 확인한다."""

        records = load_clean_fixture(10)
        keys = CONFIG["cleaning"]["duplicate_keys"]

        with TempDB() as db_path:
            first = save_clean(records, "skip", keys, db_path=db_path)
            second = save_clean(records, "skip", keys, db_path=db_path)

            self.assertEqual(first["inserted"], 10)
            self.assertEqual(second["inserted"], 0)
            self.assertEqual(second["skipped"], 10)
            self.assertEqual(len(fetch_reviews(db_path=db_path)), 10)

    def test_hash_ignores_whitespace_and_case(self):
        """
        해시 정규화가 도는지 확인한다.

        "좋아요" 와 "좋아요 " 가 다른 리뷰로 잡히면
        같은 파일을 두 번 넣을 때마다 DB가 불어난다.
        """

        base = {"product_name": "토너", "review_text": "좋아요",
                "review_date": "2025-01-01"}
        noisy = {"product_name": " 토너 ", "review_text": "좋아요  ",
                 "review_date": "2025-01-01"}

        self.assertEqual(make_review_hash(base), make_review_hash(noisy))

    def test_hash_separates_same_text_different_product(self):
        """
        제품이 다르면 다른 리뷰로 잡히는지 확인한다.

        review_text 단독으로 해시를 걸면 서로 다른 제품에 달린
        "좋아요" 가 전부 한 건으로 뭉개진다.
        """

        one = {"product_name": "토너", "review_text": "좋아요",
               "review_date": "2025-01-01"}
        two = {"product_name": "크림", "review_text": "좋아요",
               "review_date": "2025-01-01"}

        self.assertNotEqual(make_review_hash(one), make_review_hash(two))


# ============================================================
# 2. C 연결 — API 를 부르기 전에 갈리는 계약
# ============================================================
#
# 아래 셋은 실제 prompt/analyzer.py 를 부르지만 네트워크를 타지 않는다.
# C가 Gemini 를 부르기 전에 입력을 먼저 검사하기 때문이다.
# 이 순서가 뒤집히면(먼저 부르고 나중에 검사) 빈 본문 한 건 때문에
# 요금이 나가므로, 순서 자체가 계약이다.


class TestCContract(unittest.TestCase):

    def test_missing_id_is_a_caller_bug(self):
        """
        id 가 없는 건 '이 리뷰의 실패' 가 아니라 부르는 쪽의 버그다.
        조용히 넘기면 어느 리뷰가 빠졌는지 아무도 모른다.
        """

        with self.assertRaises(ValueError):
            bridge.analyzer().analyze_reviews([{"review_text": "id 가 없다"}])

    def test_empty_text_goes_to_failed_ids(self):
        """빈 본문은 failed_ids 로. 예외를 던지지 않는다."""

        output = bridge.analyzer().analyze_reviews([
            {"id": 1, "review_text": "  "},
        ])

        self.assertEqual(output["failed_ids"], [1])
        self.assertEqual(output["results"], [])

    def test_batch_failure_falls_back_to_halves(self):
        """
        ★ 한 번 흔들렸다고 앞의 건을 버리지 않는다.

        C는 전체 배치가 실패하면 반으로 쪼개 다시 부른다.
        첫 호출만 실패하도록 바꿔두고, 나머지가 살아 돌아오는지 본다.
        """

        analyzer = bridge.analyzer()
        original = analyzer.analyze_review_batch
        calls = []

        def flaky(reviews):
            calls.append(len(reviews))

            if len(calls) == 1:
                raise RuntimeError("첫 배치 실패")

            return [
                {"id": review["id"], "sentiment": "neutral",
                 "confidence": 0.6}
                for review in reviews
            ]

        analyzer.analyze_review_batch = flaky

        try:
            output = analyzer.analyze_reviews([
                {"id": 1, "review_text": "좋아요 만족합니다"},
                {"id": 2, "review_text": "그럭저럭입니다"},
                {"id": 3, "review_text": "부드럽고 촉촉해요"},
            ])

        finally:
            analyzer.analyze_review_batch = original

        self.assertEqual(output["failed_ids"], [])
        self.assertEqual(
            sorted(item["id"] for item in output["results"]), [1, 2, 3]
        )
        self.assertGreater(len(calls), 1, "반으로 쪼개 다시 부르지 않았습니다.")

    def test_total_failure_accounts_for_every_id(self):
        """
        ★ 계약의 핵심. 전부 실패해도 id 는 사라지지 않는다.
        results 아니면 failed_ids 중 어딘가에는 있어야 한다.
        """

        analyzer = bridge.analyzer()
        original = analyzer.analyze_review_batch

        def always_fails(reviews):
            raise RuntimeError("계속 실패")

        analyzer.analyze_review_batch = always_fails

        try:
            output = analyzer.analyze_reviews([
                {"id": 7, "review_text": "본문 하나"},
                {"id": 8, "review_text": "본문 둘"},
            ])

        finally:
            analyzer.analyze_review_batch = original

        self.assertEqual(output["results"], [])
        self.assertEqual(sorted(output["failed_ids"]), [7, 8])
        self.assertEqual(validate_analysis_output(output), [])

    def test_extract_rejects_bad_input_before_calling_api(self):
        """
        입력 자체가 잘못된 경우만 예외다. 이것도 API 앞에서 갈린다.

        빈 리스트로 프롬프트를 만들어 부르면 요금만 나가고
        돌아오는 건 "리뷰가 없습니다" 뿐이다.
        """

        extractor = bridge.extractor()

        with self.assertRaises(ValueError):
            extractor.extract_insights([])

        with self.assertRaises(ValueError):
            extractor.extract_insights(["정상 리뷰", "   "])

    def test_rating_never_reaches_c(self):
        """
        ★ payload 에 rating 이 섞이지 않는다.

        별점이 프롬프트에 들어가면 모델이 그대로 따라가서
        '별점-감정 일치도' 가 항상 100% 가 되고 지표가 죽는다.
        """

        with TempDB() as db_path:
            save_clean(load_clean_fixture(5), "skip",
                       CONFIG["cleaning"]["duplicate_keys"], db_path=db_path)

            rows = fetch_reviews(db_path=db_path, order_by="id")
            payload = payload_of(rows)

            self.assertTrue(all(r.get("rating") is not None for r in rows))

            for item in payload:
                self.assertEqual(set(item), {"id", "review_text"})


@unittest.skipUnless(HAS_API_KEY, NEEDS_KEY)
class TestCLive(unittest.TestCase):
    """실제 Gemini 를 부른다. 키가 있을 때만 돈다."""

    def test_analyze_reviews_shape(self):
        reviews = [
            {"id": 100, "review_text": "정말 좋아요 추천합니다"},
            {"id": 200, "review_text": "최악이에요 환불하고 싶어요"},
        ]

        output = bridge.analyzer().analyze_reviews(reviews)

        self.assertEqual(validate_analysis_output(output), [])

        returned = {item["id"] for item in output["results"]}
        returned |= set(output["failed_ids"])

        self.assertEqual(returned, {100, 200})

    def test_extract_shape(self):
        insights = bridge.extractor().extract_insights(
            [record["review_text"] for record in load_clean_fixture(20)]
        )

        self.assertIsNotNone(insights)
        self.assertEqual(validate_insights(insights), [])


# ============================================================
# 3. 리포트 연결
# ============================================================

class FakeVisualizer:
    """
    차트 대역.

    실제 차트를 그리지 않고 빈 png 파일만 만든다.
    A쪽 배선(dict -> 상대 경로 리스트, 파일 존재 검증)만 확인하기 위한 것이다.
    이름과 순서는 진짜 visualizer 의 CHART_ORDER 를 그대로 쓴다.
    여기에 이름을 따로 적어두면 진짜 차트가 늘었을 때 이 대역만 뒤처진다.
    """

    @staticmethod
    def generate_charts(chart_data, output_dir, config):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        paths = {}

        for name in CHART_ORDER:
            path = output_dir / f"{name}.png"
            path.write_bytes(b"")
            paths[name] = str(path)

        return paths


class TestReportIntegration(unittest.TestCase):

    def test_stats_matches_contract(self):
        with TempDB() as db_path:
            self.assertEqual(validate_stats(analyzed_stats(db_path, 30)), [])

    def test_reporter_accepts_chart_paths_dict(self):
        """
        ★ C의 reporter 가 dict 를 받아준다.
        예전에는 리스트만 가정해서, dict 를 넘기면 키 문자열이
        이미지 경로 자리에 박혀 ![차트 1](sentiment_distribution) 이 나왔다.
        """

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            report_path = output_dir / "report.md"

            chart_paths = FakeVisualizer.generate_charts({}, output_dir, CONFIG)

            self.assertEqual(validate_chart_paths(chart_paths), [])

            relative = {
                name: Path(path).name for name, path in chart_paths.items()
            }
            text = bridge.reporter().generate_markdown_report(
                {}, {}, relative, report_path
            )

            # 리포트의 '차트 N' 순서는 dict 를 넣은 순서를 따른다.
            for index, name in enumerate(CHART_ORDER, start=1):
                self.assertIn(f"![차트 {index}]({name}.png)", text)

    def test_report_renders_with_charts_and_insights(self):
        with TempDB() as db_path, tempfile.TemporaryDirectory() as tmp:
            stats = analyzed_stats(db_path, 30)

            output_dir = Path(tmp)
            report_path = output_dir / "report.md"

            chart_paths = FakeVisualizer.generate_charts(
                stats["chart_data"], output_dir, CONFIG
            )

            # A의 5칸 stats 를 그대로 넘긴다. 평면화는 C가 한다.
            relative = {
                name: Path(path).name for name, path in chart_paths.items()
            }
            text = bridge.reporter().generate_markdown_report(
                stats, STUB_INSIGHTS, relative, report_path
            )

            self.assertTrue(Path(report_path).exists())
            self.assertIn("## 주요 통계", text)
            self.assertIn("## AI 인사이트", text)
            self.assertIn("![차트 1](kpi_summary.png)", text)

            # chart_data 가 리포트로 새지 않았는지 확인한다.
            self.assertNotIn("chart_data", text)
            self.assertNotIn("negative_ratio", text)
            self.assertNotIn("sentiment_ratios", text)

    def test_report_survives_missing_insights(self):
        """
        extract 를 안 돌린 상태에서 dashboard 를 실행해도 죽지 않아야 한다.

        C의 reporter 는 insights.get() 을 바로 부르므로
        None 이 그대로 가면 AttributeError 로 죽는다.
        """

        with TempDB() as db_path, tempfile.TemporaryDirectory() as tmp:
            stats = analyzed_stats(db_path, 30)
            report_path = Path(tmp) / "report.md"

            text = bridge.reporter().generate_markdown_report(
                stats, None, {}, report_path
            )

            self.assertTrue(Path(report_path).exists())
            self.assertIn("AI 인사이트", text)
            self.assertNotIn("## 시각화", text)

    def test_reporter_reads_only_its_own_sections(self):
        """
        C는 summary / quality / top_n 만 읽고 chart_data 는 안 읽는다.
        chart_data 를 통째로 지워도 리포트가 똑같이 나와야 한다.
        """

        with TempDB() as db_path, tempfile.TemporaryDirectory() as tmp:
            stats = analyzed_stats(db_path, 30)
            stripped = {k: v for k, v in stats.items() if k != "chart_data"}

            full = bridge.reporter().generate_markdown_report(
                stats, {}, {}, Path(tmp) / "a.md"
            )
            partial = bridge.reporter().generate_markdown_report(
                stripped, {}, {}, Path(tmp) / "b.md"
            )

            self.assertEqual(full, partial)


# ============================================================
# 4. 차트 · 내보내기 (A 이관분)
# ============================================================

class TestChartsAndExport(unittest.TestCase):

    def test_chart_data_covers_every_chart(self):
        """
        ★ stats 의 칸 이름과 visualizer 의 차트 이름이 어긋나지 않는다.

        이름이 하나만 달라도 그 차트는 조용히 안 그려진다.
        generate_charts 는 없는 칸을 '데이터 없음' 으로 보고 넘어가므로
        오타가 [FAIL] 이 아니라 '차트 6장' 으로 나타난다.
        """

        with TempDB() as db_path:
            chart_data = analyzed_stats(db_path, 40)["chart_data"]

            self.assertEqual(set(chart_data), set(CHART_ORDER))

    def test_charts_produce_every_file(self):
        from modules.visualizer import generate_charts

        with TempDB() as db_path, tempfile.TemporaryDirectory() as tmp:
            paths = generate_charts(
                analyzed_stats(db_path, 40)["chart_data"], tmp,
                {"visualization": {"dpi": 72, "save_format": "png"}},
            )

            self.assertEqual(validate_chart_paths(paths), [])
            self.assertEqual(set(paths), set(CHART_ORDER))

            # dict 순서가 곧 리포트의 '차트 N' 순서다.
            self.assertEqual(list(paths), CHART_ORDER)

            for path in paths.values():
                self.assertGreater(Path(path).stat().st_size, 1000)

    def test_kpi_never_recounts(self):
        """
        ★ KPI 타일 숫자는 summary / quality 에서 옮겨오기만 한다.

        차트가 자기 손으로 다시 세면 타일과 리포트가 갈라지고,
        둘 중 뭐가 맞는지 확인할 방법이 없어진다.
        """

        with TempDB() as db_path:
            stats = analyzed_stats(db_path, 40)
            kpi = stats["chart_data"]["kpi_summary"]
            summary = stats["summary"]

            self.assertEqual(kpi["total"], summary["total"])
            self.assertEqual(kpi["analyzed"], summary["analyzed"])
            self.assertEqual(kpi["avg_rating"], summary["avg_rating"])
            self.assertEqual(
                kpi["negative_ratio"], summary["sentiment_ratios"]["negative"]
            )
            self.assertEqual(
                kpi["rating_sentiment_agreement"],
                stats["quality"]["rating_sentiment_agreement"],
            )

    def test_group_charts_keep_series_and_totals_aligned(self):
        """
        제품별·피부타입별 계열 길이가 labels 와 어긋나면 zip 이
        조용히 잘라버려서 마지막 제품이 통째로 사라진다.
        """

        with TempDB() as db_path:
            chart_data = analyzed_stats(db_path, 40)["chart_data"]

            for key in ("product_sentiment", "skin_type_sentiment"):
                group = chart_data[key]
                count = len(group["labels"])

                self.assertGreater(count, 0, key)
                self.assertEqual(len(group["totals"]), count, key)

                for sentiment, series in group["series"].items():
                    self.assertEqual(len(series), count, f"{key}.{sentiment}")

                # 감정 합계가 totals 와 같아야 100% 막대가 성립한다.
                for index, total in enumerate(group["totals"]):
                    self.assertEqual(
                        sum(series[index]
                            for series in group["series"].values()),
                        total,
                        f"{key}[{index}]",
                    )

    def test_charts_skip_empty_data_instead_of_blank_image(self):
        """
        데이터가 없으면 빈 축만 있는 이미지를 만들지 않는다.

        추이는 날짜가 하나도 없으면 아예 건너뛴다.
        나머지는 '아직 분석된 리뷰가 없습니다' 를 적은 그림으로 남긴다.
        차트가 통째로 사라지면 리포트를 보는 사람이
        빠뜨린 건지 없는 건지 구분할 수 없기 때문이다.
        """

        from modules.visualizer import generate_charts

        with TempDB() as db_path, tempfile.TemporaryDirectory() as tmp:
            empty = calculate_stats(db_path=db_path)["chart_data"]

            paths = generate_charts(
                empty, tmp, {"visualization": {"dpi": 72}}
            )

            self.assertNotIn("sentiment_trend", paths)
            self.assertIn("sentiment_distribution", paths)

    def test_export_handles_all_none_optional_fields(self):
        """
        ★ 선택 필드가 전부 None 인 리뷰. int(record["rating"]) 을
        무조건 부르면 여기서 TypeError 로 터진다.
        """

        from modules.exporter import export_reviews

        record = [{
            "id": 1, "product_name": None, "review_text": "본문만 있는 리뷰",
            "rating": None, "review_date": None, "skin_type": None,
            "sentiment": None, "confidence": None, "language": None,
            "model": None, "analyzed_at": None,
        }]

        with tempfile.TemporaryDirectory() as tmp:

            for fmt in ("csv", "jsonl", "xlsx"):
                saved = export_reviews(record, fmt, Path(tmp) / f"o.{fmt}")
                self.assertTrue(Path(saved).exists(), fmt)

    def test_export_csv_is_excel_safe(self):
        """
        Excel 이 한글을 깨뜨리지 않도록 BOM 이 붙어야 한다.

        utf-8 로 쓰면 Excel 이 cp949 로 읽어 한글이 전부 깨진다.
        """

        from modules.exporter import export_reviews

        with TempDB() as db_path, tempfile.TemporaryDirectory() as tmp:
            save_clean(load_clean_fixture(5), "skip",
                       CONFIG["cleaning"]["duplicate_keys"], db_path=db_path)

            rows = fetch_reviews(db_path=db_path)
            path = Path(export_reviews(rows, "csv", Path(tmp) / "o.csv"))

            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertIn("제품명", path.read_text(encoding="utf-8-sig"))

    def test_export_rejects_unknown_format(self):
        from modules.exporter import export_reviews

        with tempfile.TemporaryDirectory() as tmp:

            with self.assertRaises(ValueError):
                export_reviews([], "docx", Path(tmp) / "o.docx")

    def test_export_returns_actual_saved_path(self):
        """
        요청 경로가 아니라 실제 저장 경로를 돌려줘야 한다.
        xlsx 가 openpyxl 부재로 csv 로 떨어질 수 있다.
        """

        from modules.exporter import export_reviews

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "o.jsonl"
            saved = export_reviews(
                [{"id": 1, "review_text": "테스트"}], "jsonl", target
            )

            self.assertEqual(Path(saved), target)
            self.assertTrue(Path(saved).exists())


# ============================================================
# 5. B/C 파일 무수정 확인
# ============================================================

class TestOwnershipBoundary(unittest.TestCase):

    def test_a_did_not_add_files_to_b_and_c_folders(self):
        """
        A가 B/C 폴더에 파일을 만들지 않았는지 확인한다.

        __init__.py 하나만 넣어도 그 폴더는 더 이상 그 사람만의 것이 아니게 되고
        머지 충돌이 시작된다.
        """

        b_files = {
            path.name
            for path in (REPO_ROOT / "source" / "src").glob("*.py")
        }
        c_files = {
            path.name for path in (REPO_ROOT / "prompt").glob("*.py")
        }

        self.assertNotIn("__init__.py", b_files)
        self.assertNotIn("__init__.py", c_files)
        self.assertTrue(b_files <= {"importer.py", "cleaner.py",
                                    "visualizer.py", "exporter.py"})
        self.assertTrue(c_files <= {"analyzer.py", "extractor.py",
                                    "reporter.py"})

    def test_removed_modules_stay_removed(self):
        """
        ★ 걷어낸 파일이 되살아나지 않았는지 확인한다.

        mock_ai — 대역이 제품 코드 폴더에 있으면 언젠가 실행 경로로 들어간다.
                  규칙 기반 결과가 DB에 섞여도 model 컬럼을 열기 전에는 모른다.
                  테스트 대역은 이 파일 안의 StubAnalyzer 하나면 충분하다.
        hashing — database.py 로 합쳤다. 두 곳에 해시 함수가 있으면
                  한쪽만 고쳐서 같은 리뷰가 두 개의 해시를 갖게 된다.
        """

        modules_dir = REPO_ROOT / "chart" / "modules"

        for name in ("mock_ai.py", "hashing.py"):
            self.assertFalse(
                (modules_dir / name).exists(),
                f"modules/{name} 가 다시 생겼습니다.",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
