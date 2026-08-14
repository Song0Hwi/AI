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
#
# [2026-08-13] 칸이 5개 -> 6개. alerts 추가. (평가 #13 · #18)
#        숫자를 내놓기만 하고 "그래서 괜찮은 건가" 를 아무도 말하지 않아서
#        부정률 29% 를 보고도 그게 높은 건지 판단할 근거가 없었다.
#        임계치를 config 에 두고 여기서 판정해 alerts 로 내보낸다.
#        급증을 잡으면 어느 제품·피부타입에서 늘었는지까지 짚어준다.
#
#        top_n 에 keyword_impact 추가. (평가 #17)
#        C가 뽑은 부정 키워드를 A가 본문으로 되짚어 빈도·별점·부정률을
#        재고 우선순위를 매긴다. C 파일은 건드리지 않았다.
# ============================================================

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from modules.database import fetch_reviews
from modules.logger import get_logger


logger = get_logger("stats")


SCHEMA_VERSION = 4   # alerts / keyword_impact 추가로 3 -> 4

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

# 임계치 기본값. config.json 의 alerts 섹션이 덮어쓴다.
#
# 값의 출처를 분명히 해둔다. 업계 표준이 아니라 이 데이터셋 기준의
# 출발점이다. 99건에서 부정 4%, 별점-감정 일치도 82% 가 나왔으므로
# 부정률 15% 는 "평소의 세 배", 일치도 60% 는 "분석이 흔들리는 수준" 이다.
# 제품군이나 수집 채널이 바뀌면 다시 잡아야 한다.
DEFAULT_THRESHOLDS = {
    "negative_ratio_warn": 0.15,        # 전체 부정 비율 경고선
    "negative_ratio_critical": 0.30,    # 심각선
    "spike_delta": 0.10,                # 직전 구간 대비 부정률 증가폭
    "min_bucket_size": 5,               # 이보다 작은 구간은 판정하지 않는다
    "group_negative_ratio_warn": 0.30,  # 제품·피부타입별 부정 비율
    "min_group_size": 5,                # 이보다 작은 그룹은 판정하지 않는다
    "agreement_warn": 0.60,             # 별점-감정 일치도 하한
    "confidence_warn": 0.65,            # 평균 확신도 하한
}

# 경고를 띄웠을 때 사람이 다음에 볼 것. 코드가 답을 줄 수는 없고,
# "어디를 더 보라" 까지가 정직한 범위다.
NEXT_METRICS = {
    "negative_ratio_high": [
        "같은 기간 클레임·문의 건수", "반품·환불률", "재구매율",
    ],
    "negative_spike": [
        "해당 구간의 생산 로트·유통 경로", "직전 리뉴얼·성분 변경 시점",
        "동일 기간 경쟁사 리뷰 추이",
    ],
    "group_negative_high:product_name": [
        "해당 제품의 반품·환불률", "같은 라인 다른 제품과의 비교",
        "최근 리뉴얼·성분 변경 이력",
    ],
    "group_negative_high:skin_type": [
        "해당 피부타입 대상 사용 가이드가 있는지",
        "그 타입에서 자주 나오는 불만 어휘",
        "제품 상세페이지의 타입별 안내 문구",
    ],
    "low_agreement": [
        "표본 검수 결과(사람 라벨과의 일치도)", "프롬프트 버전별 일치도 비교",
    ],
    "low_confidence": [
        "확신도 하위 구간의 리뷰 길이", "중립 판정 비율",
    ],
}


# 별점에서 기대되는 감정. 일치도 계산에 쓴다.
EXPECTED_SENTIMENT = {
    1: "negative",
    2: "negative",
    3: "neutral",
    4: "positive",
    5: "positive",
}


