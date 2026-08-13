# ============================================================
# A 담당 · 집계 (명세 4.6 stats / 4.7 차트 데이터 / 4.8 품질 지표)
#
# 집계는 이 파일에서만 한다.
#
# B가 차트용으로 한 번 세고 C가 리포트용으로 또 세면
# 같은 데이터인데 차트는 89건, 리포트는 90건이 되는 일이 반드시 생긴다.
# (반올림 방식, 미분석 리뷰 포함 여부 같은 사소한 차이로 갈린다)
#
# 대신 반환 dict 의 칸을 용도별로 나눠
#   B는 chart_data 만, C는 summary / quality / top_n 만 본다.
# 서로의 칸을 참조하지 않는다.
#
# [변경] top_n 에 product_counts / skin_type_counts 추가.
#        B의 clean 데이터에 skin_type 이 있어 그냥 두면 쓰이지 않는다.
#
# [2026-08-12] chart_data 를 3칸 -> 7칸으로 늘렸다. (대시보드)
#        kpi / rating_distribution / product_sentiment / skin_type_sentiment
#        네 칸이 늘었고, 넷 다 여기서 계산해서 넘긴다.
#        특히 kpi 는 summary·quality 가 이미 계산한 값을 그대로 옮긴다.
#        차트가 자기 손으로 다시 세면 타일의 '평균 별점 3.65' 와
#        리포트의 '평균 별점 3.6' 이 갈라지고, 둘 중 뭐가 맞는지
#        아무도 확인하지 않게 된다.
#        C의 계약(summary / quality / top_n)은 손대지 않았다.
# ============================================================

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from modules.database import fetch_reviews
from modules.logger import get_logger


logger = get_logger("stats")


SCHEMA_VERSION = 3   # chart_data 대시보드 확장으로 2 -> 3

SENTIMENT_ORDER = ["positive", "neutral", "negative"]

SENTIMENT_LABEL = {
    "positive": "긍정",
    "neutral": "중립",
    "negative": "부정",
}

# 색은 여기서 정하지 않는다.
#
# 예전에는 chart_data 에 colors 배열을 같이 실어 보냈는데,
# visualizer 는 그 값을 쓰지 않고 자기 팔레트를 쓴다.
# 쓰이지 않는 색 목록이 남아 있으면 나중에 차트를 고치는 사람이
# "여기 색이 있네" 하고 되살리게 되고, 그 초록/회색 조합은
# 적록색약에서 구분되지 않아 이미 한 번 물린 값이다.
# (근거는 modules/visualizer.py 머리말)

# 별점에서 기대되는 감정. 일치도 계산에 쓴다.
EXPECTED_SENTIMENT = {
    1: "negative",
    2: "negative",
    3: "neutral",
    4: "positive",
    5: "positive",
}


def calculate_stats(filters=None, db_path=None, top_n=5):
    """
    대시보드/리포트/차트에 필요한 모든 집계를 한 번에 계산한다.

    filters: {"product": ..., "skin_type": ..., "date_from": ..., "date_to": ...}
    """

    filters = filters or {}

    reviews = fetch_reviews(
        product=filters.get("product"),
        skin_type=filters.get("skin_type"),
        date_from=filters.get("date_from"),
        date_to=filters.get("date_to"),
        order_by="id",
        db_path=db_path,
    )

    analyzed = [r for r in reviews if r.get("sentiment")]
    rated = [r for r in reviews if r.get("rating") is not None]

    # summary / quality 를 먼저 만들고 chart_data 에 넘긴다.
    # KPI 타일이 이 둘의 숫자를 그대로 쓰기 때문이다.
    summary = _build_summary(reviews, analyzed, rated)
    quality = _build_quality(reviews, analyzed)

    return {
        "meta": _build_meta(filters),
        "summary": summary,
        "chart_data": _build_chart_data(
            analyzed, summary, quality, top_n=top_n
        ),
        "quality": quality,
        "top_n": _build_top_n(reviews, rated, limit=top_n),
    }


# ------------------------------------------------------------ meta

def _build_meta(filters):

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "filters": {
            "product": filters.get("product"),
            "skin_type": filters.get("skin_type"),
            "date_from": filters.get("date_from"),
            "date_to": filters.get("date_to"),
        },
    }


# ------------------------------------------------------------ summary (C용)

