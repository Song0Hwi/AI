# ============================================================
# A 담당 · 대시보드 차트  (원래 B 영역이었으나 A로 이관)
#
# 입력은 stats["chart_data"] 뿐이다. 이 파일에서 추가 집계를 하지 않는다.
# 집계가 두 군데로 갈리면 같은 데이터인데 차트는 89건 리포트는 90건이 되는
# 일이 반드시 생긴다. (INTERFACE.md 5번)
#
# KPI 타일까지 stats 에서 숫자를 받아오는 이유도 같다.
# 요약 숫자를 여기서 다시 세면 타일의 '평균 별점' 과 리포트의 '평균 별점' 이
# 반올림 한 자리 때문에 달라진다. 숫자는 stats, 표현은 여기.
#
# ------------------------------------------------------------
# 색 선택 근거
#
# 1차본은 긍정 #1D9E75(초록) / 중립 #888780(회색) / 부정 #D85A30(주황)이었다.
# 검증기를 돌리니 떨어졌다.
#
#   [FAIL] CVD separation   #888780↔#1D9E75  ΔE 1.2 (deutan)
#   [FAIL] Normal-vision    #888780↔#1D9E75  ΔE 11.9  (기준 15)
#
# 적록색약에서 회색과 초록이 사실상 같은 색으로 보인다. 감정 분포 차트에서
# '중립'과 '긍정'이 구분이 안 되면 차트가 아무 정보도 주지 못한다.
#
# 감정은 부정 ← 중립 → 긍정 의 극성(polarity)이므로 categorical 이 아니라
# diverging 이다. diverging 규칙은 "두 개의 대비되는 색상 + 중립 회색 중간점"
# 이고, 초록↔빨강은 색약에서 무너지는 대표 조합이라 파랑↔빨강을 쓴다.
#
#   [PASS] CVD separation   최악 인접쌍 ΔE 8.7 (deutan) · 12.7 (tritan)
#   [PASS] Normal-vision    최악 인접쌍 ΔE 16.2
#   [PASS] Contrast         3색 모두 배경 대비 3:1 이상
#
# 회색 중간점은 chroma floor 검사에서 걸리지만, 그건 categorical 팔레트용
# 검사다. diverging 의 중간점은 원래 무채색이어야 한다.
# 대신 색만으로 의미가 전달되지 않도록 **모든 막대에 수치를 직접 표기**하고
# 범례를 항상 넣는다. (색 + 위치 + 숫자, 3중 인코딩)
#
# 별점 분포 차트는 감정이 아니라 '별점 몇 개'를 세는 단일 계열이라
# 감정 3색을 쓰지 않는다. 감정 색을 재사용하면 4점 막대가 파란색이라는
# 이유로 '긍정' 으로 읽힌다. 무채에 가까운 ACCENT 한 색만 쓴다.
# ============================================================

import platform

from modules.logger import get_logger


logger = get_logger("visualizer")


# diverging: 부정(따뜻) ← 중립(무채) → 긍정(차가움)
SENTIMENT_COLOR = {
    "positive": "#1f6fb4",
    "neutral": "#8a8580",
    "negative": "#c94a3d",
}

SENTIMENT_ORDER = ["positive", "neutral", "negative"]

SENTIMENT_LABEL_KO = {
    "positive": "긍정",
    "neutral": "중립",
    "negative": "부정",
}

SENTIMENT_LABEL_EN = {
    "positive": "Positive",
    "neutral": "Neutral",
    "negative": "Negative",
}

SURFACE = "#fcfcfb"      # 차트 배경 (검증기가 쓴 light surface)
TILE = "#f2f1ed"         # KPI 타일 바닥 — 배경보다 한 단계만 어둡게
INK = "#2c2c2a"          # 본문 잉크
INK_MUTED = "#6b6b67"    # 보조 잉크
GRID = "#e5e4e0"         # 눈금선 — 배경으로 물러나야 한다
ACCENT = "#4a5c6a"       # 감정이 아닌 단일 계열용 (배경 대비 6:1)

