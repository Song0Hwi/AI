# ============================================================
# A 담당 · 계약 검증기
#
# 이 파일은 실행되는 문서다. INTERFACE.md 와 어긋나면 코드가 기준이다.
#
# 검증 대상이 두 층으로 나뉜다.
#   1) A 자신의 산출물   : calculate_stats() 반환 형태
#   2) 어댑터 통과 후 형태: analyze_reviews() / extract_insights() 결과
#
# 어댑터를 거친 뒤를 검증하는 이유
#   B/C 원본 함수의 모양은 이미 A의 계약과 다르다.
#   원본을 직접 검사하면 통과할 수가 없다.
#   대신 "어댑터를 통과한 뒤에는 반드시 이 모양" 을 보장하면,
#   B/C가 자기 코드를 바꿔도 어댑터에서 먼저 걸린다.
# ============================================================

import os


SCHEMA_VERSION = 4

ALLOWED_SENTIMENTS = {"positive", "negative", "neutral"}

# [2026-08-12] REVIEW_RECORD_EXAMPLE / NULLABLE_KEYS / validate_review_record
# 를 뺐다. 셋 다 아무 데서도 부르지 않는 '문서용' 코드였다.
# DB 레코드의 모양은 C_인터페이스.md 3번에 적혀 있고, 그쪽은 사람이 읽는다.
# 실행되지 않는 문서를 코드로 두면 스키마가 바뀌어도 아무도 안 고친다.


# ------------------------------------------------------------ stats

def validate_stats(stats):
    """calculate_stats() 반환 형태를 본다. (A 자신의 산출물)"""

    problems = []

    if not isinstance(stats, dict):
        return ["stats 가 dict 가 아닙니다."]

    for section in ("meta", "summary", "chart_data", "quality",
                    "top_n", "alerts"):

        if section not in stats:
            problems.append(f"칸 누락: {section}")

    if problems:
        return problems

    meta = stats["meta"]

    if meta.get("schema_version") != SCHEMA_VERSION:
        problems.append(
            f"schema_version 이 {SCHEMA_VERSION} 이 아닙니다: "
            f"{meta.get('schema_version')}"
        )

    summary = stats["summary"]

    for key in ("total", "analyzed", "unanalyzed", "analysis_rate",
                "avg_rating", "avg_confidence", "sentiment_counts",
                "sentiment_ratios", "rating_counts"):

        if key not in summary:
            problems.append(f"summary.{key} 누락")

    if summary.get("total") is not None:

        if (
            summary.get("analyzed", 0) + summary.get("unanalyzed", 0)
            != summary["total"]
        ):
            problems.append(
                "summary: analyzed + unanalyzed 가 total 과 다릅니다."
            )

    for sentiment in ("positive", "neutral", "negative"):

        if sentiment not in summary.get("sentiment_counts", {}):
            problems.append(f"summary.sentiment_counts.{sentiment} 누락")

    for star in range(1, 6):

        if star not in summary.get("rating_counts", {}):
            problems.append(f"summary.rating_counts[{star}] 누락")

    chart = stats["chart_data"]

    # 칸 이름은 modules/visualizer.py 의 CHART_ORDER 와 같아야 한다.
    # 이름이 어긋나면 그 차트만 조용히 안 그려지고 리포트에서도 빠진다.
    for key in ("kpi_summary", "sentiment_distribution",
                "sentiment_trend",
                "rating_distribution", "rating_sentiment",
                "product_sentiment", "skin_type_sentiment"):

        if key not in chart:
            problems.append(f"chart_data.{key} 누락 (차트 한 장과 1:1)")

    # KPI 는 summary / quality 에서 옮겨온 값이라 '있는가' 만 본다.
    # 값이 맞는지는 summary 검사가 이미 하고 있다.
    kpi = chart.get("kpi_summary", {})

    for key in ("total", "analyzed", "analysis_rate", "avg_rating",
                "avg_confidence", "positive_ratio", "negative_ratio",
                "rating_sentiment_agreement"):

        if key not in kpi:
            problems.append(f"chart_data.kpi_summary.{key} 누락")

    if kpi.get("total") is not None and kpi["total"] != summary.get("total"):
        problems.append(
            "chart_data.kpi_summary.total 이 summary.total 과 다릅니다. "
            "KPI 는 다시 세지 않고 옮겨오기만 해야 합니다."
        )

    rating_distribution = chart.get("rating_distribution", {})

    if len(rating_distribution.get("values", [])) != 5:
        problems.append(
            "chart_data.rating_distribution.values 는 길이 5 고정입니다."
        )

    for key in ("product_sentiment", "skin_type_sentiment"):
        group = chart.get(key, {})
        label_count = len(group.get("labels", []))

        if len(group.get("totals", [])) != label_count:
            problems.append(
                f"chart_data.{key}: totals 길이가 labels 와 다릅니다."
            )

        for sentiment, series in group.get("series", {}).items():

            if len(series) != label_count:
                problems.append(
                    f"chart_data.{key}.series.{sentiment} 길이가 "
                    f"labels 와 다릅니다."
                )

    distribution = chart.get("sentiment_distribution", {})

    if (
        len(distribution.get("labels", []))
        != len(distribution.get("values", []))
    ):
        problems.append(
            "chart_data.sentiment_distribution: labels 와 values 길이가 다릅니다."
        )

    trend = chart.get("sentiment_trend", {})
    label_count = len(trend.get("labels", []))

    if len(trend.get("negative_ratio", [])) != label_count:
        problems.append(
            "chart_data.sentiment_trend: negative_ratio 길이가 labels 와 다릅니다."
        )

    for sentiment, series in trend.get("series", {}).items():

        if len(series) != label_count:
            problems.append(
                f"chart_data.sentiment_trend.series.{sentiment} 길이가 "
                f"labels 와 다릅니다."
            )

    matrix = chart.get("rating_sentiment", {})

    for sentiment, series in matrix.get("series", {}).items():

        if len(series) != 5:
            problems.append(
                f"chart_data.rating_sentiment.series.{sentiment} 는 "
                f"길이 5 고정입니다."
            )

    quality = stats["quality"]

    if len(quality) < 2:
        problems.append("quality 지표는 2개 이상이어야 합니다. (명세 4.8)")

    if not stats["top_n"]:
        problems.append("top_n 집계는 1개 이상이어야 합니다. (명세 4.8)")

    problems.extend(_validate_keyword_impact(stats["top_n"]))
    problems.extend(_validate_alerts(stats["alerts"]))

    return problems