def _build_summary(reviews, analyzed, rated):
    """
    C 리포트가 쓰는 핵심 지표.

    주의: 비율의 분모가 서로 다르다.
      analysis_rate    는 '전체' 기준
      sentiment_ratios 는 '분석된 것' 기준
    섞으면 숫자가 안 맞는다.
    """

    total = len(reviews)

    counter = Counter(r["sentiment"] for r in analyzed)
    rating_counter = Counter(int(r["rating"]) for r in rated)

    return {
        "total": total,
        "analyzed": len(analyzed),
        "unanalyzed": total - len(analyzed),
        "analysis_rate": len(analyzed) / total if total else 0.0,

        "avg_rating": (
            sum(int(r["rating"]) for r in rated) / len(rated)
            if rated else 0.0
        ),
        "avg_confidence": (
            sum(float(r["confidence"]) for r in analyzed) / len(analyzed)
            if analyzed else 0.0
        ),

        # 세 키가 항상 존재한다 (0이어도).
        # C가 .get() 으로 방어하지 않아도 되게 하려는 것이다.
        "sentiment_counts": {
            s: counter.get(s, 0) for s in SENTIMENT_ORDER
        },
        "sentiment_ratios": {
            s: (counter.get(s, 0) / len(analyzed) if analyzed else 0.0)
            for s in SENTIMENT_ORDER
        },

        # 1~5 다섯 키가 항상 존재한다.
        "rating_counts": {
            star: rating_counter.get(star, 0) for star in range(1, 6)
        },
    }


# ------------------------------------------------------------ chart_data (차트용)

def _build_chart_data(analyzed, summary, quality, top_n=5):
    """
    차트가 곧바로 matplotlib 에 넣을 수 있는 형태로 만든다.
    visualizer 는 여기서 나간 값을 그리기만 하고 다시 세지 않는다.

    7칸이고, 각 칸이 차트 한 장과 1:1 이다.
    (이름은 modules/visualizer.py 의 CHART_ORDER 와 같아야 한다)
    """

    counter = Counter(r["sentiment"] for r in analyzed)

    return {

        "kpi_summary": _build_kpi(summary, quality),

        "sentiment_distribution": {
            "labels": [SENTIMENT_LABEL[s] for s in SENTIMENT_ORDER],
            "values": [counter.get(s, 0) for s in SENTIMENT_ORDER],
        },

        "sentiment_trend": _build_trend(analyzed),

        # 별점 분포는 '분석된 것' 이 아니라 '별점이 있는 전체' 기준이다.
        # summary.rating_counts 와 같은 값을 옮긴다.
        "rating_distribution": {
            "ratings": [1, 2, 3, 4, 5],
            "values": [
                summary["rating_counts"][star] for star in range(1, 6)
            ],
        },

        "rating_sentiment": _build_rating_matrix(analyzed),

        "product_sentiment": _build_group_sentiment(
            analyzed, "product_name", limit=top_n
        ),

        "skin_type_sentiment": _build_group_sentiment(
            analyzed, "skin_type", limit=top_n
        ),
    }


def _build_kpi(summary, quality):
    """
    대시보드 맨 위 요약 타일에 들어갈 숫자.

    새로 세는 값이 하나도 없다. 전부 summary / quality 에서 옮겨온다.
    여기서 한 번이라도 다시 세면 그 순간 정답이 두 개가 된다.
    """

    ratios = summary["sentiment_ratios"]

    return {
        "total": summary["total"],
        "analyzed": summary["analyzed"],
        "analysis_rate": summary["analysis_rate"],
        "avg_rating": summary["avg_rating"],
        "avg_confidence": summary["avg_confidence"],
        "positive_ratio": ratios["positive"],
        "negative_ratio": ratios["negative"],
        "rating_sentiment_agreement": quality["rating_sentiment_agreement"],
    }