# 리포트에 실리는 순서. C의 reporter 는 dict 를 받은 순서대로
# '차트 1, 차트 2 …' 를 붙이므로, 여기 순서가 곧 리포트 순서다.
# 요약(KPI) 을 맨 앞에 두어야 리포트를 위에서부터 읽을 수 있다.
CHART_ORDER = [
    "kpi_summary",
    "sentiment_distribution",
    "sentiment_trend",
    "rating_distribution",
    "rating_sentiment",
    "product_sentiment",
    "skin_type_sentiment",
]

# 한글 폰트 후보. 앞에서부터 찾고, 없으면 영문 라벨로 떨어진다.
FONT_CANDIDATES = [
    "Malgun Gothic",       # Windows
    "AppleGothic",         # macOS
    "Apple SD Gothic Neo",  # macOS
    "NanumGothic",         # Linux (fonts-nanum)
    "Nanum Gothic",
    "Noto Sans CJK KR",
    "Noto Sans KR",
    "Noto Sans CJK JP",    # 한글 글리프 포함
    "Source Han Sans KR",
    "Malgun Gothic Semilight",
]

_FONT_STATE = None   # (폰트명 or None, 한글 가능 여부)


def resolve_font():
    """
    한글이 나오는 폰트를 찾는다. 결과를 캐시한다.

    못 찾으면 (None, False) 를 돌려주고 호출부가 영문 라벨로 바꾼다.
    폰트가 없는데 한글을 그리면 글자가 전부 두부(□□□)로 나온다.
    차트가 깨진 채로 리포트에 박히는 것보다 영문이 낫다.
    """

    global _FONT_STATE

    if _FONT_STATE is not None:
        return _FONT_STATE

    from matplotlib import font_manager

    available = {font.name for font in font_manager.fontManager.ttflist}

    for name in FONT_CANDIDATES:

        if name in available:
            _FONT_STATE = (name, True)
            logger.debug("차트 한글 폰트: %s", name)
            return _FONT_STATE

    logger.warning(
        "한글 폰트를 찾지 못해 차트 라벨을 영문으로 그립니다. "
        "(%s 기준) 설치 예: Windows=맑은 고딕 기본 포함, "
        "Linux=`apt install fonts-nanum`",
        platform.system(),
    )

    _FONT_STATE = (None, False)

    return _FONT_STATE


def korean_ok():
    """한글 라벨을 그려도 되는 상태인가."""

    return resolve_font()[1]


def _prepare_pyplot():
    """
    Agg 백엔드와 폰트를 세팅한 pyplot 을 돌려준다.

    Agg 를 쓰는 이유: 화면이 없는 환경(CI, 서버)에서도 그려야 한다.
    """

    import matplotlib

    matplotlib.use("Agg")

    import matplotlib.pyplot as plt

    font_name, _ = resolve_font()

    if font_name:
        plt.rcParams["font.family"] = font_name

    # 한글 폰트에는 유니코드 마이너스(−)가 없는 경우가 많다.
    # 그대로 두면 음수 눈금이 두부로 나온다.
    plt.rcParams["axes.unicode_minus"] = False

    return plt


def _new_figure(width, height, dpi):
    """공통 스타일이 적용된 figure/axes 를 만든다."""

    plt = _prepare_pyplot()

    figure, axes = plt.subplots(figsize=(width, height), dpi=dpi)
    figure.patch.set_facecolor(SURFACE)
    axes.set_facecolor(SURFACE)

    return plt, figure, axes


def _strip_frame(axes, keep_left=False):
    """
    축 장식을 걷어낸다.

    눈금선과 축은 데이터보다 뒤로 물러나야 한다.
    테두리 네 줄이 다 있으면 시선이 상자에 먼저 간다.
    """

    for side in ("top", "right", "bottom", "left"):

        if side == "left" and keep_left:
            axes.spines[side].set_color(GRID)
            continue

        axes.spines[side].set_visible(False)

    axes.tick_params(colors=INK_MUTED, length=0, labelsize=9)


