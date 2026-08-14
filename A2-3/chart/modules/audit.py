# ============================================================
# A 담당 · AI 결과 검수 (평가 #16)
#
# 왜 필요한가
#   감정 분석 정확도를 스스로 잴 수단이 없으면 프롬프트를 고쳐도
#   나아졌는지 알 수 없다. "그럴듯해 보인다" 로는 v1 과 v2 를 못 고른다.
#
#   stats 의 '별점-감정 일치도' 는 이 검수를 대체하지 못한다.
#   별점은 사람 라벨이 아니라 다른 신호다. 낮으면 의심할 근거는 되지만,
#   별점을 후하게 주는 사람이 많은 채널이면 일치도가 낮아도 분석은 맞을 수 있다.
#   정확도는 사람이 매긴 라벨과 비교해야만 나온다.
#
# 이 파일이 하는 일 세 가지
#   1. 표본 뽑기      — 계통 추출 + 소수 감정 전량 포함
#   2. 라벨 받아오기   — 사람이 채운 CSV 를 읽어 DB에 저장
#   3. 점수 내기      — 일치율 · 혼동 방향 · 확신도 구간별 · 버전별 A/B
#
# 판단은 하지 않는다. 숫자를 내놓고 기준선을 같이 적어줄 뿐이다.
# ============================================================

import csv
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from modules.logger import get_logger


logger = get_logger("audit")


SENTIMENTS = ["positive", "neutral", "negative"]

# 검수자가 한글로 적는 경우가 훨씬 많다. 영문 값을 외우게 하지 않는다.
LABEL_ALIASES = {
    "긍정": "positive", "중립": "neutral", "부정": "negative",
    "p": "positive", "n": "neutral", "g": "negative",
    "positive": "positive", "neutral": "neutral", "negative": "negative",
}

LABEL_KO = {"positive": "긍정", "neutral": "중립", "negative": "부정"}

# 검수 CSV 의 열. 앞 8개는 A가 채워 내보내고, 뒤 2개를 사람이 채운다.
COLUMNS = [
    "review_id", "batch", "rating", "product_name", "skin_type",
    "review_text", "ai_sentiment", "ai_confidence", "ai_model",
    "검수라벨", "메모",
]

# 판정 기준선. 근거는 chart/README.md 4.11.
AGREEMENT_FLOOR = 0.80        # AI ↔ 최종 라벨
INTER_RATER_FLOOR = 0.85      # 검수자 ↔ 검수자


def normalize_label(text):
    """'긍정' · 'Positive' · ' positive ' 를 모두 positive 로."""

    if text is None:
        return None

    key = str(text).strip().lower()

    return LABEL_ALIASES.get(key)


def new_batch_id():
    """검수 회차 이름. 파일명과 DB 양쪽에서 같은 값을 쓴다."""

    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# 1. 표본 뽑기
# ============================================================