def _build_group_sentiment(analyzed, field, limit=5):
    """
    분류 축(제품 · 피부타입)별 감정 구성.

    건수가 많은 순으로 limit 개만 남긴다.
    제품이 30종이면 막대 30줄짜리 그림이 되고, 아래쪽 20줄은
    각각 2~3건이라 비율이 0% 아니면 100% 로만 튄다.
    표본이 적은 막대를 같은 높이로 세워두면 그 100% 가
    큰 제품의 100% 와 같은 무게로 읽힌다.

    건수를 함께 돌려주는 이유도 같다. 차트가 막대 옆에 n 을 적어
    "이 100% 는 3건짜리" 임을 밝힐 수 있어야 한다.

    field 값이 비어 있는 리뷰는 빼고 센다.
    '(미지정)' 같은 칸을 만들면 그게 제일 큰 막대가 되는 일이 잦다.
    """

    buckets = defaultdict(Counter)

    for review in analyzed:
        key = review.get(field)

        if key:
            buckets[key][review["sentiment"]] += 1

    # 건수 내림차순. 같으면 이름순 — 같은 데이터면 항상 같은 그림이 나와야
    # 어제 차트와 오늘 차트를 나란히 두고 비교할 수 있다.
    ranked = sorted(
        buckets.items(),
        key=lambda item: (-sum(item[1].values()), str(item[0])),
    )[:limit]

    return {
        "labels": [name for name, _ in ranked],
        "series": {
            s: [counts.get(s, 0) for _, counts in ranked]
            for s in SENTIMENT_ORDER
        },
        "totals": [sum(counts.values()) for _, counts in ranked],
    }


def _build_trend(analyzed):
    """
    시간별 감정 추이.

    기간 길이에 따라 묶는 단위를 자동으로 바꾼다.
    하루 1건씩 들어오는 데이터를 일별로 그리면
    누적 차트가 바코드처럼 보여서 아무 정보도 주지 못한다.

      14일 이하  -> 일별
      120일 이하 -> 주별 (그 주 월요일 날짜로 표기)
      그 이상    -> 월별
    """

    empty = {
        "granularity": "day",
        "labels": [],
        "series": {s: [] for s in SENTIMENT_ORDER},
        "negative_ratio": [],
    }

    dated = [r for r in analyzed if r.get("review_date")]

    if not dated:
        return empty

    parsed = []

    for review in dated:

        try:
            parsed.append(
                (review, datetime.strptime(review["review_date"], "%Y-%m-%d"))
            )

        except ValueError:
            # 날짜 형식이 다른 1건 때문에 추이 전체를 버리지는 않는다.
            logger.debug(
                "날짜 형식이 예상과 달라 건너뜁니다: %r", review["review_date"]
            )

    if not parsed:
        logger.warning("해석 가능한 날짜가 없어 추이 계산을 건너뜁니다.")
        return empty

    dates = [date for _, date in parsed]
    span = (max(dates) - min(dates)).days + 1

    if span <= 14:
        granularity = "day"

        def bucket_of(date):
            return date.strftime("%Y-%m-%d")

    elif span <= 120:
        granularity = "week"

        def bucket_of(date):
            return (
                date - timedelta(days=date.weekday())
            ).strftime("%Y-%m-%d")

    else:
        granularity = "month"

        def bucket_of(date):
            return date.strftime("%Y-%m")

    buckets = defaultdict(Counter)

    for review, date in parsed:
        buckets[bucket_of(date)][review["sentiment"]] += 1

    labels = sorted(buckets)
    totals = [sum(buckets[label].values()) for label in labels]

    return {
        "granularity": granularity,
        "labels": labels,
        "series": {
            s: [buckets[label].get(s, 0) for label in labels]
            for s in SENTIMENT_ORDER
        },
        "negative_ratio": [
            (buckets[label].get("negative", 0) / total if total else 0.0)
            for label, total in zip(labels, totals)
        ],
    }


def _build_rating_matrix(analyzed):
    """
    별점별 감정 분포. 각 배열 길이를 5로 고정한다.
    B가 길이를 확인하지 않아도 되게 하려는 것이다.
    """

    matrix = {star: Counter() for star in range(1, 6)}

    for review in analyzed:

        if review.get("rating") is not None:
            matrix[int(review["rating"])][review["sentiment"]] += 1

    return {
        "ratings": [1, 2, 3, 4, 5],
        "series": {
            s: [matrix[star].get(s, 0) for star in range(1, 6)]
            for s in SENTIMENT_ORDER
        },
    }


# ------------------------------------------------------------ quality (C용)