def _labels(sentiment_key):
    """폰트 상황에 맞는 감정 라벨."""

    table = SENTIMENT_LABEL_KO if korean_ok() else SENTIMENT_LABEL_EN

    return table[sentiment_key]


def _title(korean, english):
    return korean if korean_ok() else english


def _count(value):
    """'12건' / 'n=12' — 폰트 상황에 맞춰 건수를 적는다."""

    return f"{value}건" if korean_ok() else f"n={value}"


def _shorten(text, limit=14):
    """
    긴 제품명을 줄인다.

    y축 라벨이 길면 bbox_inches='tight' 가 그림 폭을 통째로 늘려
    같은 리포트 안에서 차트마다 크기가 달라진다.
    """

    text = str(text)

    return text if len(text) <= limit else text[:limit - 1] + "…"


def _empty_state(figure, axes, message_ko, message_en):
    """
    그릴 값이 0인 경우, 빈 축 대신 이유를 적는다.

    빈 축만 있는 그림이 리포트에 박히면 '분석 결과가 0' 인지
    '차트가 고장난' 건지 구분이 안 된다. 한 줄이라도 적어두면 구분된다.
    """

    axes.clear()
    axes.set_facecolor(SURFACE)
    axes.axis("off")
    axes.text(
        0.5, 0.5, _title(message_ko, message_en),
        ha="center", va="center", fontsize=11, color=INK_MUTED,
        transform=axes.transAxes,
    )

    return figure


def _save(plt, figure, output_path):
    figure.savefig(output_path, facecolor=SURFACE,
                   bbox_inches="tight", pad_inches=0.3)
    plt.close(figure)

    return output_path


# ============================================================
# 0. KPI 요약 타일
# ============================================================

def draw_kpi_summary(data, output_path, dpi):
    """
    대시보드 맨 위에 놓는 요약 숫자 6칸.

    차트가 아니라 '숫자를 크게 적은 그림' 인 이유
      리포트를 여는 사람이 가장 먼저 묻는 것은 "그래서 몇 건이고
      얼마나 부정적인가" 다. 그 답이 세 번째 그래프의 막대 길이로만
      있으면 매번 눈으로 재야 한다. 숫자는 숫자로 적는 게 빠르다.

    막대 하나짜리 차트를 6개 그리지 않는 이유도 같다.
    기준선이 없는 단일 값은 막대로 그려도 정보가 늘지 않는다.
    """

    total = int(data.get("total", 0))

    plt, figure, axes = _new_figure(8.4, 3.0, dpi)

    if total == 0:
        _empty_state(figure, axes,
                     "표시할 리뷰가 없습니다.", "No reviews to summarize.")
        return _save(plt, figure, output_path)

    analyzed = int(data.get("analyzed", 0))

    tiles = [
        (
            _title("전체 리뷰", "Total reviews"),
            _count(total),
            _title(
                f"분석 완료 {analyzed}건 "
                f"({data.get('analysis_rate', 0.0):.0%})",
                f"{analyzed} analyzed "
                f"({data.get('analysis_rate', 0.0):.0%})",
            ),
            INK,
        ),
        (
            _title("평균 별점", "Average rating"),
            f"{data.get('avg_rating', 0.0):.2f}",
            _title("5점 만점", "out of 5"),
            INK,
        ),
        (
            _title("평균 확신도", "Average confidence"),
            f"{data.get('avg_confidence', 0.0):.2f}",
            _title("모델이 스스로 매긴 값", "self-reported by model"),
            INK,
        ),
        (
            _title("긍정 비율", "Positive share"),
            f"{data.get('positive_ratio', 0.0):.0%}",
            _title(f"분석 {analyzed}건 기준", f"of {analyzed} analyzed"),
            SENTIMENT_COLOR["positive"],
        ),
        (
            _title("부정 비율", "Negative share"),
            f"{data.get('negative_ratio', 0.0):.0%}",
            _title(f"분석 {analyzed}건 기준", f"of {analyzed} analyzed"),
            SENTIMENT_COLOR["negative"],
        ),
        (
            _title("별점-감정 일치도", "Rating vs sentiment"),
            f"{data.get('rating_sentiment_agreement', 0.0):.0%}",
            _title("별점이 기대하는 감정과 같은 비율",
                   "matches the rating's expected sentiment"),
            INK,
        ),
    ]

    from matplotlib.patches import Rectangle

    columns = 3
    axes.set_xlim(0, columns)
    axes.set_ylim(0, 2)
    axes.axis("off")

    for index, (label, value, note, color) in enumerate(tiles):

        column = index % columns
        row = index // columns
        base_y = 1.0 - row          # 위쪽 줄이 row 0

        axes.add_patch(Rectangle(
            (column + 0.03, base_y + 0.07), 0.94, 0.86,
            facecolor=TILE, edgecolor="none",
        ))

        text_x = column + 0.11

        axes.text(text_x, base_y + 0.72, label,
                  fontsize=9.5, color=INK_MUTED, va="center")
        axes.text(text_x, base_y + 0.46, value,
                  fontsize=21, color=color, va="center", fontweight="bold")
        axes.text(text_x, base_y + 0.22, note,
                  fontsize=7.5, color=INK_MUTED, va="center")

    axes.set_title(
        _title("리뷰 분석 요약", "Review analysis at a glance"),
        fontsize=13, color=INK, pad=14, loc="left", fontweight="bold",
    )

    return _save(plt, figure, output_path)


