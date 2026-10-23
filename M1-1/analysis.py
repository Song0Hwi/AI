"""
AXIS-Y 비건 콜라겐 아이 세럼 아마존 리뷰 시계열 데이터 정제 및 심층 분석 스크립트
- 입력: data/axis_y_reviews_raw.xlsx (Reviews, Summary, StarDistribution 시트)
- 출력:
  1) data/reviews_cleaned.csv (정제 및 특성 공학이 완료된 개별 리뷰 데이터, 478건)
  2) data/timeseries_daily.csv (일별 시계열 집계 및 이동평균 데이터, 324개 활성일 / 873일 전체 캘린더)
  3) data/timeseries_weekly.csv (주별 시계열 집계 및 이동평균 데이터, 126주)
  4) data/timeseries_monthly.csv (월별 시계열 집계, 변화율, 가중평점, 토픽 비중 데이터, 26개월)
  5) images/01 ~ 06 시각화 차트 (총 6종 PNG)
"""

import os
import sys
import re
import json
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8')

plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.dpi'] = 150

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
IMG_DIR = os.path.join(BASE_DIR, 'images')
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(IMG_DIR, exist_ok=True)

RAW_XLSX = os.path.join(DATA_DIR, 'axis_y_reviews_raw.xlsx')


def load_and_clean_data():
    print("=" * 70)
    print("[1단계] 원본 데이터 로드 및 시계열 정제 시작")
    print("=" * 70)

    df_raw = pd.read_excel(RAW_XLSX, sheet_name='Reviews')
    df_summary = pd.read_excel(RAW_XLSX, sheet_name='Summary')
    df_star = pd.read_excel(RAW_XLSX, sheet_name='StarDistribution')

    print(f"- 원본 리뷰 데이터 행 수: {len(df_raw)}건, 컬럼 수: {df_raw.shape[1]}개")
    print(f"- 원본 결측치 현황:\n{df_raw.isnull().sum().to_dict()}")

    df = df_raw.copy()

    # 1) 날짜 및 국가 파싱 ("Reviewed in the United States on August 17, 2026")
    def parse_date_country(val):
        m = re.match(r'Reviewed in (?:the )?(.+?) on (.+)', str(val))
        return (m.group(1).strip(), m.group(2).strip()) if m else (None, None)

    parsed = df['date'].apply(parse_date_country)
    df['country'] = [p[0] for p in parsed]
    df['review_date'] = pd.to_datetime([p[1] for p in parsed])

    # 2) 별점 수치화 ("5.0 out of 5 stars" -> 5.0)
    df['rating_num'] = df['rating'].str.extract(r'(\d+\.\d+)').astype(float)

    # 3) 결측치 및 이상치 플래그 정의 및 처리
    df['is_title_missing'] = df['title'].isnull()
    df['is_body_missing'] = df['body'].isnull()
    df['is_empty_text'] = df['title'].isnull() & df['body'].isnull()
    df['is_name_anomaly'] = df['reviewer_name'].astype(str).str.len() > 35

    df['reviewer_name_clean'] = np.where(
        df['is_name_anomaly'],
        'Anonymous_User (Name Anomaly Cleaned)',
        df['reviewer_name'].astype(str).str.strip()
    )

    df['title_clean'] = df['title'].fillna('').astype(str).str.strip()
    df['body_clean'] = (
        df['body']
        .fillna('')
        .astype(str)
        .str.replace(r'^Click to play video\s*', '', regex=True)
        .str.strip()
    )
    df['has_video'] = df['body'].fillna('').astype(str).str.contains('Click to play video', regex=False)
    df['full_text'] = (df['title_clean'] + ' ' + df['body_clean']).str.strip()
    df['text_length'] = df['full_text'].str.len()
    df['word_count'] = df['full_text'].apply(lambda x: len(x.split()) if x else 0)

    # 4) 모집단 가중치(Population Weight) 산출 (층화 표집 편향 보정)
    pop_share = dict(zip(df_star['star'].astype(float), df_star['percent'] / 100.0))
    sample_share = (df['rating_num'].value_counts() / len(df)).to_dict()
    pop_weights = {star: pop_share[star] / sample_share[star] for star in pop_share}
    df['pop_weight'] = df['rating_num'].map(pop_weights).round(4)

    # 5) 파생 시계열 변수 및 지역/감성 그룹 생성
    df = df.sort_values(['review_date', 'rating_num'], ascending=[True, False]).reset_index(drop=True)
    df['review_id'] = [f'REV_{i+1:04d}' for i in range(len(df))]
    df['year'] = df['review_date'].dt.year
    df['year_month'] = df['review_date'].dt.strftime('%Y-%m')
    df['year_quarter'] = df['review_date'].dt.to_period('Q').astype(str)
    df['week_start'] = df['review_date'].dt.to_period('W').apply(lambda r: r.start_time.strftime('%Y-%m-%d'))
    df['day_of_week'] = df['review_date'].dt.day_name()
    df['dow_num'] = df['review_date'].dt.dayofweek

    df['region_group'] = np.where(df['country'] == 'United States', 'US (미국)', 'Global (비미국 18개국)')
    df['sentiment_group'] = np.select(
        [df['rating_num'] >= 4.0, df['rating_num'] == 3.0, df['rating_num'] <= 2.0],
        ['Positive (4~5★)', 'Neutral (3★)', 'Negative (1~2★)'],
        default='Neutral (3★)'
    )
    df['verified_bool'] = df['verified_purchase'] == 'Y'

    # 6) 다국어 키워드 기반 토픽/이슈 분류
    patterns = {
        'topic_cooling_roller': r'(?:cool\w*|cold|roller\w*|ball|metal\w*|applicat\w*|aplicador|applicatore|applicateur|fresc\w*|froid\w*|kühl\w*|rodillo|sfera|bille|fridge|refrigerator|roll\w*|refresh\w*|rinfresc\w*)',
        'topic_hydration': r'(?:hydrat\w*|moistur\w*|dry\w*|trocken\w*|hidrat\w*|idrat\w*|secc\w*|sèche|resequedad|feucht\w*|humect\w*)',
        'topic_depuff': r'(?:puff\w*|depuff\w*|bag\w*|bolsa\w*|bolsita\w*|borse|sgonfi\w*|poche\w*|desinflam\w*|schwell\w*)',
        'topic_brightening': r'(?:dark\w*|circle\w*|bright\w*|ojera\w*|occhiaie|cerne\w*|augenring\w*|pigment\w*|discoloration|lighten\w*|aclar\w*|schiar\w*|luminos\w*)',
        'topic_wrinkles': r'(?:wrinkl\w*|line\w*|crease\w*|falten|arruga\w*|rughe|ride\w*|plump\w*|firm\w*|smooth\w*|tersa)',
        'raw_irritation': r'(?:\bburn\w*|\bsting\w*|\bstung\b|allerg\w*|\brash\w*|\bitch\w*|milia|\bbump\w*|brenn\w*|\barde\b|eczema|blister\w*|swollen|\bstye\w*|teary|\bhive\w*|rougeur\w*|irrit\w*|picazón|pica\b|rospo|bouton\w*)',
        'issue_packaging_pump': r'(?:\bempty\b|pump\w*|dispens\w*|broke\w*|peel\w*|\bgreen\b|wasteful|too much|vacío|vuoto|faulty|leaked|spring|popped|\blid\b|\bcap\b|\bseal\b|button|stantuffo|botón|emballage|verpackung|abierta|opened|vazio|مفتوح|مكسر)',
        'issue_no_effect': r'(?:no difference|didn[\'’]t work|does not work|doesn[\'’]t work|no change|no improvement|not effective|ineffective|useless|waste of money|did nothing|does nothing|no results|zero result|nessun miglioramento|pas efficace|no vi cambios|no he visto diferencia|no sirve|no me sirvió|aucun effet|kein\w* effekt|keinerlei)'
    }

    for col, pat in patterns.items():
        df[col] = df['full_text'].str.contains(pat, case=False, regex=True)

    neg_irrit_pat = r'(?:no\s+(?:\w+\s+)?irritat|not\s+irritat|didn[\'’]t\s+(?:cause\s+(?:me\s+)?(?:any\s+)?)?irritat|doesn[\'’]t\s+(?:cause\s+(?:me\s+)?(?:any\s+)?)?irritat|never\s+(?:ever\s+)?irritat|without\s+irritat|no\s+skin\s+irritation|hasn[\'’]t\s+caused\s+any\s+irritation|no\s+allerg|nessun\s+allergia|doesn[\'’]t\s+burn|did\s+not\s+irritat|non\s+irrit)'
    has_negated_irrit = df['full_text'].str.contains(neg_irrit_pat, case=False, regex=True)
    df['issue_skin_irritation'] = df['raw_irritation'] & (~has_negated_irrit) & (df['rating_num'] <= 4.0)
    df.drop(columns=['raw_irritation'], inplace=True)

    clean_cols = [
        'review_id', 'review_date', 'year', 'year_month', 'year_quarter', 'week_start',
        'day_of_week', 'country', 'region_group', 'rating_num', 'sentiment_group',
        'pop_weight', 'filter', 'sort', 'verified_purchase', 'reviewer_name_clean',
        'is_title_missing', 'is_body_missing', 'is_empty_text', 'is_name_anomaly',
        'has_video', 'text_length', 'word_count',
        'topic_cooling_roller', 'topic_hydration', 'topic_depuff',
        'topic_brightening', 'topic_wrinkles',
        'issue_skin_irritation', 'issue_packaging_pump', 'issue_no_effect',
        'title_clean', 'body_clean'
    ]
    df_clean = df[clean_cols].copy()
    df_clean.to_csv(os.path.join(DATA_DIR, 'reviews_cleaned.csv'), index=False, encoding='utf-8-sig')
    print(f"- 정제 완료: data/reviews_cleaned.csv 저장 ({len(df_clean)}행)")

    return df_clean, df_summary, df_star


