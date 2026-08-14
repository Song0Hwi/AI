from pathlib import Path


def generate_markdown_report(
    stats=None,
    insights=None,
    chart_paths=None,
    output_path=None,
):
    """통계와 AI 인사이트를 받아 Markdown 리포트를 생성한다."""

    stats = stats or {}
    insights = insights or {}

    if isinstance(chart_paths, dict):
        chart_paths = list(chart_paths.values())
    elif chart_paths is None:
        chart_paths = []
    elif not isinstance(chart_paths, list):
        raise TypeError("chart_paths는 리스트, 딕셔너리 또는 None이어야 합니다.")

    lines = [
        "# 고객 리뷰 분석 리포트",
        "",
    ]

    if stats:
        summary = stats["summary"]
        quality = stats["quality"]
        top_n = stats["top_n"]

        lines.extend([
            "## 주요 통계",
            "",
            f"- 전체 리뷰 수: {summary['total']}",
            f"- 분석 완료: {summary['analyzed']}",
            f"- 미분석: {summary['unanalyzed']}",
            f"- 분석률: {summary['analysis_rate']:.1%}",
            f"- 평균 별점: {summary['avg_rating']:.2f}",
            f"- 평균 분석 신뢰도: {summary['avg_confidence']:.2f}",
            "",
            "### 감정 분포",
        ])

        sentiment_counts = summary["sentiment_counts"]
        sentiment_ratios = summary["sentiment_ratios"]

        sentiment_labels = {
            "positive": "긍정",
            "neutral": "중립",
            "negative": "부정",
        }

        for sentiment in ("positive", "neutral", "negative"):
            lines.append(
                f"- {sentiment_labels[sentiment]}: "
                f"{sentiment_counts[sentiment]}건 "
                f"({sentiment_ratios[sentiment]:.1%})"
            )

        lines.extend([
            "",
            "### 별점 분포",
        ])

        rating_counts = summary["rating_counts"]

        for star in range(1, 6):
            count = rating_counts.get(
                star,
                rating_counts.get(str(star), 0),
            )
            lines.append(f"- {star}점: {count}건")

        lines.extend([
            "",
            "## 품질 지표",
            "",
            f"- 별점-감정 일치도: "
            f"{quality['rating_sentiment_agreement']:.1%}",
            f"- 데이터 완전성: "
            f"{quality['data_completeness']:.1%}",
            f"- 평균 리뷰 길이: "
            f"{quality['avg_review_length']:.1f}자",
            "",
            "## TOP N",
            "",
        ])

        product_counts = top_n["product_counts"]
        if product_counts:
            lines.append("### 리뷰 수가 많은 제품")

            for rank, (name, count) in enumerate(
                product_counts,
                start=1,
            ):
                lines.append(f"{rank}. {name}: {count}건")

            lines.append("")

        skin_type_counts = top_n["skin_type_counts"]
        if skin_type_counts:
            lines.append("### 피부 타입별 리뷰 수")

            for rank, (name, count) in enumerate(
                skin_type_counts,
                start=1,
            ):
                lines.append(f"{rank}. {name}: {count}건")

            lines.append("")

        worst_reviews = top_n["worst_reviews"]
        if worst_reviews:
            lines.append("### 낮은 별점 리뷰")

            for review in worst_reviews:
                lines.append(
                    f"- [{review['rating']}점] "
                    f"{review['product_name']} / "
                    f"{sentiment_labels.get(review['sentiment'], review['sentiment'])} / "
                    f"{review['review_text']}"
                )

            lines.append("")

    lines.extend([
        "## AI 인사이트",
        "",
        "### 긍정 키워드",
    ])

    positive_keywords = insights.get("positive_keywords", [])
    if positive_keywords:
        lines.append(", ".join(positive_keywords))
    else:
        lines.append("없음")

    lines.extend([
        "",
        "### 부정 키워드",
    ])

    negative_keywords = insights.get("negative_keywords", [])
    if negative_keywords:
        lines.append(", ".join(negative_keywords))
    else:
        lines.append("없음")

    lines.extend([
        "",
        "### 전체 요약",
        insights.get("summary", "요약 결과가 없습니다."),
        "",
        "### 개선 제안",
    ])

    improvements = insights.get("improvements", [])
    if improvements:
        for improvement in improvements:
            lines.append(f"- {improvement}")
    else:
        lines.append("- 개선 제안이 없습니다.")

    if chart_paths:
        lines.extend([
            "",
            "## 시각화",
            "",
        ])

        for index, chart_path in enumerate(chart_paths, start=1):
            lines.append(f"![차트 {index}]({chart_path})")
            lines.append("")

    report_text = "\n".join(lines) + "\n"

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report_text, encoding="utf-8")

    return report_text