# ============================================================
# 1. 감정 분포
# ============================================================

def draw_sentiment_distribution(data, output_path, dpi):
    """
    감정 분포 — 가로 막대.

    파이 차트를 쓰지 않는 이유
      3조각짜리 파이는 각도로 크기를 비교해야 해서 막대보다 읽기 어렵고,
      비슷한 두 조각의 대소가 눈으로 판별되지 않는다.
      막대는 같은 기준선에서 길이만 비교하면 된다.

    여기서는 감정 3개가 '축의 항목'이라 범례가 따로 필요 없다.
    (범례 규칙은 계열이 2개 이상일 때 적용된다)
    """

    values = [int(value) for value in data.get("values", [])]

    plt, figure, axes = _new_figure(7.2, 2.6, dpi)

    if not values or sum(values) == 0:
        _empty_state(figure, axes,
                     "아직 감정 분석된 리뷰가 없습니다.",
                     "No analyzed reviews yet.")
        return _save(plt, figure, output_path)

    total = sum(values)
    positions = list(range(len(SENTIMENT_ORDER)))[::-1]

    # 막대 끝을 둥글게 다듬는 방법을 먼저 써봤다가 되돌렸다.
    # FancyBboxPatch 의 rounding 은 데이터 좌표계에서 계산돼서
    # x축 스케일이 바뀔 때마다 모서리가 늘어나고 막대 위아래로
    # 가느다란 선이 새어 나왔다. 장식 하나 때문에 차트에 없는 선이
    # 그려지는 건 남는 장사가 아니다.
    for position, key, value in zip(positions, SENTIMENT_ORDER, values):

        axes.barh(
            position, value, height=0.46,
            color=SENTIMENT_COLOR[key], linewidth=0,
        )

        # 직접 라벨. 색만으로 의미가 전달되지 않게 하는 장치다.
        axes.text(
            value + total * 0.015, position,
            f"{_count(value)} ({value / total:.1%})",
            va="center", ha="left", fontsize=10, color=INK,
        )

    axes.set_yticks(positions)
    axes.set_yticklabels(
        [_labels(key) for key in SENTIMENT_ORDER], fontsize=11, color=INK
    )
    axes.set_xlim(0, total * 1.22)
    axes.set_ylim(-0.6, len(SENTIMENT_ORDER) - 0.4)
    axes.set_xticks([])

    axes.set_title(
        _title("감정 분포", "Sentiment distribution"),
        fontsize=13, color=INK, pad=14, loc="left", fontweight="bold",
    )
    axes.text(
        0, len(SENTIMENT_ORDER) - 0.5,
        _title(f"분석 완료 {total}건 기준", f"n = {total} analyzed"),
        fontsize=9, color=INK_MUTED, va="bottom",
    )

    _strip_frame(axes)

    return _save(plt, figure, output_path)