def _build_quality(reviews, analyzed):
    """명세 4.8 이 요구하는 품질 지표. 2개 이상이어야 한다."""

    total = len(reviews)

    # 별점-감정 일치도
    #
    # 이 지표가 의미를 가지려면 감정 분석이 별점을 보지 않아야 한다.
    # C의 프롬프트에 "별점이나 다른 정보는 사용하지 않습니다" 가 들어 있어
    # 조건이 지켜지고 있다. 별점을 넣으면 모델이 그대로 따라가
    # 일치도가 항상 100%가 되고 지표가 순환논리로 무의미해진다.
    rated_analyzed = [r for r in analyzed if r.get("rating") is not None]

    agree = sum(
        1 for r in rated_analyzed
        if r["sentiment"] == EXPECTED_SENTIMENT[int(r["rating"])]
    )

    # 데이터 완전성: 선택 필드까지 모두 채워진 비율
    complete = sum(
        1 for r in reviews
        if r.get("rating") is not None
        and r.get("review_date")
        and r.get("review_text")
    )

    return {
        "rating_sentiment_agreement": (
            agree / len(rated_analyzed) if rated_analyzed else 0.0
        ),
        "data_completeness": complete / total if total else 0.0,
        "avg_review_length": (
            sum(len(r["review_text"]) for r in reviews) / total
            if total else 0.0
        ),
    }


# ------------------------------------------------------------ top_n (C용)

def _build_top_n(reviews, rated, limit=5):
    """
    명세 4.8 이 요구하는 TOP N 집계. 1개 이상이어야 한다.

    worst_reviews    : 별점이 낮은 순. 개선 우선순위가 높은 리뷰.
    product_counts   : 제품별 리뷰 수
    skin_type_counts : 피부타입별 리뷰 수 (B의 clean 데이터에만 있는 필드)
    """

    worst = sorted(
        rated,
        key=lambda r: (int(r["rating"]), r.get("review_date") or ""),
    )

    # 리포트에 필요한 필드만 남긴다.
    #
    # 예전에는 DB 레코드 13개 키를 통째로 넘겼는데,
    # review_hash · created_at · model · analyzed_at 은 A 내부 사정이라
    # 리포트가 알 이유가 없다. 계약에 들어가는 키가 적을수록
    # 나중에 컬럼을 바꿔도 C가 영향을 안 받는다.
    worst = [
        {
            key: review.get(key)
            for key in ("id", "product_name", "review_text", "rating",
                        "review_date", "skin_type", "sentiment", "confidence")
        }
        for review in worst[:limit]
    ]

    products = Counter(
        r["product_name"] for r in reviews if r.get("product_name")
    )
    skin_types = Counter(
        r["skin_type"] for r in reviews if r.get("skin_type")
    )

    return {
        "worst_reviews": worst,
        "product_counts": products.most_common(limit),
        "skin_type_counts": skin_types.most_common(limit),
    }


# ------------------------------------------------------------ 콘솔 출력

def format_stats(stats):
    """stats 서브커맨드용 콘솔 출력. (명세 4.6)"""

    summary = stats["summary"]

    if summary["total"] == 0:
        return "리뷰가 없습니다. 먼저 `import` 명령으로 데이터를 넣으세요."

    lines = [
        "",
        "=== 리뷰 분석 통계 ===",
        f"총 리뷰 수: {summary['total']}건",
        f"분석 완료: {summary['analyzed']}건 ({summary['analysis_rate']:.1%})",
    ]

    if summary["analyzed"]:

        lines.append("\n[감정 분포]")

        for sentiment in SENTIMENT_ORDER:
            count = summary["sentiment_counts"][sentiment]
            ratio = summary["sentiment_ratios"][sentiment]
            lines.append(
                f"- {SENTIMENT_LABEL[sentiment]}: {count}건 ({ratio:.1%})"
            )

    lines.append("\n[별점 분포]")

    total_rated = sum(summary["rating_counts"].values())

    for star in range(5, 0, -1):
        count = summary["rating_counts"][star]
        ratio = count / total_rated if total_rated else 0.0
        stars = "★" * star + "☆" * (5 - star)
        lines.append(f"- {stars}: {count}건 ({ratio:.1%})")

    lines.append(f"\n평균 별점: {summary['avg_rating']:.2f}")

    if summary["analyzed"]:
        lines.append(f"평균 확신도: {summary['avg_confidence']:.2f}")

    quality = stats["quality"]
    lines.append(
        f"별점-감정 일치도: {quality['rating_sentiment_agreement']:.1%}"
    )
    lines.append(f"데이터 완전성: {quality['data_completeness']:.1%}")

    top_n = stats.get("top_n", {})

    if top_n.get("product_counts"):
        lines.append("\n[제품별 리뷰 수]")

        for name, count in top_n["product_counts"]:
            lines.append(f"- {name}: {count}건")

    if top_n.get("skin_type_counts"):
        lines.append("\n[피부타입별 리뷰 수]")

        for name, count in top_n["skin_type_counts"]:
            lines.append(f"- {name}: {count}건")

    return "\n".join(lines)