def _validate_keyword_impact(top_n):
    """부정 키워드 영향도. keywords 를 안 넘기면 빈 리스트가 정상이다."""

    problems = []
    rows = top_n.get("keyword_impact")

    if rows is None:
        return ["top_n.keyword_impact 누락 (없으면 빈 리스트여야 합니다)"]

    if not isinstance(rows, list):
        return ["top_n.keyword_impact 는 리스트여야 합니다."]

    previous = None

    for index, row in enumerate(rows):

        for key in ("keyword", "reviews", "share", "avg_rating",
                    "rating_gap", "negative_ratio", "priority"):

            if key not in row:
                problems.append(f"top_n.keyword_impact[{index}].{key} 누락")

        priority = row.get("priority")

        if isinstance(priority, (int, float)):

            if not 0.0 <= priority <= 1.0:
                problems.append(
                    f"top_n.keyword_impact[{index}].priority 범위 초과: "
                    f"{priority}"
                )

            # 정렬이 깨지면 리포트가 1순위로 엉뚱한 걸 올린다.
            if previous is not None and priority > previous:
                problems.append(
                    "top_n.keyword_impact 가 priority 내림차순이 아닙니다."
                )

            previous = priority

    return problems


ALERT_LEVELS = {"critical", "warning", "info"}


def _validate_alerts(alerts):
    """임계치 판정 결과. 경고가 없으면 빈 리스트가 정상이다."""

    problems = []

    if not isinstance(alerts, list):
        return ["alerts 는 리스트여야 합니다."]

    for index, alert in enumerate(alerts):

        if not isinstance(alert, dict):
            problems.append(f"alerts[{index}] 가 dict 가 아닙니다.")
            continue

        for key in ("level", "code", "title", "scope", "value",
                    "threshold", "detail", "hypotheses", "next_metrics"):

            if key not in alert:
                problems.append(f"alerts[{index}].{key} 누락")

        if alert.get("level") not in ALERT_LEVELS:
            problems.append(
                f"alerts[{index}].level 이 허용값이 아닙니다: "
                f"{alert.get('level')!r}"
            )

        for key in ("hypotheses", "next_metrics"):

            if key in alert and not isinstance(alert[key], list):
                problems.append(f"alerts[{index}].{key} 는 리스트여야 합니다.")

    return problems