def build_timeseries_datasets(df):
    print("\n" + "=" * 70)
    print("[2단계] 일별 / 주별 / 월별 시계열 데이터셋 구축")
    print("=" * 70)

    daily_active = df.groupby('review_date').agg(
        review_count=('review_id', 'count'),
        mean_rating=('rating_num', 'mean'),
        weighted_rating=('rating_num', lambda s: np.average(s, weights=df.loc[s.index, 'pop_weight'])),
        pos_count=('rating_num', lambda s: (s >= 4.0).sum()),
        neu_count=('rating_num', lambda s: (s == 3.0).sum()),
        neg_count=('rating_num', lambda s: (s <= 2.0).sum()),
        us_count=('country', lambda s: (s == 'United States').sum()),
        global_count=('country', lambda s: (s != 'United States').sum()),
        cooling_cnt=('topic_cooling_roller', 'sum'),
        hydration_cnt=('topic_hydration', 'sum'),
        irritation_cnt=('issue_skin_irritation', 'sum'),
        packaging_cnt=('issue_packaging_pump', 'sum'),
        no_effect_cnt=('issue_no_effect', 'sum')
    ).reset_index()

    full_dates = pd.date_range(df['review_date'].min(), df['review_date'].max(), freq='D')
    daily_full = pd.DataFrame({'review_date': full_dates}).merge(daily_active, on='review_date', how='left')
    count_cols = ['review_count', 'pos_count', 'neu_count', 'neg_count', 'us_count', 'global_count',
                  'cooling_cnt', 'hydration_cnt', 'irritation_cnt', 'packaging_cnt', 'no_effect_cnt']
    daily_full[count_cols] = daily_full[count_cols].fillna(0).astype(int)
    daily_full['cum_reviews'] = daily_full['review_count'].cumsum()
    daily_full['ma7_count'] = daily_full['review_count'].rolling(7, min_periods=1).mean().round(3)
    daily_full['ma30_count'] = daily_full['review_count'].rolling(30, min_periods=1).mean().round(3)
    daily_full['ma30_rating'] = daily_full['mean_rating'].rolling(30, min_periods=3).mean().round(3)

    daily_active['cum_reviews'] = daily_active['review_count'].cumsum()
    daily_active['ma7_active_count'] = daily_active['review_count'].rolling(7, min_periods=1).mean().round(3)
    daily_active['ma14_active_count'] = daily_active['review_count'].rolling(14, min_periods=1).mean().round(3)
    daily_active['ma14_active_rating'] = daily_active['mean_rating'].rolling(14, min_periods=3).mean().round(3)
    daily_active['mean_rating'] = daily_active['mean_rating'].round(3)
    daily_active['weighted_rating'] = daily_active['weighted_rating'].round(3)

    daily_active.to_csv(os.path.join(DATA_DIR, 'timeseries_daily.csv'), index=False, encoding='utf-8-sig')
    print(f"- 일별 시계열 저장: data/timeseries_daily.csv (활성 일수: {len(daily_active)}일, 전체 캘린더: {len(daily_full)}일)")

    df['week_start_dt'] = pd.to_datetime(df['week_start'])
    weekly_raw = df.groupby('week_start_dt').agg(
        review_count=('review_id', 'count'),
        mean_rating=('rating_num', 'mean'),
        weighted_rating=('rating_num', lambda s: np.average(s, weights=df.loc[s.index, 'pop_weight'])),
        pos_count=('rating_num', lambda s: (s >= 4.0).sum()),
        neg_count=('rating_num', lambda s: (s <= 2.0).sum()),
        us_count=('country', lambda s: (s == 'United States').sum()),
        global_count=('country', lambda s: (s != 'United States').sum()),
        irritation_cnt=('issue_skin_irritation', 'sum'),
        packaging_cnt=('issue_packaging_pump', 'sum')
    ).reset_index()

    full_weeks = pd.date_range(weekly_raw['week_start_dt'].min(), weekly_raw['week_start_dt'].max(), freq='W-MON')
    weekly_df = pd.DataFrame({'week_start_dt': full_weeks}).merge(weekly_raw, on='week_start_dt', how='left')
    w_count_cols = ['review_count', 'pos_count', 'neg_count', 'us_count', 'global_count', 'irritation_cnt', 'packaging_cnt']
    weekly_df[w_count_cols] = weekly_df[w_count_cols].fillna(0).astype(int)
    weekly_df['week_start'] = weekly_df['week_start_dt'].dt.strftime('%Y-%m-%d')
    weekly_df['ma4_count'] = weekly_df['review_count'].rolling(4, min_periods=1).mean().round(3)
    weekly_df['ma8_count'] = weekly_df['review_count'].rolling(8, min_periods=1).mean().round(3)
    weekly_df['ma4_rating'] = weekly_df['mean_rating'].rolling(4, min_periods=1).mean().round(3)
    weekly_df['mean_rating'] = weekly_df['mean_rating'].round(3)
    weekly_df['weighted_rating'] = weekly_df['weighted_rating'].round(3)

    weekly_df.drop(columns=['week_start_dt']).to_csv(os.path.join(DATA_DIR, 'timeseries_weekly.csv'), index=False, encoding='utf-8-sig')
    print(f"- 주별 시계열 저장: data/timeseries_weekly.csv (총 {len(weekly_df)}주, 활성 주수: {len(weekly_raw)}주)")

    monthly_df = df.groupby('year_month').agg(
        review_count=('review_id', 'count'),
        mean_rating=('rating_num', 'mean'),
        std_rating=('rating_num', 'std'),
        weighted_rating=('rating_num', lambda s: np.average(s, weights=df.loc[s.index, 'pop_weight'])),
        star_5=('rating_num', lambda s: (s == 5.0).sum()),
        star_4=('rating_num', lambda s: (s == 4.0).sum()),
        star_3=('rating_num', lambda s: (s == 3.0).sum()),
        star_2=('rating_num', lambda s: (s == 2.0).sum()),
        star_1=('rating_num', lambda s: (s == 1.0).sum()),
        pos_count=('rating_num', lambda s: (s >= 4.0).sum()),
        neu_count=('rating_num', lambda s: (s == 3.0).sum()),
        neg_count=('rating_num', lambda s: (s <= 2.0).sum()),
        us_count=('country', lambda s: (s == 'United States').sum()),
        global_count=('country', lambda s: (s != 'United States').sum()),
        cooling_cnt=('topic_cooling_roller', 'sum'),
        hydration_cnt=('topic_hydration', 'sum'),
        depuff_cnt=('topic_depuff', 'sum'),
        brightening_cnt=('topic_brightening', 'sum'),
        wrinkles_cnt=('topic_wrinkles', 'sum'),
        irritation_cnt=('issue_skin_irritation', 'sum'),
        packaging_cnt=('issue_packaging_pump', 'sum'),
        no_effect_cnt=('issue_no_effect', 'sum')
    ).reset_index()

    monthly_df['std_rating'] = monthly_df['std_rating'].fillna(0.0)
    monthly_df['pos_ratio'] = (monthly_df['pos_count'] / monthly_df['review_count'] * 100).round(1)
    monthly_df['neg_ratio'] = (monthly_df['neg_count'] / monthly_df['review_count'] * 100).round(1)
    monthly_df['global_share'] = (monthly_df['global_count'] / monthly_df['review_count'] * 100).round(1)
    monthly_df['mom_growth_pct'] = (monthly_df['review_count'].pct_change() * 100).round(1)
    monthly_df['ma3_count'] = monthly_df['review_count'].rolling(3, min_periods=1).mean().round(2)
    monthly_df['ma3_rating'] = monthly_df['mean_rating'].rolling(3, min_periods=1).mean().round(3)
    monthly_df['ma3_weighted_rating'] = monthly_df['weighted_rating'].rolling(3, min_periods=1).mean().round(3)
    monthly_df['mean_rating'] = monthly_df['mean_rating'].round(3)
    monthly_df['weighted_rating'] = monthly_df['weighted_rating'].round(3)
    monthly_df['std_rating'] = monthly_df['std_rating'].round(3)

    monthly_df.to_csv(os.path.join(DATA_DIR, 'timeseries_monthly.csv'), index=False, encoding='utf-8-sig')
    print(f"- 월별 시계열 저장: data/timeseries_monthly.csv (총 {len(monthly_df)}개월)")

    return daily_active, daily_full, weekly_df, monthly_df