# ============================================================
# 2. 감정 추이
# ============================================================

def draw_sentiment_trend(data, output_path, dpi):
    """
    감정 추이 — 위: 건수 누적 막대 / 아래: 부정 비율 선.

    이중 축(dual-axis)을 쓰지 않는 이유
      '건수'와 '비율'은 단위가 다르다. 한 그림에 y축 두 개를 세우면
      두 계열의 교차점이 축 눈금을 어떻게 맞추느냐에 따라 마음대로 움직인다.
      실제로는 아무 의미 없는 교차가 인과처럼 읽힌다.
      그래서 위아래 패널로 나누고 x축만 공유한다.
    """

    labels = list(data.get("labels", []))

    if not labels:
        return None

    plt = _prepare_pyplot()

    figure, (top, bottom) = plt.subplots(
        2, 1, figsize=(max(7.2, len(labels) * 0.9), 5.4), dpi=dpi,
        sharex=True, gridspec_kw={"height_ratios": [2.2, 1]},
    )
    figure.patch.set_facecolor(SURFACE)

    for axes in (top, bottom):
        axes.set_facecolor(SURFACE)

    series = data.get("series", {})
    positions = list(range(len(labels)))
    bottoms = [0] * len(labels)

    for key in SENTIMENT_ORDER:
        values = list(series.get(key, []))

        # 계열 길이가 labels 와 다르면 zip 이 조용히 잘라버린다.
        # 짧은 쪽을 0으로 채워 어느 구간이 비었는지 보이게 한다.
        values = (values + [0] * len(labels))[:len(labels)]

        top.bar(
            positions, values, bottom=bottoms, width=0.6,
            color=SENTIMENT_COLOR[key], label=_labels(key),
            # 조각 사이 배경색 테두리 = 2px 간격.
            # 인접한 두 색이 맞붙으면 경계가 섞여 보인다.
            edgecolor=SURFACE, linewidth=1.6,
        )

        bottoms = [b + v for b, v in zip(bottoms, values)]

    # 직접 라벨은 선택적으로. 모든 조각에 숫자를 박으면 읽을 수 없다.
    # 막대 위 합계만 표기한다.
    for position, total in zip(positions, bottoms):

        if total:
            top.text(position, total + max(bottoms) * 0.03, str(total),
                     ha="center", fontsize=9, color=INK_MUTED)

    top.set_ylim(0, max(bottoms) * 1.18 if any(bottoms) else 1)
    top.set_title(
        _title("기간별 감정 추이", "Sentiment over time"),
        fontsize=13, color=INK, pad=14, loc="left", fontweight="bold",
    )
    top.set_ylabel(_title("건수", "Count"), fontsize=9, color=INK_MUTED)
    top.grid(axis="y", color=GRID, linewidth=0.8)
    top.set_axisbelow(True)

    # 계열이 3개이므로 범례는 필수다. 색만으로 정체를 알게 두면 안 된다.
    top.legend(
        frameon=False, fontsize=9, ncol=3,
        loc="upper left", bbox_to_anchor=(0, -0.06),
        labelcolor=INK,
    )

    ratios = list(data.get("negative_ratio", []))
    ratios = (ratios + [0.0] * len(labels))[:len(labels)]

    bottom.plot(
        positions, ratios, color=SENTIMENT_COLOR["negative"],
        linewidth=2, marker="o", markersize=5,
        markeredgecolor=SURFACE, markeredgewidth=1.5,
    )
    bottom.fill_between(
        positions, ratios, color=SENTIMENT_COLOR["negative"], alpha=0.10
    )
    bottom.set_ylim(0, max(ratios + [0.1]) * 1.35)
    bottom.set_ylabel(
        _title("부정 비율", "Negative %"), fontsize=9, color=INK_MUTED
    )
    bottom.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda value, _: f"{value:.0%}")
    )
    bottom.grid(axis="y", color=GRID, linewidth=0.8)
    bottom.set_axisbelow(True)

    granularity = data.get("granularity", "day")
    unit = {"day": ("일별", "daily"), "week": ("주별", "weekly"),
            "month": ("월별", "monthly")}.get(granularity, (granularity,) * 2)

    bottom.set_xticks(positions)
    bottom.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    bottom.set_xlabel(
        _title(f"집계 단위: {unit[0]}", f"granularity: {unit[1]}"),
        fontsize=9, color=INK_MUTED, labelpad=8,
    )

    for axes in (top, bottom):
        _strip_frame(axes)

    return _save(plt, figure, output_path)