def pick_sample(reviews, size=30):
    """
    검수할 표본을 고른다.

    계통 추출을 쓰는 이유
      무작위로 뽑으면 돌릴 때마다 표본이 바뀌어 프롬프트 v1 과 v2 를
      같은 표본으로 비교할 수 없다. id 순으로 일정 간격을 띄우면
      같은 데이터에서 항상 같은 표본이 나온다. 재현이 되는 쪽이 낫다.

    소수 감정을 전량 넣는 이유
      99건에서 부정이 4건이면, 30건을 고르게 뽑아도 부정이 한두 건밖에
      안 들어간다. 그러면 "부정을 잘 잡는가" 를 잴 수 없다.
      가장 적은 감정은 통째로 넣고 나머지를 계통 추출로 채운다.

    표본이 요청 수보다 적을 수 있다. 분석된 리뷰가 그것뿐이면 그렇다.
    """

    analyzed = [r for r in reviews if r.get("sentiment")]

    if not analyzed:
        return []

    if len(analyzed) <= size:
        return list(analyzed)

    counts = Counter(r["sentiment"] for r in analyzed)
    rarest = min(counts, key=lambda key: counts[key])

    picked = {r["id"]: r for r in analyzed if r["sentiment"] == rarest}

    # 남은 자리를 계통 추출로 채운다.
    remaining = [r for r in analyzed if r["id"] not in picked]
    slots = size - len(picked)

    if slots > 0 and remaining:
        step = max(1, len(remaining) // slots)

        for review in remaining[::step][:slots]:
            picked[review["id"]] = review

    sample = sorted(picked.values(), key=lambda r: r["id"])

    logger.info(
        "검수 표본 %d건 (분석 %d건 중) · '%s' %d건 전량 포함",
        len(sample), len(analyzed), rarest, counts[rarest],
    )

    return sample


def write_sample_csv(sample, batch, output_path):
    """검수용 CSV 를 쓴다. 검수자는 마지막 두 열만 채우면 된다."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # utf-8-sig 로 쓴다. Excel 이 utf-8 을 cp949 로 읽어
    # 한글이 전부 깨지는 걸 막는다. 검수는 대개 Excel 로 한다.
    with open(output_path, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()

        for review in sample:
            writer.writerow({
                "review_id": review["id"],
                "batch": batch,
                "rating": review.get("rating"),
                "product_name": review.get("product_name") or "",
                "skin_type": review.get("skin_type") or "",
                "review_text": review.get("review_text"),
                "ai_sentiment": review.get("sentiment"),
                "ai_confidence": review.get("confidence"),
                "ai_model": review.get("model") or "",
                "검수라벨": "",
                "메모": "",
            })

    return output_path


# ============================================================
# 2. 라벨 받아오기
# ============================================================

def read_labeled_csv(file_path, reviewer):
    """
    사람이 채운 CSV 를 읽어 저장용 dict 리스트로 바꾼다.

    반환: (records, problems)

    빈 칸은 조용히 건너뛴다. 30건 중 20건만 채워 온 경우가 흔하고,
    그걸 오류로 막으면 나눠서 검수할 수가 없다.
    대신 **못 알아본 라벨은 problems 로 올린다.** '보통' 이라고 적어온 걸
    조용히 버리면 검수자는 자기가 매긴 게 반영된 줄 안다.
    """

    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"검수 파일을 찾을 수 없습니다: {file_path}")

    records = []
    problems = []

    with open(file_path, "r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames or "검수라벨" not in reader.fieldnames:
            raise ValueError(
                "'검수라벨' 열이 없습니다. "
                "`review sample` 이 만든 파일을 그대로 채워 주세요."
            )

        for line_number, row in enumerate(reader, start=2):
            raw = (row.get("검수라벨") or "").strip()

            if not raw:
                continue

            sentiment = normalize_label(raw)

            if sentiment is None:
                problems.append(
                    f"{line_number}행: 알 수 없는 라벨 {raw!r} "
                    f"(긍정 / 중립 / 부정 중 하나로 적어 주세요)"
                )
                continue

            try:
                review_id = int(row["review_id"])

            except (KeyError, TypeError, ValueError):
                problems.append(f"{line_number}행: review_id 를 읽을 수 없습니다")
                continue

            confidence = (row.get("ai_confidence") or "").strip()

            records.append({
                "review_id": review_id,
                "batch": (row.get("batch") or "unknown").strip(),
                "reviewer": reviewer,
                "sentiment": sentiment,
                "note": (row.get("메모") or "").strip() or None,
                "ai_sentiment": (row.get("ai_sentiment") or "").strip() or None,
                "ai_confidence": float(confidence) if confidence else None,
                "ai_model": (row.get("ai_model") or "").strip() or None,
            })

    return records, problems


# ============================================================
# 3. 점수 내기
# ============================================================

def _majority(labels):
    """
    검수자들의 라벨을 하나로 합친다.

    갈리면(2인이 서로 다르게 매기면) None 이다. 임의로 한쪽을 고르면
    그 순간 '검수자 간 불일치' 라는 정보가 사라진다. 그건 따로 세야
    "AI 가 틀린 건지 기준이 모호한 건지" 를 가릴 수 있다.
    """

    counts = Counter(labels)
    top, count = counts.most_common(1)[0]

    if list(counts.values()).count(count) > 1:
        return None

    return top


def score(labels):
    """
    검수 라벨을 받아 지표를 낸다.

    labels: fetch_human_labels() 결과

    돌려주는 것
      agreement        AI ↔ 최종 라벨 일치율
      inter_rater      검수자 ↔ 검수자 일치율 (2인 이상 매긴 건만)
      confusion        (AI 라벨, 최종 라벨) 별 건수 — 어느 쌍이 뒤집히는가
      by_confidence    확신도 구간별 일치율
      by_model         모델·프롬프트 버전별 일치율 (A/B 비교)
      disputed         검수자끼리 갈린 건
    """

    if not labels:
        return None

    # review_id + batch 로 묶는다. 같은 리뷰라도 회차가 다르면 다른 검수다.
    grouped = defaultdict(list)

    for label in labels:
        grouped[(label["batch"], label["review_id"])].append(label)

    agreed = total = 0
    confusion = Counter()
    by_confidence = defaultdict(lambda: [0, 0])   # [일치, 전체]
    by_model = defaultdict(lambda: [0, 0])
    disputed = []

    inter_agreed = inter_total = 0

    for (batch, review_id), group in sorted(grouped.items()):
        human = _majority([item["sentiment"] for item in group])

        if len(group) > 1:
            inter_total += 1

            if len({item["sentiment"] for item in group}) == 1:
                inter_agreed += 1

        if human is None:
            disputed.append({
                "batch": batch,
                "review_id": review_id,
                "labels": {item["reviewer"]: item["sentiment"]
                           for item in group},
            })
            continue

        ai = group[0].get("ai_sentiment")

        if not ai:
            continue

        total += 1
        match = int(ai == human)
        agreed += match
        confusion[(ai, human)] += 1

        model = group[0].get("ai_model") or "(미상)"
        by_model[model][0] += match
        by_model[model][1] += 1

        confidence = group[0].get("ai_confidence")

        if confidence is not None:
            bucket = _confidence_bucket(float(confidence))
            by_confidence[bucket][0] += match
            by_confidence[bucket][1] += 1

    return {
        "reviews": total,
        "labels": len(labels),
        "batches": sorted({label["batch"] for label in labels}),
        "reviewers": sorted({label["reviewer"] for label in labels}),
        "agreement": agreed / total if total else 0.0,
        "agreement_floor": AGREEMENT_FLOOR,
        "inter_rater": (
            inter_agreed / inter_total if inter_total else None
        ),
        "inter_rater_pairs": inter_total,
        "inter_rater_floor": INTER_RATER_FLOOR,
        "confusion": dict(confusion),
        "by_confidence": {
            bucket: {"agreed": hit, "total": count,
                     "rate": hit / count if count else 0.0}
            for bucket, (hit, count) in sorted(by_confidence.items())
        },
        "by_model": {
            model: {"agreed": hit, "total": count,
                    "rate": hit / count if count else 0.0}
            for model, (hit, count) in sorted(by_model.items())
        },
        "disputed": disputed,
    }


def _confidence_bucket(confidence):
    """확신도를 구간으로 자른다."""

    if confidence >= 0.9:
        return "0.90~1.00"

    if confidence >= 0.8:
        return "0.80~0.89"

    if confidence >= 0.7:
        return "0.70~0.79"

    return "~0.69"


def format_score(result):
    """검수 결과를 콘솔용 문자열로."""

    if result is None:
        return (
            "검수 라벨이 없습니다.\n"
            "  1) python main.py review sample --size 30\n"
            "  2) 만들어진 CSV 의 '검수라벨' 열을 채웁니다\n"
            "  3) python main.py review load --file <경로> --reviewer <이름>"
        )

    lines = [
        "",
        "=== AI 검수 결과 ===",
        f"검수 회차: {', '.join(result['batches'])}",
        f"검수자   : {', '.join(result['reviewers'])}",
        f"대상     : {result['reviews']}건 (라벨 {result['labels']}개)",
        "",
    ]

    rate = result["agreement"]
    floor = result["agreement_floor"]
    mark = "OK" if rate >= floor else "미달"

    lines.append(
        f"AI-사람 일치율   : {rate:.1%}  (기준 {floor:.0%}) [{mark}]"
    )

    if rate < floor:
        lines.append(
            "  → 프롬프트를 손볼 차례입니다. 아래 혼동 방향을 먼저 보세요."
        )

    if result["inter_rater"] is not None:
        inter = result["inter_rater"]
        inter_floor = result["inter_rater_floor"]
        inter_mark = "OK" if inter >= inter_floor else "미달"

        lines.append(
            f"검수자 간 일치율 : {inter:.1%}  "
            f"({result['inter_rater_pairs']}건 · 기준 {inter_floor:.0%}) "
            f"[{inter_mark}]"
        )

        if inter < inter_floor:
            lines.append(
                "  → AI 보다 라벨 기준이 먼저입니다. "
                "사람끼리 갈리는데 AI 만 고쳐봐야 소용없습니다."
            )

    else:
        lines.append(
            "검수자 간 일치율 : 계산 불가 (2인 이상 매긴 건이 없습니다)"
        )

    wrong = [
        (pair, count) for pair, count in result["confusion"].items()
        if pair[0] != pair[1]
    ]

    if wrong:
        lines.append("\n[혼동 방향] AI 판정 → 사람 판정")

        for (ai, human), count in sorted(wrong, key=lambda x: -x[1]):
            lines.append(
                f"- {LABEL_KO.get(ai, ai)} → {LABEL_KO.get(human, human)}"
                f" : {count}건"
            )

    if result["by_confidence"]:
        lines.append("\n[확신도 구간별 일치율]")

        for bucket, row in sorted(result["by_confidence"].items(),
                                  reverse=True):
            lines.append(
                f"- {bucket} : {row['rate']:.1%} "
                f"({row['agreed']}/{row['total']})"
            )

        lines.append(
            "  확신도가 높은데 일치율이 낮으면 프롬프트가 "
            "잘못된 확신을 주고 있는 것입니다."
        )

    if len(result["by_model"]) > 1:
        lines.append("\n[모델·프롬프트 버전별] ← A/B 비교")

        for model, row in sorted(result["by_model"].items(),
                                 key=lambda x: -x[1]["rate"]):
            lines.append(
                f"- {model} : {row['rate']:.1%} "
                f"({row['agreed']}/{row['total']})"
            )

    elif result["by_model"]:
        model = next(iter(result["by_model"]))
        lines.append(
            f"\n[모델] {model} 한 종류뿐입니다. "
            f"프롬프트를 바꿔 재분석한 뒤 같은 표본을 다시 검수하면 "
            f"여기서 버전별로 비교됩니다."
        )

    if result["disputed"]:
        lines.append(f"\n[검수자 간 불일치] {len(result['disputed'])}건")

        for item in result["disputed"][:5]:
            pairs = " / ".join(
                f"{name}={LABEL_KO.get(value, value)}"
                for name, value in item["labels"].items()
            )
            lines.append(f"- id {item['review_id']}: {pairs}")

    return "\n".join(lines)


def log_score(result):
    """검수 결과를 로그 파일에 남긴다. 회차별 추이를 나중에 볼 수 있게."""

    if result is None:
        return

    logger.info(
        "검수 결과 | 회차 %s | 대상 %d건 | 일치율 %.4f (기준 %.2f) | "
        "검수자간 %s | 불일치 %d건",
        ",".join(result["batches"]), result["reviews"],
        result["agreement"], result["agreement_floor"],
        f"{result['inter_rater']:.4f}"
        if result["inter_rater"] is not None else "-",
        len(result["disputed"]),
    )

    for model, row in sorted(result["by_model"].items()):
        logger.info(
            "검수 결과 | 모델 %s | 일치율 %.4f (%d/%d)",
            model, row["rate"], row["agreed"], row["total"],
        )

    for (ai, human), count in sorted(result["confusion"].items()):

        if ai != human:
            logger.info("검수 결과 | 혼동 %s -> %s | %d건", ai, human, count)

    if result["agreement"] < result["agreement_floor"]:
        logger.warning(
            "검수 일치율이 기준 미달입니다: %.1f%% < %.0f%%",
            result["agreement"] * 100, result["agreement_floor"] * 100,
        )
