"""
2022~2025 소방청 전국 119 신고접수 현황 대용량 CSV 전처리 및 시계열 추출 스크립트
- 4개 연도(2022~2025, 총 약 7.8GB) 원본 CSV에서 균일 청크 스트리밍 샘플링을 수행하여
  100개 이상(약 140~180개)의 시계열 데이터 포인트(date, value, memo)를 생성합니다.
"""
import os
import sys
import json
import csv
from datetime import datetime, timedelta
from collections import defaultdict, Counter

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)


def parse_dt_diff_minutes(dt_start_str: str, dt_end_str: str):
    """YYYYMMDDHHMMSS 형식의 두 시각 차이를 분(minute) 단위로 계산 (이상치 제외)"""
    s1 = dt_start_str.strip(' "')
    s2 = dt_end_str.strip(' "')
    if len(s1) != 14 or len(s2) != 14 or not (s1.isdigit() and s2.isdigit()):
        return None
    try:
        t1 = datetime.strptime(s1, "%Y%m%d%H%M%S")
        t2 = datetime.strptime(s2, "%Y%m%d%H%M%S")
        diff_min = (t2 - t1).total_seconds() / 60.0
        if 0.5 <= diff_min <= 120.0:
            return diff_min
    except Exception:
        pass
    return None


def main():
    years = ["2022", "2023", "2024", "2025"]
    daily_stats = defaultdict(lambda: {
        "raw_count": 0,
        "scaled_count": 0.0,
        "seasons": Counter(),
        "regions": Counter(),
        "hours": Counter(),
        "urban_rural": Counter(),
        "arrival_mins": [],
    })

    total_file_bytes = 0
    total_sampled_rows = 0
    overall_regions = Counter()
    overall_seasons = Counter()
    overall_hours = Counter()
    overall_dow = Counter()
    year_summary = {}

    for yr in years:
        csv_path = os.path.join(BASE_DIR, f"119 신고접수 현황_{yr}_전국.csv")
        if not os.path.exists(csv_path):
            print(f"[WARN] 파일 없음: {csv_path}")
            continue

        file_size = os.path.getsize(csv_path)
        total_file_bytes += file_size

        # 파일당 500개 균일 오프셋에서 64KB씩 읽기 (~32MB/파일)
        n_chunks = 500
        chunk_size = 65536
        sampled_bytes = 0
        yr_rows = 0

        with open(csv_path, "rb") as f:
            # 첫 줄 헤더 스킵 확인
            header_line = f.readline()
            usable_size = max(1, file_size - len(header_line))

            for i in range(n_chunks):
                pos = len(header_line) + int(usable_size * i / n_chunks)
                f.seek(pos)
                raw_chunk = f.read(chunk_size)
                if not raw_chunk:
                    continue
                sampled_bytes += len(raw_chunk)
                text = raw_chunk.decode("utf-8", errors="ignore")
                lines = text.splitlines()
                # 첫 줄과 마지막 줄은 잘렸을 수 있으므로 제외
                if len(lines) <= 2:
                    continue
                valid_lines = lines[1:-1]

                for line in valid_lines:
                    parts = [p.strip(' "') for p in line.split(",")]
                    if len(parts) < 28:
                        continue
                    ymd = parts[2]
                    if len(ymd) != 8 or not ymd.isdigit():
                        continue
                    if not ymd.startswith(yr):
                        continue

                    date_str = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
                    hr = parts[7]
                    dow = parts[9]
                    season = parts[10]
                    region = parts[12] or parts[30]
                    urban_se = parts[15]
                    dspt_dt = parts[23]
                    arvl_dt = parts[24]

                    yr_rows += 1
                    total_sampled_rows += 1

                    st = daily_stats[date_str]
                    st["raw_count"] += 1
                    if season:
                        st["seasons"][season] += 1
                        overall_seasons[season] += 1
                    if region:
                        st["regions"][region] += 1
                        overall_regions[region] += 1
                    if hr and hr.isdigit():
                        h_int = int(hr)
                        st["hours"][h_int] += 1
                        overall_hours[f"{h_int:02d}시"] += 1
                    if dow:
                        overall_dow[dow] += 1
                    if urban_se:
                        st["urban_rural"][urban_se] += 1

                    diff_m = parse_dt_diff_minutes(dspt_dt, arvl_dt)
                    if diff_m is not None and len(st["arrival_mins"]) < 200:
                        st["arrival_mins"].append(diff_m)

        scale_factor = usable_size / max(1, sampled_bytes)
        est_total_rows = int(yr_rows * scale_factor)
        year_summary[yr] = {
            "file_size_mb": round(file_size / (1024 * 1024), 1),
            "sampled_rows": yr_rows,
            "scale_factor": round(scale_factor, 2),
            "estimated_total_records": est_total_rows,
        }
        print(f"[{yr}년] 크기: {file_size/(1024**2):.1f}MB | 샘플링 행: {yr_rows:,}건 | 추정 전체: {est_total_rows:,}건")

        # 일별 카운트에 스케일 팩터 반영
        for d_key, st in daily_stats.items():
            if d_key.startswith(yr):
                st["scaled_count"] = st["raw_count"] * scale_factor

    sorted_dates = sorted(daily_stats.keys())
    print(f"총 고유 일자(Daily) 수: {len(sorted_dates)}일 ({sorted_dates[0]} ~ {sorted_dates[-1]})")

    # 주간(Weekly, 월요일 기준) 단위로 집계하되, 포인트 수가 100개 이상이 되도록 구성
    # 먼저 주간(Weekly) 그룹핑 개수 확인
    weekly_groups = defaultdict(list)
    for d_str in sorted_dates:
        dt = datetime.strptime(d_str, "%Y-%m-%d")
        # ISO 주간 시작일(월요일)
        week_start = (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")
        weekly_groups[week_start].append(d_str)

    print(f"총 고유 주간(Weekly) 수: {len(weekly_groups)}주")

    # 만약 주간 포인트가 110개 이상이면 주간 시계열 사용, 아니면 5일(Pentad)/일별 시계열 사용
    if len(weekly_groups) >= 110:
        bucket_mode = "weekly"
        buckets = sorted(weekly_groups.items(), key=lambda x: x[0])
    else:
        # 반주(3~4일) 또는 일별 상위/균일 구간으로 150개 시계열 포인트 구성
        bucket_mode = "daily_or_subweekly"
        buckets = []
        for d_str in sorted_dates:
            buckets.append((d_str, [d_str]))

    records = []
    for bucket_date, date_list in buckets:
        if bucket_date < "2022-01-01" or bucket_date > "2025-09-21":
            continue
        days_observed = len(date_list)
        if days_observed < 3:
            continue
        raw_sum = sum(daily_stats[d]["raw_count"] for d in date_list)
        if raw_sum < 30:
            continue
        # 관측 일수 기준 주간(7일) 환산 신고접수 건수로 정규화하여 부분 주간 왜곡 방지
        scaled_sum = int(round(sum(daily_stats[d]["scaled_count"] for d in date_list) * (7.0 / days_observed)))
        merged_seasons = Counter()
        merged_regions = Counter()
        merged_hours = Counter()
        merged_urban = Counter()
        merged_arrivals = []

        for d in date_list:
            st = daily_stats[d]
            merged_seasons.update(st["seasons"])
            merged_regions.update(st["regions"])
            merged_hours.update(st["hours"])
            merged_urban.update(st["urban_rural"])
            merged_arrivals.extend(st["arrival_mins"])

        season_str = merged_seasons.most_common(1)[0][0] if merged_seasons else "기타"
        top_regs = merged_regions.most_common(2)
        reg_total = sum(merged_regions.values()) or 1
        if len(top_regs) >= 2:
            reg_desc = f"{top_regs[0][0]}({top_regs[0][1]*100/reg_total:.1f}%)·{top_regs[1][0]}({top_regs[1][1]*100/reg_total:.1f}%)"
            top_reg_name = top_regs[0][0]
        elif len(top_regs) == 1:
            reg_desc = f"{top_regs[0][0]}({top_regs[0][1]*100/reg_total:.1f}%)"
            top_reg_name = top_regs[0][0]
        else:
            reg_desc = "전국"
            top_reg_name = "전국"

        peak_hr = f"{merged_hours.most_common(1)[0][0]:02d}시" if merged_hours else "14시"
        urban_total = sum(merged_urban.values()) or 1
        urban_ratio = round(merged_urban.get("도시", 0) * 100.0 / urban_total, 1)
        avg_arrival = round(sum(merged_arrivals) / len(merged_arrivals), 1) if merged_arrivals else 7.5

        value = scaled_sum if bucket_mode == "weekly" else int(round(scaled_sum / days_observed))
        unit_label = "주간 접수" if bucket_mode == "weekly" else "일일 접수"

        memo = (
            f"[{season_str}] 전국 119 {unit_label} | 최다 지역: {reg_desc} | "
            f"피크 시간대: {peak_hr} | 평균 현장도착: {avg_arrival}분 (도시 비중 {urban_ratio}%)"
        )

        records.append({
            "date": bucket_date,
            "value": value,
            "memo": memo,
            "season": season_str,
            "top_region": top_reg_name,
            "avg_arrival_min": avg_arrival,
            "urban_ratio": urban_ratio,
            "peak_hour": peak_hr,
        })

    # 만약 일별 레코드가 너무 많으면(예: 500개 이상) 주간(Weekly)으로 재집계하거나 150~180개 핵심 시계열로 정렬
    print(f"1차 생성 시계열 포인트 수: {len(records)}개 (모드: {bucket_mode})")

    if len(records) > 200:
        # 5일(Pentad) 단위 시계열로 집계하여 약 140~180개의 균일하고 밀도 높은 시계열 포인트 생성
        pentad_groups = defaultdict(list)
        for r in records:
            dt = datetime.strptime(r["date"], "%Y-%m-%d")
            # 각 월을 1일, 6일, 11일, 16일, 21일, 26일(월 6구간)로 그룹핑 -> 연 72구간, 2.5~3년치면 약 140~180개!
            p_day = min(26, ((dt.day - 1) // 5) * 5 + 1)
            p_date = f"{dt.year:04d}-{dt.month:02d}-{p_day:02d}"
            pentad_groups[p_date].append(r)

        compact_records = []
        for p_date, grp in sorted(pentad_groups.items()):
            avg_val = int(round(sum(x["value"] for x in grp) / len(grp)))
            season_str = Counter(x["season"] for x in grp).most_common(1)[0][0]
            top_reg = Counter(x["top_region"] for x in grp).most_common(1)[0][0]
            avg_arr = round(sum(x["avg_arrival_min"] for x in grp) / len(grp), 1)
            urb_rat = round(sum(x["urban_ratio"] for x in grp) / len(grp), 1)
            pk_hr = Counter(x["peak_hour"] for x in grp).most_common(1)[0][0]
            # 대표 메모 구성
            memo = (
                f"[{season_str}·5일 평균] 일평균 {avg_val:,}건 | 주요 시도: {top_reg} | "
                f"피크: {pk_hr} | 평균 현장도착: {avg_arr}분 (도시 {urb_rat}%)"
            )
            compact_records.append({
                "date": p_date,
                "value": avg_val,
                "memo": memo,
                "season": season_str,
                "top_region": top_reg,
                "avg_arrival_min": avg_arr,
                "urban_ratio": urb_rat,
                "peak_hour": pk_hr,
            })
        records = compact_records
        print(f"5일(Pentad) 균일 시계열 집계 완료: 총 {len(records)}개 데이터 포인트")

    out_csv = os.path.join(DATA_DIR, "119_timeseries.csv")
    fieldnames = ["date", "value", "memo", "season", "top_region", "avg_arrival_min", "urban_ratio", "peak_hour"]
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    meta = {
        "dataset_title": "소방청 전국 119 신고접수 현황 시계열 데이터 (2022~2025)",
        "source": "공공데이터포털 / 소방청 (119 신고접수 현황_2022~2025_전국.csv)",
        "total_raw_size_gb": round(total_file_bytes / (1024**3), 2),
        "total_sampled_rows": total_sampled_rows,
        "timeseries_points_count": len(records),
        "period_start": records[0]["date"] if records else "",
        "period_end": records[-1]["date"] if records else "",
        "year_summary": year_summary,
        "top_regions": dict(overall_regions.most_common(10)),
        "season_distribution": dict(overall_seasons),
        "day_of_week_distribution": dict(overall_dow),
        "peak_hours_top5": dict(overall_hours.most_common(5)),
    }
    out_meta = os.path.join(DATA_DIR, "dataset_metadata.json")
    with open(out_meta, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"저장 완료: {out_csv} ({len(records)}개 포인트)")
    print(f"메타데이터: {out_meta}")


if __name__ == "__main__":
    main()
