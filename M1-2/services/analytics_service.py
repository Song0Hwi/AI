"""
시계열 데이터 요약 및 심화 통계 분석 서비스 (analytics_service.py)
- /api/data/summary: 시스템 프롬프트 컨텍스트 주입용 핵심 요약 생성
- /api/data/statistics: 보너스 과제용 확장 지표(이동평균, 변동성, 계절성, 이상치 탐지, 단기 예측) 계산
"""
import json
import math
from collections import defaultdict
from typing import List, Dict, Any, Optional

from config import BASE_DIR
from schemas import SummaryResponse, MetricsModel
from services.firebase_service import firebase_service


class AnalyticsService:
    def __init__(self):
        self.meta_path = BASE_DIR / "data" / "dataset_metadata.json"

    def _load_metadata(self) -> Dict[str, Any]:
        if self.meta_path.exists():
            try:
                with open(self.meta_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def get_summary(self) -> SummaryResponse:
        items = firebase_service.list_data()
        if not items:
            return SummaryResponse(
                period="데이터 없음",
                count=0,
                metrics=MetricsModel(total=0, average=0, max=0, min=0),
                trend="데이터 없음",
                recent_average=0,
                recent_change_pct=0,
                highlights=["저장된 시계열 데이터가 없습니다."],
            )

        values = [float(x["value"]) for x in items]
        count = len(values)
        total_val = round(sum(values), 1)
        avg_val = round(total_val / count, 1)

        max_item = max(items, key=lambda x: float(x["value"]))
        min_item = min(items, key=lambda x: float(x["value"]))
        max_val = round(float(max_item["value"]), 1)
        min_val = round(float(min_item["value"]), 1)

        # 표준편차 및 변동계수(CV) 계산
        variance = sum((v - avg_val) ** 2 for v in values) / max(1, count)
        std_dev = round(math.sqrt(variance), 1)
        cv_pct = round((std_dev / avg_val) * 100.0, 1) if avg_val > 0 else 0.0

        start_ym = items[0]["date"][:7]
        end_ym = items[-1]["date"][:7]
        period_str = f"{start_ym} ~ {end_ym}"

        # 최근 추세 계산: 최근 8개 포인트 vs 직전 8개 포인트 (및 전체 평균 대비)
        window = min(8, max(1, count // 4))
        recent_slice = values[-window:]
        prev_slice = values[-2 * window : -window] if count >= 2 * window else values[:-window]
        recent_avg = round(sum(recent_slice) / len(recent_slice), 1)
        prev_avg = round(sum(prev_slice) / len(prev_slice), 1) if prev_slice else avg_val

        change_pct = round(((recent_avg - prev_avg) / max(1.0, prev_avg)) * 100.0, 1)
        vs_overall_pct = round(((recent_avg - avg_val) / max(1.0, avg_val)) * 100.0, 1)

        if change_pct >= 3.0:
            direction = "상승"
            sign = "+"
        elif change_pct <= -3.0:
            direction = "하락"
            sign = ""
        else:
            direction = "유지/보합"
            sign = "+" if change_pct >= 0 else ""

        trend_str = (
            f"{direction} (직전 구간 대비 {sign}{change_pct}%, "
            f"전체 평균 대비 {'+' if vs_overall_pct >= 0 else ''}{vs_overall_pct}%)"
        )

        highlights = [
            f"전체 {count}개 주간 시계열 평균은 {avg_val:,.0f}건이며, 최근 {window}주 평균은 {recent_avg:,.0f}건({sign}{change_pct}%)입니다.",
            f"최고 신고접수 시점은 {max_item['date']} ({max_val:,.0f}건)이며, 최저 시점은 {min_item['date']} ({min_val:,.0f}건)입니다.",
            f"변동계수(CV)는 {cv_pct}%로 여름철(7~8월 폭염·집중호우) 및 연초 한파 구간에 뚜렷한 계절적 피크가 나타납니다.",
        ]

        return SummaryResponse(
            period=period_str,
            count=count,
            metrics=MetricsModel(
                total=total_val,
                average=avg_val,
                max=max_val,
                min=min_val,
                max_date=max_item["date"],
                min_date=min_item["date"],
                std_dev=std_dev,
                cv_percent=cv_pct,
            ),
            trend=trend_str,
            recent_average=recent_avg,
            recent_change_pct=change_pct,
            highlights=highlights,
        )

    def get_advanced_statistics(self) -> Dict[str, Any]:
        """보너스 과제: 확장 통계 지표 + 시계열 분해/이동평균/이상치/예측 데이터 반환"""
        items = firebase_service.list_data()
        summary = self.get_summary()
        meta = self._load_metadata()

        if not items:
            return {"summary": summary.model_dump(), "series": [], "outliers": []}

        values = [float(x["value"]) for x in items]
        avg_val = summary.metrics.average
        std_val = summary.metrics.std_dev or 1.0

        # 1. 이동평균(MA4, MA12) 및 Z-score 계산
        enriched_series = []
        outliers = []
        yearly_buckets = defaultdict(list)
        seasonal_buckets = defaultdict(list)
        monthly_buckets = defaultdict(list)

        for idx, item in enumerate(items):
            v = float(item["value"])
            d = item["date"]
            memo = item.get("memo", "")
            yr = d[:4]
            mo = d[5:7]

            ma4_slice = values[max(0, idx - 3) : idx + 1]
            ma12_slice = values[max(0, idx - 11) : idx + 1]
            ma4 = round(sum(ma4_slice) / len(ma4_slice), 1)
            ma12 = round(sum(ma12_slice) / len(ma12_slice), 1)
            z_score = round((v - avg_val) / max(1.0, std_val), 2)

            # 계절 추출
            season = "기타"
            for s_name in ["겨울", "봄", "여름", "가을"]:
                if f"[{s_name}" in memo:
                    season = s_name
                    break
            if season == "기타":
                m_int = int(mo)
                if m_int in (12, 1, 2):
                    season = "겨울"
                elif m_int in (3, 4, 5):
                    season = "봄"
                elif m_int in (6, 7, 8):
                    season = "여름"
                else:
                    season = "가을"

            yearly_buckets[yr].append(v)
            seasonal_buckets[season].append(v)
            monthly_buckets[f"{int(mo)}월"].append(v)

            point = {
                "id": item["id"],
                "date": d,
                "value": v,
                "ma4": ma4,
                "ma12": ma12,
                "z_score": z_score,
                "season": season,
                "memo": memo,
            }
            enriched_series.append(point)

            if abs(z_score) >= 1.5:
                outliers.append({
                    "date": d,
                    "value": v,
                    "z_score": z_score,
                    "type": "급증(Spike)" if z_score > 0 else "급감(Drop)",
                    "memo": memo,
                })

        # 2. 연도별 통계
        yearly_stats = {}
        for yr, vals in sorted(yearly_buckets.items()):
            yearly_stats[yr] = {
                "count": len(vals),
                "average": round(sum(vals) / len(vals), 1),
                "max": round(max(vals), 1),
                "min": round(min(vals), 1),
                "total": round(sum(vals), 1),
            }

        # 3. 계절별 통계
        seasonal_stats = {}
        for s_name in ["봄", "여름", "가을", "겨울"]:
            vals = seasonal_buckets.get(s_name, [])
            if vals:
                seasonal_stats[s_name] = {
                    "count": len(vals),
                    "average": round(sum(vals) / len(vals), 1),
                    "max": round(max(vals), 1),
                    "min": round(min(vals), 1),
                }

        # 4. 향후 4주 베이스라인 예측 (최근 8주 선형 추세 + 이동평균 결합)
        recent_n = min(8, len(values))
        recent_vals = values[-recent_n:]
        slope = (recent_vals[-1] - recent_vals[0]) / max(1, recent_n - 1) if recent_n > 1 else 0.0
        damped_slope = slope * 0.45  # 과도한 발산 방지 감쇠 계수
        base_level = sum(recent_vals[-4:]) / min(4, len(recent_vals))

        forecast = []
        for step in range(1, 5):
            pred_val = max(0.0, round(base_level + damped_slope * step, 0))
            forecast.append({
                "step": f"+{step}주 후",
                "predicted_value": pred_val,
                "confidence_low": round(pred_val * 0.9, 0),
                "confidence_high": round(pred_val * 1.1, 0),
            })

        return {
            "summary": summary.model_dump(),
            "yearly_statistics": yearly_stats,
            "seasonal_statistics": seasonal_stats,
            "outliers_count": len(outliers),
            "outliers": sorted(outliers, key=lambda x: abs(x["z_score"]), reverse=True)[:10],
            "forecast_next_4_weeks": forecast,
            "metadata_insights": {
                "top_regions": meta.get("top_regions", {}),
                "peak_hours_top5": meta.get("peak_hours_top5", {}),
                "day_of_week_distribution": meta.get("day_of_week_distribution", {}),
            },
            "series": enriched_series,
        }


analytics_service = AnalyticsService()