# ============================================================
# 3. 별점 분포
# ============================================================

def draw_rating_distribution(data, output_path, dpi):
    """
    별점 분포 — 세로 막대. 감정과 무관한 단일 계열이다.

    감정 3색을 쓰지 않는 이유
      4점 막대를 긍정색으로 칠하면 '4점 = 긍정' 이라는 결론을
      차트가 미리 내려버린다. 그 대응 관계가 실제로 성립하는지를
      보려고 바로 아래 '별점별 감정 구성' 차트를 따로 두는 것이라,
      여기서 색으로 답을 말해버리면 두 차트가 같은 말을 하게 된다.
    """

    ratings = list(data.get("ratings", [1, 2, 3, 4, 5]))
    values = [int(value) for value in data.get("values", [])]
    values = (values + [0] * len(ratings))[:len(ratings)]

    plt, figure, axes = _new_figure(7.2, 3.0, dpi)

    if sum(values) == 0:
        _empty_state(figure, axes,
                     "별점이 입력된 리뷰가 없습니다.",
                     "No rated reviews.")
        return _save(plt, figure, output_path)

    total = sum(values)
    positions = list(range(len(ratings)))

    axes.bar(positions, values, width=0.56, color=ACCENT, linewidth=0)

    for position, value in zip(positions, values):
        axes.text(
            position, value + max(values) * 0.04,
            f"{value} ({value / total:.0%})",
            ha="center", fontsize=9, color=INK,
        )

    axes.set_xticks(positions)
    axes.set_xticklabels(
        [("★" * star) + ("☆" * (5 - star)) for star in ratings], fontsize=11
    )
    axes.set_ylim(0, max(values) * 1.2)
    axes.set_yticks([])

    axes.set_title(
        _title("별점 분포", "Rating distribution"),
        fontsize=13, color=INK, pad=14, loc="left", fontweight="bold",
    )
    axes.set_xlabel(
        _title(f"별점이 있는 리뷰 {total}건 기준", f"n = {total} rated"),
        fontsize=9, color=INK_MUTED, labelpad=8,
    )

    _strip_frame(axes)

    return _save(plt, figure, output_path)


# ============================================================
# 4. 그룹별 감정 구성 (별점 · 제품 · 피부타입 공용)
# ============================================================