def calculate_stats(filters=None, db_path=None, top_n=5,
                    keywords=None, thresholds=None):
    """
    대시보드/리포트/차트에 필요한 모든 집계를 한 번에 계산한다.

    filters:    {"product": ..., "skin_type": ..., "date_from": ..., "date_to": ...}
    keywords:   C가 뽑은 부정 키워드 목록. 있으면 keyword_impact 를 매긴다.
    thresholds: config.alerts. 없으면 DEFAULT_THRESHOLDS.
    """

    filters = filters or {}
    thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

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

    # 추이는 두 곳에서 쓴다. 차트와 급증 판정이다.
    # 두 번 묶으면 차트가 본 구간과 경고가 본 구간이 달라질 수 있어
    # 한 번만 묶고 결과를 나눠 쓴다.
    trend, buckets = _build_trend(analyzed)

    return {
        "meta": _build_meta(filters),
        "summary": summary,
        "chart_data": _build_chart_data(
            analyzed, summary, quality, trend, top_n=top_n
        ),
        "quality": quality,
        "top_n": _build_top_n(
            reviews, analyzed, rated, keywords, limit=top_n
        ),
        "alerts": _build_alerts(
            reviews, analyzed, summary, quality, trend, buckets,
            thresholds, limit=top_n,
        ),
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

def _build_chart_data(analyzed, summary, quality, trend, top_n=5):
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

        "sentiment_trend": trend,

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
        return empty, {}

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
        return empty, {}

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
    members = defaultdict(list)

    for review, date in parsed:
        label = bucket_of(date)
        buckets[label][review["sentiment"]] += 1
        members[label].append(review)

    labels = sorted(buckets)
    totals = [sum(buckets[label].values()) for label in labels]

    trend = {
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

    # members 는 chart_data 에 넣지 않는다. 차트가 쓸 일이 없고,
    # 리뷰 원문이 통째로 딸려가면 stats 를 로그로 찍을 수 없게 된다.
    return trend, dict(members)


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

def _build_top_n(reviews, analyzed, rated, keywords=None, limit=5):
    """
    명세 4.8 이 요구하는 TOP N 집계. 1개 이상이어야 한다.

    worst_reviews    : 별점이 낮은 순. 개선 우선순위가 높은 리뷰.
    product_counts   : 제품별 리뷰 수
    skin_type_counts : 피부타입별 리뷰 수 (B의 clean 데이터에만 있는 필드)
    keyword_impact   : 부정 키워드별 영향도와 우선순위 (keywords 가 있을 때만)
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
        "keyword_impact": _build_keyword_impact(
            reviews, analyzed, keywords, limit=limit
        ),
    }


def _build_keyword_impact(reviews, analyzed, keywords, limit=5):
    """
    부정 키워드별 영향도와 개선 우선순위. (평가 #17)

    분업
      C가 "무엇이 문제인가" 를 뽑고(키워드), A가 "얼마나 문제인가" 를 잰다.
      C의 extract 는 앞의 60건만 프롬프트에 넣으므로 빈도를 알 수 없고,
      별점·감정은 DB에만 있다. 그래서 세는 일은 A가 맡는다.

    본문 매칭이 왜 이렇게 생겼나
      C가 주는 키워드는 '무거운 사용감', '트러블 발생' 처럼 **모델이 요약한
      개념**이다. 본문에 그 문구가 그대로 있는 경우는 거의 없다.
      실제로 문자열을 그대로 찾으면 다섯 개 중 다섯 개가 0건이었다.

      그래서 어절로 쪼개고 3글자 이상이면 앞 2글자만 어간으로 본다.
      한국어는 어미가 뒤에 붙어서 '무거운 / 무겁게 / 무거워' 가
      앞 두 글자를 공유한다. 형태소 분석기 없이 쓸 수 있는 근사다.

      대신 흔한 어절은 STOPWORD_STEMS 로 뺀다. 이걸 안 하면
      '무거운 사용감' 이 '사용' 때문에 99건 중 72건에 걸려서
      아무 의미 없는 1순위가 된다.

    매칭이 0건이면 버리지 않고 matched=False 로 남긴다
      "왜 내 키워드가 리포트에 없지" 를 없애려는 것도 있지만,
      그것 자체가 신호다. 모델이 본문에 없는 말로 요약했다는 뜻이라
      요약 품질을 의심할 근거가 된다. (검수 절차는 README 4.11)

    우선순위 점수
      세 가지를 섞는다. 하나만 보면 판단이 어긋난다.

        빈도      많이 언급될수록 손대는 값이 크다
        부정률    그 말이 나온 리뷰가 실제로 부정으로 읽히는가
        별점 하락  전체 평균보다 얼마나 낮은 별점을 끌고 오는가

      '향' 은 자주 나오지만 긍정도 많아 부정률이 낮고, '고장' 은 드물지만
      나오면 1점이다. 빈도만 보면 앞을, 심각도만 보면 뒤를 고르게 되어
      둘 다 틀린다.

    점수는 **이 데이터 안에서의 상대 순위**다. 절대 척도가 아니다.
    빈도를 최댓값으로 정규화하므로 리뷰가 바뀌면 같은 키워드도 다른 점수를
    받는다. 제품 간·기간 간 비교에 쓰면 안 된다.
    """

    if not keywords or not reviews:
        return []

    overall_rated = [r for r in reviews if r.get("rating") is not None]
    overall_avg = (
        sum(int(r["rating"]) for r in overall_rated) / len(overall_rated)
        if overall_rated else 0.0
    )

    rows = []

    for keyword in keywords:
        keyword = str(keyword).strip()

        if not keyword:
            continue

        terms = _match_terms(keyword)
        hits = [
            r for r in reviews
            if terms and any(t in (r.get("review_text") or "") for t in terms)
        ]

        hit_rated = [r for r in hits if r.get("rating") is not None]
        hit_analyzed = [r for r in hits if r.get("sentiment")]
        negative = sum(
            1 for r in hit_analyzed if r["sentiment"] == "negative"
        )
        avg_rating = (
            sum(int(r["rating"]) for r in hit_rated) / len(hit_rated)
            if hit_rated else 0.0
        )

        rows.append({
            "keyword": keyword,
            "matched": bool(hits),
            "matched_terms": terms,
            "reviews": len(hits),
            "share": len(hits) / len(reviews),
            "avg_rating": avg_rating,
            # 매칭이 없으면 별점 비교가 성립하지 않는다. 0으로 두면
            # -3.65 같은 값이 나와 "가장 나쁜 키워드" 로 올라간다.
            "rating_gap": (avg_rating - overall_avg) if hit_rated else 0.0,
            "negative_ratio": (
                negative / len(hit_analyzed) if hit_analyzed else 0.0
            ),
        })

    matched = [row for row in rows if row["matched"]]
    busiest = max((row["reviews"] for row in matched), default=0)

    for row in rows:

        if not row["matched"] or not busiest:
            row["priority"] = 0.0
            continue

        frequency = row["reviews"] / busiest                 # 0~1 (상대)
        severity = row["negative_ratio"]                      # 0~1
        pull = max(0.0, -row["rating_gap"]) / 4.0             # 0~1

        row["priority"] = round(
            0.40 * frequency + 0.40 * severity + 0.20 * pull, 3
        )

    # 매칭된 것 먼저, 그 안에서 우선순위 내림차순.
    rows.sort(key=lambda row: (-row["priority"], row["keyword"]))

    return rows[:limit]


# 어간 매칭에서 뺄 흔한 어절.
#
# 화장품 리뷰에는 '사용/제품/피부' 가 거의 모든 문장에 들어간다.
# 이걸 남겨두면 그 어절을 포함한 키워드가 전부 1순위가 되고,
# 우선순위 표가 통째로 무의미해진다.
STOPWORD_STEMS = {
    "사용", "제품", "피부", "얼굴", "리뷰", "구매", "배송", "포장",
    "정도", "조금", "생각", "부분", "느낌", "발림", "바르", "발라",
    "이번", "처음", "다시", "여름", "겨울", "아침", "저녁",
    "발생", "증가", "감소", "적음", "많음", "호불",
}


def _match_terms(keyword):
    """
    키워드를 본문에서 찾을 어간 목록으로 바꾼다.

    '무거운 사용감' -> ['무거']   ('사용' 은 불용어라 빠진다)
    '느린 흡수'     -> ['느린', '흡수']
    '향 호불호'     -> []          (한 글자 + 불용어만 남아 매칭 불가)

    한 글자는 버린다. '향' 을 그대로 찾으면 '향수 / 방향 / 영향' 이
    전부 걸린다.
    """

    terms = []

    for token in re.split(r"[^가-힣A-Za-z0-9]+", keyword):

        if len(token) < 2:
            continue

        stem = token[:2] if len(token) >= 3 else token

        if stem in STOPWORD_STEMS:
            continue

        if stem not in terms:
            terms.append(stem)

    return terms


# ------------------------------------------------------------ alerts

def _build_alerts(reviews, analyzed, summary, quality, trend, buckets,
                  thresholds, limit=5):
    """
    임계치 판정과 급증 감지. (평가 #13 · #18)

    왜 필요한가
      집계는 숫자를 내놓을 뿐 "그래서 괜찮은가" 를 말하지 않는다.
      부정률 29% 를 보고도 그게 평소보다 높은 건지 판단할 근거가 없으면
      리포트를 읽는 사람마다 다른 결론을 낸다.

    무엇을 하지 않는가
      원인을 단정하지 않는다. 코드는 "5월에 지성 피부 부정률이 40% 로
      다른 구간보다 높다" 까지만 말할 수 있고, 왜 그런지는 모른다.
      그래서 hypotheses 는 **확인해볼 후보**로, next_metrics 는
      **다음에 볼 지표**로 이름을 붙였다. 결론이 아니다.

    표본이 작으면 판정하지 않는다. 3건 중 2건이 부정이면 67% 지만
    그건 경고가 아니라 잡음이다. min_bucket_size / min_group_size 로 끊는다.
    """

    alerts = []

    def add(level, code, title, scope, value, threshold, detail,
            hypotheses=None, metrics_key=None):
        alerts.append({
            "level": level,
            "code": code,
            "title": title,
            "scope": scope,
            "value": round(float(value), 4),
            "threshold": round(float(threshold), 4),
            "detail": detail,
            "hypotheses": hypotheses or [],
            "next_metrics": NEXT_METRICS.get(metrics_key or code, []),
        })

    analyzed_count = len(analyzed)

    # ---- 1. 전체 부정 비율
    negative_ratio = summary["sentiment_ratios"]["negative"]
    negative_count = summary["sentiment_counts"]["negative"]

    if analyzed_count >= thresholds["min_bucket_size"]:

        for level, key in (("critical", "negative_ratio_critical"),
                           ("warning", "negative_ratio_warn")):

            if negative_ratio >= thresholds[key]:
                add(
                    level, "negative_ratio_high",
                    "부정 비율이 기준을 넘었습니다", "전체",
                    negative_ratio, thresholds[key],
                    f"분석 {analyzed_count}건 중 부정 {negative_count}건 "
                    f"({negative_ratio:.1%}). 기준 {thresholds[key]:.0%}",
                    hypotheses=[
                        "특정 제품에 몰려 있는지 — 아래 제품별 경고를 함께 보세요",
                        "특정 기간에 몰려 있는지 — 추이 차트의 부정 비율 선",
                        "수집 채널이 바뀌어 불만 유입이 늘었는지",
                    ],
                )
                break

    # ---- 2. 구간별 급증
    labels = trend.get("labels", [])
    ratios = trend.get("negative_ratio", [])
    unit = {"day": "일", "week": "주", "month": "월"}.get(
        trend.get("granularity"), "구간"
    )

    for index in range(1, len(labels)):
        label = labels[index]
        members = buckets.get(label, [])

        if len(members) < thresholds["min_bucket_size"]:
            continue

        delta = ratios[index] - ratios[index - 1]

        if delta < thresholds["spike_delta"]:
            continue

        add(
            "warning", "negative_spike",
            f"부정 비율이 직전 {unit} 대비 급증했습니다", label,
            delta, thresholds["spike_delta"],
            f"{labels[index - 1]} {ratios[index - 1]:.0%} → "
            f"{label} {ratios[index]:.0%} "
            f"(+{delta:.0%}p, 표본 {len(members)}건)",
            hypotheses=_spike_hypotheses(members, analyzed),
        )

    # ---- 3. 그룹별 부정 비율
    for field, label_ko in (("product_name", "제품"),
                            ("skin_type", "피부타입")):

        groups = defaultdict(list)

        for review in analyzed:

            if review.get(field):
                groups[review[field]].append(review)

        for name, members in sorted(groups.items()):

            if len(members) < thresholds["min_group_size"]:
                continue

            ratio = sum(
                1 for r in members if r["sentiment"] == "negative"
            ) / len(members)

            if ratio < thresholds["group_negative_ratio_warn"]:
                continue

            add(
                "warning", "group_negative_high",
                f"{label_ko}별 부정 비율이 기준을 넘었습니다",
                f"{label_ko}={name}",
                ratio, thresholds["group_negative_ratio_warn"],
                f"{name}: 분석 {len(members)}건 중 부정 "
                f"{int(ratio * len(members))}건 ({ratio:.1%})",
                hypotheses=[
                    f"'{name}' 쪽에만 해당하는 변화가 있었는지 "
                    f"(성분·제형·안내 문구)",
                    f"'{name}' 리뷰 원문에서 반복되는 불만이 무엇인지 "
                    f"— list --{'product' if field == 'product_name' else 'skin-type'} "
                    f"\"{name}\" --sentiment negative",
                ],
                metrics_key=f"group_negative_high:{field}",
            )

    # ---- 4. 분석 품질
    agreement = quality["rating_sentiment_agreement"]

    if analyzed_count >= thresholds["min_bucket_size"]:

        if agreement < thresholds["agreement_warn"]:
            add(
                "warning", "low_agreement",
                "별점-감정 일치도가 낮습니다", "전체",
                agreement, thresholds["agreement_warn"],
                f"일치도 {agreement:.1%} (기준 {thresholds['agreement_warn']:.0%}). "
                f"감정 분석이 흔들렸거나, 별점과 본문이 실제로 어긋나는 "
                f"데이터일 수 있습니다",
                hypotheses=[
                    "프롬프트가 바뀐 뒤 떨어졌는지 — 모델·버전별로 나눠 보세요",
                    "별점을 습관적으로 후하게 주는 채널인지",
                ],
            )

        if summary["avg_confidence"] < thresholds["confidence_warn"]:
            add(
                "warning", "low_confidence",
                "평균 확신도가 낮습니다", "전체",
                summary["avg_confidence"], thresholds["confidence_warn"],
                f"평균 확신도 {summary['avg_confidence']:.2f} "
                f"(기준 {thresholds['confidence_warn']:.2f}). "
                f"애매한 리뷰가 많거나 프롬프트가 흐릿할 수 있습니다",
            )

    # ---- 5. 미분석 잔량 (경고가 아니라 안내)
    if summary["unanalyzed"]:
        add(
            "info", "unanalyzed_remaining",
            "아직 분석되지 않은 리뷰가 있습니다", "전체",
            summary["analysis_rate"], 1.0,
            f"미분석 {summary['unanalyzed']}건. "
            f"지금 통계와 차트는 분석된 {analyzed_count}건 기준입니다",
        )

    order = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: (order[a["level"]], a["code"], a["scope"]))

    return alerts


def _spike_hypotheses(members, analyzed):
    """
    급증 구간에서 '어디가 늘었나' 를 짚는다.

    구간 안의 부정 리뷰를 제품·피부타입별로 갈라, 그 구간에서의 비중이
    전체에서의 비중보다 눈에 띄게 높은 그룹을 후보로 올린다.
    원인이 아니라 **먼저 들여다볼 곳**이다.
    """

    negative = [r for r in members if r["sentiment"] == "negative"]

    if not negative:
        return ["이 구간의 부정 리뷰 원문을 먼저 읽어보세요."]

    hypotheses = []

    for field, label_ko in (("product_name", "제품"),
                            ("skin_type", "피부타입")):

        here = Counter(r[field] for r in negative if r.get(field))

        if not here:
            continue

        everywhere = Counter(
            r[field] for r in analyzed
            if r.get(field) and r["sentiment"] == "negative"
        )

        name, count = here.most_common(1)[0]
        share_here = count / len(negative)
        share_all = (
            everywhere.get(name, 0) / sum(everywhere.values())
            if everywhere else 0.0
        )

        if share_here > share_all + 0.15:
            hypotheses.append(
                f"{label_ko} '{name}' 에 몰려 있습니다 — "
                f"이 구간 부정의 {share_here:.0%} (전체 평균 {share_all:.0%})"
            )

    if not hypotheses:
        hypotheses.append(
            "특정 제품·피부타입에 쏠리지 않았습니다. "
            "기간 공통 요인(배송·프로모션·계절)을 확인해 보세요."
        )

    hypotheses.append("이 구간의 부정 리뷰 원문을 표본으로 읽어보세요.")

    return hypotheses


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

    if top_n.get("keyword_impact"):
        lines.append("\n[개선 우선순위] 부정 키워드 영향도")

        for rank, row in enumerate(top_n["keyword_impact"], start=1):

            if not row["matched"]:
                lines.append(
                    f"{rank}. {row['keyword']} — 본문에서 찾지 못했습니다 "
                    f"(모델이 개념으로 요약한 표현. 순위 산정 제외)"
                )
                continue

            lines.append(
                f"{rank}. {row['keyword']} "
                f"(우선순위 {row['priority']:.2f}) "
                f"— {row['reviews']}건, 부정 {row['negative_ratio']:.0%}, "
                f"평균 별점 {row['avg_rating']:.2f} "
                f"({row['rating_gap']:+.2f})"
            )

    alerts = stats.get("alerts") or []

    if alerts:
        mark = {"critical": "[!!]", "warning": "[! ]", "info": "[i ]"}
        lines.append(f"\n[경고 · 안내] {len(alerts)}건")

        for alert in alerts:
            lines.append(
                f"{mark[alert['level']]} {alert['title']} "
                f"({alert['scope']})"
            )
            lines.append(f"     {alert['detail']}")

            for item in alert["hypotheses"]:
                lines.append(f"     · 확인 후보: {item}")

            for item in alert["next_metrics"]:
                lines.append(f"     · 다음 지표: {item}")

    return "\n".join(lines)