def generate_visualizations(df, daily_active, daily_full, weekly_df, monthly_df, df_star):
    print("\n" + "=" * 70)
    print("[3단계] 시각화 차트 6종 생성 시작")
    print("=" * 70)

    m_sub = monthly_df[monthly_df['year_month'] >= '2025-01'].copy().reset_index(drop=True)
    x_idx = np.arange(len(m_sub))
    x_labels = m_sub['year_month'].tolist()

    # -------------------------------------------------------------------------
    # [차트 1] 월별/일별 리뷰 유입량 추이 및 이동평균(MA) · 성장 국면 분석
    # -------------------------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [1.15, 1]})
    fig.patch.set_facecolor('white')

    ax1.axvspan(-0.5, 5.5, color='#E8F4F8', alpha=0.55, label='Phase 1: 초기 도입기 (2025.01~06, 월평균 7.5건)')
    ax1.axvspan(5.5, 13.5, color='#FFF8E7', alpha=0.65, label='Phase 2: 바이럴·글로벌 확장기 (2025.07~2026.02, 월평균 22.0건)')
    ax1.axvspan(13.5, len(m_sub) - 0.5, color='#EEF8F0', alpha=0.65, label='Phase 3: 피크 및 성숙 안착기 (2026.03~10, 월평균 31.4건)')

    ax1.bar(x_idx, m_sub['review_count'], color='#3B82F6', alpha=0.82, width=0.6, label='월별 리뷰 수 (건)', zorder=3)
    ax1.plot(x_idx, m_sub['ma3_count'], color='#DC2626', marker='o', linewidth=2.6, markersize=6, label='3개월 이동평균 (3M MA)', zorder=4)

    for i, row in m_sub.iterrows():
        cnt = row['review_count']
        ax1.text(
            i, cnt + 1.0, f"{cnt}건", ha='center', va='bottom', fontsize=8.5,
            fontweight='bold', color='#1E293B', zorder=5,
            bbox=dict(boxstyle='round,pad=0.12', facecolor='white', edgecolor='none', alpha=0.8)
        )

    idx_nov25 = x_labels.index('2025-11')
    idx_mar26 = x_labels.index('2026-03')
    idx_may26 = x_labels.index('2026-05')
    ax1.annotate('블랙프라이데이·글로벌 급증\n30건 (MoM +100.0%)',
                 xy=(idx_nov25, 30), xytext=(idx_nov25 - 2.3, 39),
                 arrowprops=dict(arrowstyle='->', color='#B45309', lw=1.5),
                 fontsize=9, fontweight='bold', color='#B45309', zorder=6,
                 bbox=dict(boxstyle='round,pad=0.3', facecolor='#FEF3C7', edgecolor='#F59E0B'))
    ax1.annotate('역대 최고 유입 피크\n43건 (MoM +48.3%)',
                 xy=(idx_mar26, 43), xytext=(idx_mar26 - 2.9, 47.5),
                 arrowprops=dict(arrowstyle='->', color='#DC2626', lw=1.5),
                 fontsize=9, fontweight='bold', color='#DC2626', zorder=6,
                 bbox=dict(boxstyle='round,pad=0.3', facecolor='#FEE2E2', edgecolor='#EF4444'))
    ax1.annotate('3M MA 최고점 (38.3건)\n5월 39건 유입',
                 xy=(idx_may26, 39), xytext=(idx_may26 + 0.7, 45.5),
                 arrowprops=dict(arrowstyle='->', color='#047857', lw=1.5),
                 fontsize=9, fontweight='bold', color='#047857', zorder=6,
                 bbox=dict(boxstyle='round,pad=0.3', facecolor='#D1FAE5', edgecolor='#10B981'))

    ax1.set_title('① 월별 리뷰 유입량 추이, 3개월 이동평균(3M MA) 및 3단계 성장 국면 (2025.01 ~ 2026.10)', fontsize=13, fontweight='bold', pad=12)
    ax1.set_xticks(x_idx)
    ax1.set_xticklabels(x_labels, rotation=35, fontsize=9)
    ax1.set_ylabel('월별 리뷰 수 (건)', fontsize=10, fontweight='bold')
    ax1.set_ylim(0, 56)
    ax1.grid(axis='y', linestyle='--', alpha=0.4, zorder=0)
    ax1.legend(loc='upper left', fontsize=8.5, ncol=2, framealpha=0.92)

    d_sub = daily_full[daily_full['review_date'] >= '2025-01-01'].copy()
    ax2.bar(d_sub['review_date'], d_sub['review_count'], color='#94A3B8', alpha=0.45, width=1.0, label='일별 리뷰 발생 수 (최대 5건/일)')
    ax2.plot(d_sub['review_date'], d_sub['ma7_count'], color='#2563EB', linewidth=1.5, alpha=0.85, label='7일 이동평균 (7D MA)')
    ax2.plot(d_sub['review_date'], d_sub['ma30_count'], color='#DC2626', linewidth=2.4, label='30일 이동평균 (30D MA)')

    ax2_twin = ax2.twinx()
    ax2_twin.plot(d_sub['review_date'], d_sub['cum_reviews'], color='#059669', linestyle='--', linewidth=2.0, label='누적 리뷰 수 (우측 축, 총 478건)')
    ax2_twin.set_ylabel('누적 리뷰 수 (건)', fontsize=10, fontweight='bold', color='#059669')
    ax2_twin.tick_params(axis='y', labelcolor='#059669')
    ax2_twin.set_ylim(0, 530)

    ax2.set_title('② 일별 리뷰 시계열 흐름 (324개 활성 데이터 포인트), 7일·30일 이동평균 및 누적 성장 곡선', fontsize=13, fontweight='bold', pad=12)
    ax2.set_xlabel('날짜 (Date)', fontsize=10, fontweight='bold')
    ax2.set_ylabel('일별 리뷰 수 / 이동평균 (건)', fontsize=10, fontweight='bold')
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax2.grid(True, linestyle='--', alpha=0.4)

    lines1, labels1 = ax2.get_legend_handles_labels()
    lines2, labels2 = ax2_twin.get_legend_handles_labels()
    ax2.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=9, framealpha=0.92)

    plt.tight_layout()
    path1 = os.path.join(IMG_DIR, '01_review_volume_and_ma_trend.png')
    plt.savefig(path1, bbox_inches='tight')
    plt.close()
    print(f"- 차트 1 저장 완료: {path1}")

    # -------------------------------------------------------------------------
    # [차트 2] 평점 시계열 추이, 변동성 밴드 및 표본 추출 편향 보정 비교
    # -------------------------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6.2), gridspec_kw={'width_ratios': [1.65, 1]})
    fig.patch.set_facecolor('white')

    ax1.fill_between(
        x_idx,
        np.clip(m_sub['mean_rating'] - 0.5 * m_sub['std_rating'], 1.0, 5.0),
        np.clip(m_sub['mean_rating'] + 0.5 * m_sub['std_rating'], 1.0, 5.0),
        color='#93C5FD', alpha=0.3, label='표본 평점 변동성 구간 (±0.5σ)'
    )
    ax1.plot(x_idx, m_sub['mean_rating'], color='#64748B', linestyle=':', marker='s', markersize=5, linewidth=1.5, label='월별 표본 단순평균 평점 (Raw Mean)')
    ax1.plot(x_idx, m_sub['ma3_rating'], color='#2563EB', marker='o', markersize=6, linewidth=2.5, label='표본 평점 3개월 이동평균 (Raw 3M MA)')
    ax1.plot(x_idx, m_sub['weighted_rating'], color='#F59E0B', linestyle='--', marker='^', markersize=5, linewidth=1.6, alpha=0.85, label='모집단 가중 보정 평점 (Pop-Weighted)')
    ax1.plot(x_idx, m_sub['ma3_weighted_rating'], color='#D97706', marker='D', markersize=6, linewidth=2.6, label='가중 보정 평점 3개월 이동평균 (Weighted 3M MA)')

    ax1.axhline(4.44, color='#059669', linestyle='-.', linewidth=1.5, label='아마존 전체 모집단 평균 (4.44★, N=4,325)')
    ax1.axhline(3.19, color='#DC2626', linestyle='-.', linewidth=1.5, label='수집 표본 전체 단순평균 (3.19★, N=478)')

    idx_jun25 = x_labels.index('2025-06')
    ax1.annotate('초기 저평점 집중 구간\n(2025-06: 표본 1.71★ / 보정 2.58★)',
                 xy=(idx_jun25, 1.71), xytext=(idx_jun25 - 2.5, 1.15),
                 arrowprops=dict(arrowstyle='->', color='#DC2626', lw=1.4),
                 fontsize=8.5, fontweight='bold', color='#DC2626',
                 bbox=dict(boxstyle='round,pad=0.3', facecolor='#FEE2E2', edgecolor='#EF4444'))

    ax1.annotate('5점 리뷰 대량 유입 및 평점 반등\n(2026-03: 표본 3.74★ / 보정 4.69★)',
                 xy=(idx_mar26, 3.74), xytext=(idx_mar26 - 4.5, 4.05),
                 arrowprops=dict(arrowstyle='->', color='#2563EB', lw=1.4),
                 fontsize=8.5, fontweight='bold', color='#1D4ED8',
                 bbox=dict(boxstyle='round,pad=0.3', facecolor='#DBEAFE', edgecolor='#3B82F6'))

    ax1.set_title('① 월별 평점 추이: 수집 표본 단순평균 vs 모집단 가중 보정 평점 (2025.01~2026.10)', fontsize=12, fontweight='bold', pad=10)
    ax1.set_xticks(x_idx)
    ax1.set_xticklabels(x_labels, rotation=40, fontsize=8.5)
    ax1.set_ylabel('평점 (1.0 ★ ~ 5.0 ★)', fontsize=10, fontweight='bold')
    ax1.set_ylim(0.8, 5.3)
    ax1.grid(True, linestyle='--', alpha=0.4)
    ax1.legend(loc='lower right', fontsize=8, framealpha=0.92)

    stars = [5, 4, 3, 2, 1]
    pop_pcts = [72.0, 12.0, 8.0, 4.0, 4.0]
    sample_pcts = [round((df['rating_num'] == s).mean() * 100, 1) for s in stars]

    y_pos = np.arange(len(stars))
    bar_h = 0.36
    ax2.barh(y_pos - bar_h/2, pop_pcts, height=bar_h, color='#10B981', alpha=0.88, label='아마존 전체 모집단 (N=4,325, 평균 4.44★)')
    ax2.barh(y_pos + bar_h/2, sample_pcts, height=bar_h, color='#3B82F6', alpha=0.88, label='수집 리뷰 표본 (N=478, 단순평균 3.19★)')

    for i, (p_val, s_val) in enumerate(zip(pop_pcts, sample_pcts)):
        ax2.text(p_val + 1.0, y_pos[i] - bar_h/2, f"{p_val:.1f}%", va='center', fontsize=8.5, fontweight='bold', color='#047857')
        ax2.text(s_val + 1.0, y_pos[i] + bar_h/2, f"{s_val:.1f}%", va='center', fontsize=8.5, fontweight='bold', color='#1D4ED8')

    ax2.set_yticks(y_pos)
    ax2.set_yticklabels([f"{s}점 (★)" for s in stars], fontsize=10, fontweight='bold')
    ax2.invert_yaxis()
    ax2.set_xlabel('비중 (%)', fontsize=10, fontweight='bold')
    ax2.set_xlim(0, 85)
    ax2.set_title('② 모집단 vs 수집 표본 별점 분포 (층화 표집 구조)', fontsize=12, fontweight='bold', pad=10)
    ax2.grid(axis='x', linestyle='--', alpha=0.4)
    ax2.legend(loc='lower right', fontsize=8.5, framealpha=0.92)

    plt.tight_layout()
    path2 = os.path.join(IMG_DIR, '02_rating_trend_and_sampling_bias.png')
    plt.savefig(path2, bbox_inches='tight')
    plt.close()
    print(f"- 차트 2 저장 완료: {path2}")

    # -------------------------------------------------------------------------
    # [차트 3] 글로벌 시장(미국 vs 비미국 18개국) 확산 추이 및 국가별 비교
    # -------------------------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6.0), gridspec_kw={'width_ratios': [1.4, 1.05]})
    fig.patch.set_facecolor('white')

    ax1.bar(x_idx, m_sub['us_count'], color='#2563EB', alpha=0.85, width=0.6, label='미국 (US, 총 326건 / 68.2%)')
    ax1.bar(x_idx, m_sub['global_count'], bottom=m_sub['us_count'], color='#F59E0B', alpha=0.88, width=0.6, label='글로벌 비미국 18개국 (Global, 총 152건 / 31.8%)')

    ax1_twin = ax1.twinx()
    ax1_twin.plot(x_idx, m_sub['global_share'], color='#B45309', marker='o', linewidth=2.2, markersize=5, linestyle='--', label='글로벌(비미국) 리뷰 비중 (%)')
    ax1_twin.set_ylabel('글로벌 리뷰 비중 (%)', fontsize=10, fontweight='bold', color='#B45309')
    ax1_twin.set_ylim(0, 80)
    ax1_twin.tick_params(axis='y', labelcolor='#B45309')

    ax1.annotate('글로벌 비중 최고점\n2025-11: 56.7% (17/30건)',
                 xy=(idx_nov25, 30), xytext=(idx_nov25 - 3.6, 36),
                 arrowprops=dict(arrowstyle='->', color='#B45309', lw=1.4),
                 fontsize=8.5, fontweight='bold', color='#B45309',
                 bbox=dict(boxstyle='round,pad=0.3', facecolor='#FEF3C7', edgecolor='#F59E0B'))

    ax1.set_title('① 월별 미국(US) vs 글로벌(18개국) 리뷰 유입 추이 및 글로벌 확장 비중', fontsize=12, fontweight='bold', pad=10)
    ax1.set_xticks(x_idx)
    ax1.set_xticklabels(x_labels, rotation=40, fontsize=8.5)
    ax1.set_ylabel('월별 리뷰 수 (건)', fontsize=10, fontweight='bold')
    ax1.set_ylim(0, 48)
    ax1.grid(axis='y', linestyle='--', alpha=0.4)

    l1, lb1 = ax1.get_legend_handles_labels()
    l2, lb2 = ax1_twin.get_legend_handles_labels()
    ax1.legend(l1 + l2, lb1 + lb2, loc='upper left', fontsize=8.5, framealpha=0.92)

    top_countries = (
        df.groupby('country')
        .agg(cnt=('review_id', 'count'), avg_rating=('rating_num', 'mean'))
        .sort_values('cnt', ascending=False)
        .head(10)
    )
    c_names = top_countries.index.tolist()
    c_cnts = top_countries['cnt'].tolist()
    c_ratings = top_countries['avg_rating'].tolist()
    y_c = np.arange(len(c_names))

    colors_c = ['#2563EB' if c == 'United States' else '#F59E0B' for c in c_names]
    ax2.barh(y_c, c_cnts, color=colors_c, alpha=0.85, height=0.6)
    for i, (cnt, rt) in enumerate(zip(c_cnts, c_ratings)):
        ax2.text(cnt + 5, y_c[i], f"{cnt}건 (평균 {rt:.2f}★)", va='center', fontsize=8.5, fontweight='bold', color='#1E293B')

    ax2.set_yticks(y_c)
    ax2.set_yticklabels(c_names, fontsize=9.5, fontweight='bold')
    ax2.invert_yaxis()
    ax2.set_xlim(0, 460)
    ax2.set_xlabel('리뷰 수 (건) 및 국가별 표본 평균 평점', fontsize=10, fontweight='bold')
    ax2.set_title('② 상위 10개국 리뷰 분포 및 국가별 평균 평점 비교', fontsize=12, fontweight='bold', pad=10)
    ax2.grid(axis='x', linestyle='--', alpha=0.4)

    plt.tight_layout()
    path3 = os.path.join(IMG_DIR, '03_global_market_and_seasonality.png')
    plt.savefig(path3, bbox_inches='tight')
    plt.close()
    print(f"- 차트 3 저장 완료: {path3}")

    # -------------------------------------------------------------------------
    # [차트 4] 핵심 긍정 요인 vs 3대 불만 요인 별점별·시계열 분석
    # -------------------------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6.2), gridspec_kw={'width_ratios': [1.1, 1.35]})
    fig.patch.set_facecolor('white')

    rating_groups = [1.0, 2.0, 3.0, 4.0, 5.0]
    topic_rates = df.groupby('rating_num')[
        ['topic_cooling_roller', 'topic_hydration', 'topic_brightening',
         'issue_skin_irritation', 'issue_packaging_pump', 'issue_no_effect']
    ].mean() * 100

    x_r = np.arange(len(rating_groups))
    w_bar = 0.13
    topic_meta = [
        ('topic_cooling_roller', '쿨링 롤러·어플리케이터', '#0EA5E9'),
        ('topic_hydration', '수분·보습감', '#10B981'),
        ('topic_brightening', '다크서클·브라이트닝', '#8B5CF6'),
        ('issue_skin_irritation', '[불만] 피부 자극·화끈거림·알러지', '#EF4444'),
        ('issue_packaging_pump', '[불만] 용기·펌프 불량·빈 통', '#F97316'),
        ('issue_no_effect', '[불만] 효과 미흡·변화 없음', '#64748B'),
    ]

    for idx_m, (col_name, label_kr, color_hex) in enumerate(topic_meta):
        offset = (idx_m - 2.5) * w_bar
        vals = topic_rates[col_name].values
        ax1.bar(x_r + offset, vals, width=w_bar, color=color_hex, alpha=0.88, label=label_kr)

    ax1.set_xticks(x_r)
    ax1.set_xticklabels([f"{int(r)}점 (★)\n(N={int((df['rating_num']==r).sum())})" for r in rating_groups], fontsize=9.5, fontweight='bold')
    ax1.set_ylabel('리뷰 내 키워드 언급 비율 (%)', fontsize=10, fontweight='bold')
    ax1.set_ylim(0, 44)
    ax1.set_title('① 별점 구간별 핵심 긍정 포인트 vs 3대 불만 요인 언급률(%)', fontsize=12, fontweight='bold', pad=10)
    ax1.grid(axis='y', linestyle='--', alpha=0.4)
    ax1.legend(loc='upper right', fontsize=8, framealpha=0.92)

    tot_irrit = int(df['issue_skin_irritation'].sum())
    tot_pkg = int(df['issue_packaging_pump'].sum())
    tot_noeff = int(df['issue_no_effect'].sum())

    ax2.plot(x_idx, m_sub['irritation_cnt'], color='#EF4444', marker='o', linewidth=2.4, markersize=6, label=f'피부 자극·화끈거림·알러지 (총 {tot_irrit}건)')
    ax2.plot(x_idx, m_sub['packaging_cnt'], color='#F97316', marker='s', linewidth=2.2, markersize=5.5, label=f'용기·펌프 토출 불량·코팅 벗겨짐 (총 {tot_pkg}건)')
    ax2.plot(x_idx, m_sub['no_effect_cnt'], color='#64748B', marker='^', linewidth=2.0, markersize=5.5, linestyle='--', label=f'효과 미흡·변화 없음 (총 {tot_noeff}건)')

    peak_irrit_mar = int(m_sub.loc[idx_mar26, 'irritation_cnt'])
    ax2.axvspan(idx_mar26 - 0.4, idx_may26 + 0.4, color='#FEE2E2', alpha=0.55, label='피부 자극·용기 불량 집중 구간 (2026.03~05)')
    ax2.annotate(f'2026-03 피부 자극(8건)·용기 불량(4건) 동시 급증\n"전월 대비 자극 클레임 4배 급증 (2건→8건)"',
                 xy=(idx_mar26, peak_irrit_mar),
                 xytext=(idx_mar26 - 6.2, 9.6),
                 arrowprops=dict(arrowstyle='->', color='#DC2626', lw=1.5),
                 fontsize=8.5, fontweight='bold', color='#DC2626',
                 bbox=dict(boxstyle='round,pad=0.3', facecolor='#FEF2F2', edgecolor='#EF4444'))

    ax2.set_title('② 월별 3대 핵심 불만 요인(피부 자극·용기 불량·효과 미흡) 발생 추이', fontsize=12, fontweight='bold', pad=10)
    ax2.set_xticks(x_idx)
    ax2.set_xticklabels(x_labels, rotation=40, fontsize=8.5)
    ax2.set_ylabel('월별 이슈 언급 리뷰 수 (건)', fontsize=10, fontweight='bold')
    ax2.set_ylim(0, 12.5)
    ax2.grid(True, linestyle='--', alpha=0.4)
    ax2.legend(loc='upper left', fontsize=8.5, framealpha=0.92)

    plt.tight_layout()
    path4 = os.path.join(IMG_DIR, '04_pain_points_and_topic_trends.png')
    plt.savefig(path4, bbox_inches='tight')
    plt.close()
    print(f"- 차트 4 저장 완료: {path4}")

    # -------------------------------------------------------------------------
    # [차트 5] 보너스 과제 (A): 시계열 분해 (Time-Series Decomposition)
    # -------------------------------------------------------------------------
    y_obs = m_sub['review_count'].values.astype(float)
    s_obs = pd.Series(y_obs)
    trend = s_obs.rolling(window=3, center=True, min_periods=1).mean().values
    detrended = y_obs - trend
    period = 3
    seasonal_pattern = np.zeros(period)
    for p in range(period):
        seasonal_pattern[p] = np.mean(detrended[p::period])
    seasonal_pattern -= np.mean(seasonal_pattern)
    seasonal = np.array([seasonal_pattern[i % period] for i in range(len(y_obs))])
    residual = y_obs - trend - seasonal
    resid_std = np.std(residual)

    fig, axes = plt.subplots(4, 1, figsize=(13, 9.5), sharex=True)
    fig.patch.set_facecolor('white')

    axes[0].plot(x_idx, y_obs, color='#1E293B', marker='o', linewidth=2.2, label='관측값 (Observed)')
    axes[0].set_ylabel('관측값 (건)', fontsize=9.5, fontweight='bold')
    axes[0].set_title('보너스 과제 (A): 월별 리뷰 유입량 시계열 분해 (Observed = Trend + Periodic + Residual)', fontsize=13, fontweight='bold', pad=12)
    axes[0].legend(loc='upper left', fontsize=9)
    axes[0].grid(True, linestyle='--', alpha=0.4)

    axes[1].plot(x_idx, trend, color='#2563EB', marker='s', linewidth=2.4, label='추세 성분 (Trend: 중심 이동평균 기반 장기 성장 흐름)')
    axes[1].set_ylabel('추세 (Trend)', fontsize=9.5, fontweight='bold')
    axes[1].legend(loc='upper left', fontsize=9)
    axes[1].grid(True, linestyle='--', alpha=0.4)

    axes[2].plot(x_idx, seasonal, color='#059669', marker='^', linewidth=2.0, linestyle='--', label='주기/계절성 성분 (Periodic/Seasonal: 분기별 캠페인 파동)')
    axes[2].axhline(0, color='#64748B', linestyle=':', linewidth=1)
    axes[2].set_ylabel('주기성 (Seasonal)', fontsize=9.5, fontweight='bold')
    axes[2].legend(loc='upper left', fontsize=9)
    axes[2].grid(True, linestyle='--', alpha=0.4)

    bar_colors = ['#DC2626' if abs(r) > 1.5 * resid_std else '#64748B' for r in residual]
    axes[3].bar(x_idx, residual, color=bar_colors, alpha=0.8, width=0.5, label='잔차/노이즈 (Residual, 빨간색 = ±1.5σ 이상 징후 스파이크)')
    axes[3].axhline(1.5 * resid_std, color='#DC2626', linestyle='--', linewidth=1.2, label=f'+1.5σ 임계선 (+{1.5*resid_std:.1f}건)')
    axes[3].axhline(-1.5 * resid_std, color='#DC2626', linestyle='--', linewidth=1.2, label=f'-1.5σ 임계선 (-{1.5*resid_std:.1f}건)')
    axes[3].axhline(0, color='#1E293B', linewidth=1)
    axes[3].set_ylabel('잔차 (Residual)', fontsize=9.5, fontweight='bold')
    axes[3].set_xticks(x_idx)
    axes[3].set_xticklabels(x_labels, rotation=35, fontsize=9)
    axes[3].legend(loc='upper left', fontsize=8.5, ncol=3)
    axes[3].grid(True, linestyle='--', alpha=0.4)

    plt.tight_layout()
    path5 = os.path.join(IMG_DIR, '05_timeseries_decomposition.png')
    plt.savefig(path5, bbox_inches='tight')
    plt.close()
    print(f"- 차트 5 저장 완료: {path5}")

    # -------------------------------------------------------------------------
    # [차트 6] 보너스 과제 (B): 시계열 베이스라인 예측 (Baseline Forecast)
    # -------------------------------------------------------------------------
    n_total = len(y_obs)
    n_train = n_total - 3
    y_train = y_obs[:n_train]
    y_val = y_obs[n_train:]

    pred_val_naive = np.repeat(y_train[-1], 3)
    pred_val_ma3 = np.repeat(np.mean(y_train[-3:]), 3)

    def holt_damped(series, steps, alpha=0.45, beta=0.25, phi=0.85):
        level = series[0]
        trend_h = series[1] - series[0]
        fitted = [level]
        for val in series[1:]:
            prev_level = level
            level = alpha * val + (1 - alpha) * (prev_level + phi * trend_h)
            trend_h = beta * (level - prev_level) + (1 - beta) * phi * trend_h
            fitted.append(level)
        forecasts = []
        phi_sum = 0.0
        for h in range(1, steps + 1):
            phi_sum += phi ** h
            forecasts.append(level + phi_sum * trend_h)
        return np.array(fitted), np.array(forecasts)

    _, pred_val_holt = holt_damped(y_train, 3)

    mae_naive = np.mean(np.abs(y_val - pred_val_naive))
    mae_ma3 = np.mean(np.abs(y_val - pred_val_ma3))
    mae_holt = np.mean(np.abs(y_val - pred_val_holt))

    rmse_naive = np.sqrt(np.mean((y_val - pred_val_naive) ** 2))
    rmse_ma3 = np.sqrt(np.mean((y_val - pred_val_ma3) ** 2))
    rmse_holt = np.sqrt(np.mean((y_val - pred_val_holt) ** 2))

    fitted_full, future_holt = holt_damped(y_obs, 3)
    future_ma3 = np.repeat(np.mean(y_obs[-3:]), 3)
    future_labels = ['2026-11(예측)', '2026-12(예측)', '2027-01(예측)']
    all_labels = x_labels + future_labels
    all_idx = np.arange(len(all_labels))
    future_idx = np.arange(n_total, n_total + 3)

    fit_resid_std = np.std(y_obs - fitted_full)
    ci_95 = 1.96 * fit_resid_std * np.sqrt(np.arange(1, 4) * 0.6)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 5.8), gridspec_kw={'width_ratios': [1.65, 1]})
    fig.patch.set_facecolor('white')

    ax1.axvspan(n_train - 0.5, n_total - 0.5, color='#FEF3C7', alpha=0.5, label='검증 구간 (Validation: 2026.08~10)')
    ax1.axvspan(n_total - 0.5, n_total + 2.5, color='#DBEAFE', alpha=0.45, label='향후 3개월 예측 구간 (Forecast: 2026.11~2027.01)')

    ax1.plot(x_idx, y_obs, color='#1E293B', marker='o', linewidth=2.4, markersize=6, label='실제 월별 리뷰 수 (Actual)')
    ax1.plot(x_idx, fitted_full, color='#2563EB', linestyle='--', linewidth=1.6, alpha=0.75, label='지수가중 추세 적합선 (Fitted)')

    conn_idx = np.concatenate([[n_total - 1], future_idx])
    ax1.plot(conn_idx, np.concatenate([[y_obs[-1]], future_holt]), color='#DC2626', marker='D', linewidth=2.5, markersize=6.5, label=f'감쇠 지수평활 예측 (2026.11~2027.01 평균 {np.mean(future_holt):.1f}건)')
    ax1.plot(conn_idx, np.concatenate([[y_obs[-1]], future_ma3]), color='#059669', marker='s', linestyle='--', linewidth=2.0, markersize=5.5, label=f'3M 이동평균 베이스라인 ({future_ma3[0]:.1f}건)')
    ax1.fill_between(future_idx, np.clip(future_holt - ci_95, 5, None), future_holt + ci_95, color='#FCA5A5', alpha=0.35, label='95% 예측 신뢰구간 (Prediction Interval)')

    for idx_f, val_f in zip(future_idx, future_holt):
        ax1.text(idx_f, val_f - 3.8, f"{val_f:.1f}건", ha='center', va='top', fontsize=8.5, fontweight='bold', color='#DC2626')

    ax1.set_title('① 보너스 과제 (B): 월별 리뷰 유입량 베이스라인 예측 (2026.11 ~ 2027.01)', fontsize=12, fontweight='bold', pad=10)
    ax1.set_xticks(all_idx)
    ax1.set_xticklabels(all_labels, rotation=40, fontsize=8.5)
    ax1.set_ylabel('월별 리뷰 수 (건)', fontsize=10, fontweight='bold')
    ax1.set_ylim(0, 52)
    ax1.grid(True, linestyle='--', alpha=0.4)
    ax1.legend(loc='upper left', fontsize=8, framealpha=0.92)

    models = ['Naive\n(직전값 유지)', '3M 이동평균\n(3M MA)', '감쇠 지수평활\n(Damped Holt)']
    maes = [mae_naive, mae_ma3, mae_holt]
    rmses = [rmse_naive, rmse_ma3, rmse_holt]
    xm = np.arange(len(models))
    bw = 0.34

    ax2.bar(xm - bw/2, maes, width=bw, color='#3B82F6', alpha=0.88, label='MAE (평균절대오차, 낮을수록 우수)')
    ax2.bar(xm + bw/2, rmses, width=bw, color='#F59E0B', alpha=0.88, label='RMSE (평균제곱근오차, 낮을수록 우수)')

    for i, (m_v, r_v) in enumerate(zip(maes, rmses)):
        ax2.text(xm[i] - bw/2, m_v + 0.3, f"{m_v:.2f}", ha='center', va='bottom', fontsize=9, fontweight='bold', color='#1D4ED8')
        ax2.text(xm[i] + bw/2, r_v + 0.3, f"{r_v:.2f}", ha='center', va='bottom', fontsize=9, fontweight='bold', color='#B45309')

    ax2.set_xticks(xm)
    ax2.set_xticklabels(models, fontsize=9.5, fontweight='bold')
    ax2.set_ylabel('예측 오차 (건/월)', fontsize=10, fontweight='bold')
    ax2.set_ylim(0, 18.5)
    ax2.set_title('② 검증 구간(2026.08~10) 베이스라인 모델 정확도 비교', fontsize=12, fontweight='bold', pad=10)
    ax2.grid(axis='y', linestyle='--', alpha=0.4)
    ax2.legend(loc='upper left', fontsize=8.5, framealpha=0.92)

    plt.tight_layout()
    path6 = os.path.join(IMG_DIR, '06_timeseries_forecast.png')
    plt.savefig(path6, bbox_inches='tight')
    plt.close()
    print(f"- 차트 6 저장 완료: {path6}")

    return {
        'mae_naive': round(float(mae_naive), 2),
        'mae_ma3': round(float(mae_ma3), 2),
        'mae_holt': round(float(mae_holt), 2),
        'rmse_naive': round(float(rmse_naive), 2),
        'rmse_ma3': round(float(rmse_ma3), 2),
        'rmse_holt': round(float(rmse_holt), 2),
        'future_holt': [round(float(x), 1) for x in future_holt],
        'future_ma3': [round(float(x), 1) for x in future_ma3],
        'resid_std': round(float(resid_std), 2)
    }


