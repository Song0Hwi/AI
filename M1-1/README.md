# M1-1: 시계열 데이터 분석 및 인사이트 리포트 — AXIS-Y 비건 콜라겐 아이 세럼 글로벌 리뷰 분석

아마존(Amazon) 글로벌 리뷰 데이터(`ASIN: B0CWPCX1D2`, 총 478건 / 모집단 4,325건)를 일별·주별·월별 시계열 데이터로 정제하고, 이동평균(MA), 변화율(MoM), 층화 표집 편향 보정(`pop_weight`), 시계열 분해(Decomposition), 베이스라인 예측(Forecast) 및 인터랙티브 웹 대시보드까지 구현한 프로젝트입니다.

---

## 📁 폴더 및 파일 구조

```text
M1-1/
├── data/
│   ├── axis_y_reviews_raw.xlsx      # 원본 아마존 리뷰 데이터 (Reviews, Summary, StarDistribution 3개 시트)
│   ├── reviews_cleaned.csv          # 정제 및 특성 공학 완료 개별 리뷰 시계열 데이터 (478건)
│   ├── timeseries_daily.csv         # 일별 시계열 집계 및 7일·14일 이동평균 데이터 (324개 활성일)
│   ├── timeseries_weekly.csv        # 주별 시계열 집계 및 4주·8주 이동평균 데이터 (126주 연속)
│   └── timeseries_monthly.csv       # 월별 시계열 집계, MoM 변화율, 가중 보정 평점, 토픽 비중 (26개월)
├── images/
│   ├── 01_review_volume_and_ma_trend.png      # [시각화 1] 월별/일별 유입량 추이, 이동평균 및 3단계 성장 국면
│   ├── 02_rating_trend_and_sampling_bias.png  # [시각화 2] 표본 평점 vs 모집단 가중 보정 평점 추이 및 분포 비교
│   ├── 03_global_market_and_seasonality.png   # [시각화 3] 미국 vs 글로벌 18개국 확산 추이 및 국가별 평점 비교
│   ├── 04_pain_points_and_topic_trends.png    # [시각화 4] 긍정 매력 요인 vs 3대 불만 요인 별점별·시계열 추이
│   ├── 05_timeseries_decomposition.png        # [보너스 A] 시계열 분해 (Trend + Periodic + Residual 및 이상치 탐지)
│   └── 06_timeseries_forecast.png             # [보너스 B] 베이스라인 3종 예측 및 향후 3개월 전망
├── REPORT.md                        # 📊 최종 시계열 분석 및 인사이트 리포트 (필수 + 보너스 전체 포함)
├── analysis.py                      # 🐍 시계열 데이터 정제·집계·시각화 자동화 Python 스크립트
├── analysis.ipynb                   # 📓 단계별 분석 코드 및 실행 출력이 포함된 Jupyter Notebook
├── app.py                           # 🌐 (보너스) 인터랙티브 웹 대시보드 로컬 서버 실행 스크립트
├── dashboard.html                   # 🖥️ (보너스) 독립 실행형 인터랙티브 시계열 탐색 웹 대시보드
├── requirements.txt                 # 📦 Python 패키지 의존성 목록
└── introduction.md                  # 📋 미션 소개 및 요구사항 명세서
```

---

## 🚀 빠른 실행 방법 (Quick Start)

### 1. 환경 준비 및 의존성 설치
```bash
pip install -r requirements.txt
```

### 2. 시계열 데이터 정제 및 시각화 차트 6종 재현
```bash
python analysis.py
```
- 실행 시 `data/` 폴더 내 4종의 정제된 CSV 파일과 `images/` 폴더 내 6종의 고해상도 PNG 차트가 자동 생성됩니다.

### 3. 인터랙티브 웹 대시보드 실행 (보너스 과제)
```bash
python app.py
```
- 실행 시 로컬 웹 서버(`http://localhost:8050/dashboard.html`)가 구동되며, 브라우저에서 **집계 단위(일/주/월), 기간, 이동평균 윈도우(MA 3/5/7), 국가/지역, 별점 그룹, 핵심 토픽/이슈**를 바꿔가며 시계열 데이터를 동적으로 탐색할 수 있습니다.
- 서버 실행 없이 `dashboard.html` 파일을 브라우저에서 직접 열어도 동일하게 작동합니다.

---

## 📌 핵심 결과물 바로가기
- **최종 분석 리포트:** [REPORT.md](REPORT.md)
- **정제 및 분석 코드:** [analysis.py](analysis.py) / [analysis.ipynb](analysis.ipynb)
- **웹 대시보드:** [dashboard.html](dashboard.html) / [app.py](app.py)