# ------------------------------------------------------------ 어댑터 통과 후

def validate_analysis_output(output):
    """
    adapters.analyze_reviews() 반환 형태를 본다.

    C 원본은 [{sentiment, confidence}] 리스트를 준다.
    어댑터가 id 를 붙이고 failed_ids 를 만든 뒤의 모양을 검증한다.
    """

    problems = []

    if not isinstance(output, dict):
        return ["analyze 결과가 dict 가 아닙니다."]

    if "results" not in output:
        problems.append("results 키 누락")

    if "failed_ids" not in output:
        problems.append("failed_ids 키 누락")

    if problems:
        return problems

    if not isinstance(output["results"], list):
        problems.append("results 는 리스트여야 합니다.")
        return problems

    if not isinstance(output["failed_ids"], list):
        problems.append("failed_ids 는 리스트여야 합니다.")

    seen = set()

    for index, item in enumerate(output["results"]):

        if not isinstance(item, dict):
            problems.append(f"results[{index}] 가 dict 가 아닙니다.")
            continue

        review_id = item.get("id")

        if not isinstance(review_id, int):
            problems.append(f"results[{index}].id 는 int 여야 합니다.")

        elif review_id in seen:
            problems.append(f"results 에 id={review_id} 가 두 번 있습니다.")

        else:
            seen.add(review_id)

        if item.get("sentiment") not in ALLOWED_SENTIMENTS:
            problems.append(
                f"results[{index}].sentiment 가 허용값이 아닙니다: "
                f"{item.get('sentiment')!r}"
            )

        confidence = item.get("confidence")

        if not isinstance(confidence, (int, float)):
            problems.append(f"results[{index}].confidence 는 숫자여야 합니다.")

        elif not 0.0 <= float(confidence) <= 1.0:
            problems.append(
                f"results[{index}].confidence 범위 초과: {confidence}"
            )

    overlap = seen & set(output["failed_ids"])

    if overlap:
        problems.append(
            f"성공과 실패에 같은 id 가 들어 있습니다: {sorted(overlap)}"
        )

    return problems


def validate_insights(insights):
    """adapters.extract_insights() 반환 형태를 본다."""

    problems = []

    if not isinstance(insights, dict):
        return ["insights 가 dict 가 아닙니다."]

    for key in ("positive_keywords", "negative_keywords", "improvements"):

        if key not in insights:
            problems.append(f"{key} 누락")

        elif not isinstance(insights[key], list):
            problems.append(f"{key} 는 리스트여야 합니다.")

    if "summary" not in insights:
        problems.append("summary 누락")

    elif not isinstance(insights["summary"], str):
        problems.append("summary 는 문자열이어야 합니다.")

    return problems


def validate_chart_paths(chart_paths):
    """
    B의 generate_charts() 반환 형태를 본다.

    dict {이름: 경로} 를 기대하며, 파일이 실제로 있는지까지 확인한다.
    경로만 돌려주고 저장에 실패한 경우를 리포트 단계 전에 잡는다.
    """

    problems = []

    if chart_paths is None:
        return problems

    if not isinstance(chart_paths, dict):
        return [
            "generate_charts() 는 {이름: 경로} dict 를 돌려줘야 합니다 "
            f"(현재: {type(chart_paths).__name__})"
        ]

    # 여기 3장만 필수로 본다.
    #
    # 대시보드에는 7장이 있지만, 나머지는 데이터가 없으면 안 나오는 것이
    # 정상이다. 추이는 날짜가 없으면 못 그리고, 제품별 구성은 제품명이
    # 하나도 없으면 그릴 게 없다. 그걸 [FAIL] 로 잡으면 dashboard 가
    # 통째로 멈춰서 통계도 리포트도 못 보게 된다.
    # 못 그린 차트는 visualizer 가 로그로 남기고 main.py 가 목록을 찍는다.
    for name in ("sentiment_distribution", "sentiment_trend",
                 "rating_sentiment"):

        if name not in chart_paths:
            problems.append(f"{name} 키 누락 (차트 3종)")

    for name, path in chart_paths.items():

        if not path:
            problems.append(f"{name}: 경로가 비어 있습니다.")

        elif not os.path.exists(str(path)):
            problems.append(f"{name}: 파일이 실제로 없습니다 - {path}")

    return problems