def main():
    df_clean, df_summary, df_star = load_and_clean_data()
    daily_active, daily_full, weekly_df, monthly_df = build_timeseries_datasets(df_clean)
    forecast_metrics = generate_visualizations(df_clean, daily_active, daily_full, weekly_df, monthly_df, df_star)

    print("\n" + "=" * 70)
    print("[4단계] 핵심 분석 요약 통계 출력")
    print("=" * 70)
    print(f"- 분석 기간: {df_clean['review_date'].min().strftime('%Y-%m-%d')} ~ {df_clean['review_date'].max().strftime('%Y-%m-%d')}")
    print(f"- 총 리뷰 수: {len(df_clean)}건 (고유 일수: {len(daily_active)}일, 연속 주수: {len(weekly_df)}주, 월수: {len(monthly_df)}개월)")
    print(f"- 표본 단순평균 평점: {df_clean['rating_num'].mean():.2f}★ / 모집단 가중 보정 평점: {np.average(df_clean['rating_num'], weights=df_clean['pop_weight']):.2f}★")
    mean_us = (df_clean['country'] == 'United States').mean() * 100
    print(f"- 국가 수: {df_clean['country'].nunique()}개국 (미국 {sum(df_clean['country']=='United States')}건 [{mean_us:.1f}%], 비미국 {sum(df_clean['country']!='United States')}건 [{100-mean_us:.1f}%])")
    print(f"- 예측 결과: {forecast_metrics}")


if __name__ == '__main__':
    main()