def _draw_group_sentiment(labels, series, output_path, dpi,
                          title_ko, title_en, empty_ko, empty_en,
                          label_fontsize=11):
    """
    100% 누적 가로 막대. 별점·제품·피부타입이 모두 같은 질문에 답한다.

    건수가 아니라 비율로 그리는 이유
      그룹마다 리뷰 수가 다르다(5점 33건, 1점 8건). 건수로 그리면
      막대 길이가 '리뷰가 몇 개인지'를 말할 뿐,
      "5점 리뷰는 실제로 긍정으로 읽히는가" 라는 질문에 답하지 못한다.
      각 막대를 100%로 맞춰야 그룹 사이 구성 비교가 된다.

    건수는 막대 오른쪽에 따로 적는다. 3건짜리 막대의 100% 와
    30건짜리 막대의 100% 를 같은 무게로 읽으면 안 되기 때문이다.
    """

    # 막대 한 줄당 높이를 고정한다. 항목 수가 달라도 막대 두께가 같아야
    # 제품별 차트와 피부타입별 차트를 나란히 놓고 비교할 수 있다.
    height = max(2.4, 0.56 * len(labels) + 1.5)

    plt, figure, axes = _new_figure(7.6, height, dpi)

    totals = [
        sum(series.get(key, [0] * len(labels))[index]
            for key in SENTIMENT_ORDER)
        for index in range(len(labels))
    ]

    if not labels or sum(totals) == 0:
        _empty_state(figure, axes, empty_ko, empty_en)
        return _save(plt, figure, output_path)

    # 위에서 아래로 읽히도록 뒤집는다. barh 는 y가 클수록 위다.
    positions = list(range(len(labels)))[::-1]
    lefts = [0.0] * len(labels)

    for key in SENTIMENT_ORDER:
        counts = series.get(key, [0] * len(labels))
        shares = [
            (count / total if total else 0.0)
            for count, total in zip(counts, totals)
        ]

        axes.barh(
            positions, shares, left=lefts, height=0.62,
            color=SENTIMENT_COLOR[key], label=_labels(key),
            edgecolor=SURFACE, linewidth=1.6,
        )

        # 조각이 충분히 넓을 때만 안에 비율을 적는다.
        # 좁은 조각에 숫자를 넣으면 옆 조각을 침범한다.
        for position, share, left in zip(positions, shares, lefts):

            if share >= 0.13:
                axes.text(
                    left + share / 2, position, f"{share:.0%}",
                    ha="center", va="center", fontsize=9,
                    color="#ffffff" if key != "neutral" else INK,
                )

        lefts = [left + share for left, share in zip(lefts, shares)]

    axes.set_yticks(positions)
    axes.set_yticklabels(labels, fontsize=label_fontsize)
    axes.set_xlim(0, 1.16)
    # y 범위를 직접 잡는다. 자동으로 두면 항목이 3개일 때와 5개일 때
    # 막대 사이 간격이 달라져서 두 차트가 다른 그림처럼 보인다.
    axes.set_ylim(-0.65, len(labels) - 0.35)
    axes.set_xticks([])

    for position, total in zip(positions, totals):
        axes.text(
            1.02, position, _count(total),
            va="center", fontsize=9, color=INK_MUTED,
        )

    axes.set_title(
        _title(title_ko, title_en),
        fontsize=13, color=INK, pad=14, loc="left", fontweight="bold",
    )
    axes.legend(
        frameon=False, fontsize=9, ncol=3,
        loc="upper left", bbox_to_anchor=(0, -0.04), labelcolor=INK,
    )

    _strip_frame(axes)

    return _save(plt, figure, output_path)


def draw_rating_sentiment(data, output_path, dpi):
    """별점별 감정 구성."""

    ratings = list(data.get("ratings", [1, 2, 3, 4, 5]))

    return _draw_group_sentiment(
        labels=[("★" * star) + ("☆" * (5 - star)) for star in ratings],
        series=data.get("series", {}),
        output_path=output_path,
        dpi=dpi,
        title_ko="별점별 감정 구성",
        title_en="Sentiment by rating",
        empty_ko="별점과 감정이 함께 있는 리뷰가 없습니다.",
        empty_en="No reviews with both rating and sentiment.",
    )


def draw_product_sentiment(data, output_path, dpi):
    """
    제품별 감정 구성.

    "부정이 많다" 는 사실만으로는 다음 행동이 안 나온다.
    어느 제품에서 나온 부정인지가 붙어야 담당자가 정해진다.
    """

    labels = [_shorten(label) for label in data.get("labels", [])]

    return _draw_group_sentiment(
        labels=labels,
        series=data.get("series", {}),
        output_path=output_path,
        dpi=dpi,
        title_ko="제품별 감정 구성",
        title_en="Sentiment by product",
        empty_ko="제품명이 있는 분석 리뷰가 없습니다.",
        empty_en="No analyzed reviews with a product name.",
        label_fontsize=10,
    )


def draw_skin_type_sentiment(data, output_path, dpi):
    """
    피부타입별 감정 구성.

    B의 clean 데이터에 skin_type 이 들어 있는데 차트에서 한 번도
    쓰이지 않고 있었다. 같은 제품이 지성에서만 부정이 몰리는 식의
    패턴은 이 축을 세우지 않으면 보이지 않는다.
    """

    labels = [_shorten(label) for label in data.get("labels", [])]

    return _draw_group_sentiment(
        labels=labels,
        series=data.get("series", {}),
        output_path=output_path,
        dpi=dpi,
        title_ko="피부타입별 감정 구성",
        title_en="Sentiment by skin type",
        empty_ko="피부타입이 있는 분석 리뷰가 없습니다.",
        empty_en="No analyzed reviews with a skin type.",
        label_fontsize=10,
    )


# ============================================================
# 공개 함수
# ============================================================

DRAWERS = {
    "kpi_summary": draw_kpi_summary,
    "sentiment_distribution": draw_sentiment_distribution,
    "sentiment_trend": draw_sentiment_trend,
    "rating_distribution": draw_rating_distribution,
    "rating_sentiment": draw_rating_sentiment,
    "product_sentiment": draw_product_sentiment,
    "skin_type_sentiment": draw_skin_type_sentiment,
}


def generate_charts(chart_data, output_dir, config):
    """
    대시보드 차트를 그리고 {이름: 경로} dict 를 돌려준다.

    dict 로 돌려주는 이유
      리스트로 주면 순서가 곧 의미가 되어, 한 장이 빠지면 전부 밀린다.
      이름을 붙여두면 리포트가 원하는 차트를 골라 쓸 수 있다.
      (넣는 순서는 CHART_ORDER 를 따르므로 리포트에서 읽는 순서도 고정이다)

    데이터가 없어 못 그린 차트는 dict 에 넣지 않는다.
    빈 축만 있는 이미지를 리포트에 박는 것보다 없는 편이 낫다.
    다만 '분석이 아직 0건' 처럼 이유를 적을 수 있는 경우에는
    그 문장을 적은 그림을 남긴다. 차트가 사라지면 리포트를 보는 사람이
    빠뜨린 건지 없는 건지 구분할 수 없다.
    """

    from pathlib import Path

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    visualization = (config or {}).get("visualization", {})
    dpi = int(visualization.get("dpi", 150))
    suffix = visualization.get("save_format", "png")

    chart_data = chart_data or {}
    paths = {}

    for name in CHART_ORDER:

        data = chart_data.get(name)

        if not data:
            logger.warning("%s: chart_data 가 비어 건너뜁니다.", name)
            continue

        path = output_dir / f"{name}.{suffix}"

        try:
            result = DRAWERS[name](data, path, dpi)

        except Exception as error:
            # 차트 한 장이 실패해도 나머지와 리포트는 나와야 한다.
            logger.error("%s 생성 실패: %s", name, error)
            continue

        if result is None:
            logger.warning("%s: 그릴 데이터가 없어 건너뜁니다.", name)
            continue

        paths[name] = str(path)
        logger.info("차트 생성: %s", path.name)

    return paths
