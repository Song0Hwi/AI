# 고객 리뷰 감정 분석 대시보드

화장품 리뷰 CSV·Excel 을 수집·정제해 SQLite 에 넣고, Gemini 로 감정을 분석한 뒤
통계 · 대시보드 차트 · Markdown 리포트를 만드는 CLI 도구입니다.

```bash
python main.py import --file source/input/cosmetics_reviews_100.csv
python main.py analyze --unanalyzed --limit 25
python main.py extract
python main.py dashboard
```

네 줄이면 원본 CSV 에서 리포트까지 나옵니다.

---

## 한눈에

| | |
|---|---|
| 규모 | 파이썬 18개 파일 · **9,146줄** · 함수 238개 |
| CLI | 서브커맨드 **12개** (10개는 API 키 없이 동작) |
| 저장소 | SQLite 테이블 5개 |
| 시각화 | 대시보드 차트 **7종** (PNG) |
| 자동 테스트 | A **58개** (직접 확인) · C 25개 (민규님 보고, 아래 11번 참고) |
| 실측 | 리뷰 99건 · 감정 분석 99건 · 별점-감정 일치도 **81.8%** |

---

## 1. 팀 구성과 분업

3인이 폴더 하나씩 맡습니다. **자기 폴더만 수정합니다.**

| 담당 | 폴더 | 범위 | 문서 |
|---|---|---|---|
| **A** 영휘 | `chart/` | DB · CLI · 집계 · 차트 · export · 전체 통합 | [chart/README.md](chart/README.md) |
| **B** 세인 | `source/` | 수집 · 정제 | [source/README.md](source/README.md) |
| **C** 민규 | `prompt/` | AI 감정 분석 · 인사이트 · 리포트 | [prompt/README.md](prompt/README.md) |

세 사람의 접점은 [INTERFACE.md](INTERFACE.md) 에 계약으로 적혀 있고,
`chart/check_contract.py` 가 그 계약을 **실행해서** 확인합니다.

---

## 2. 아키텍처

### 의존 방향은 한 방향입니다

```
        ┌─────────────┐
        │  A  chart/  │  DB · CLI · 집계 · 차트 · 통합
        └──────┬──────┘
               │  bridge.py 한 곳에서만 호출
       ┌───────┴───────┐
       ▼               ▼
┌─────────────┐ ┌─────────────┐
│  B source/  │ │  C prompt/  │
│  수집·정제   │ │  AI·리포트   │
└─────────────┘ └─────────────┘
```

**B와 C는 A를 import 하지 않습니다.** 그래서 두 사람이 A쪽 코드 없이
자기 폴더만으로 개발하고 테스트할 수 있습니다.

`main.py` 도 `source/` 나 `prompt/` 를 직접 import 하지 않습니다.
전부 `chart/modules/bridge.py` 를 거칩니다.

### B/C 폴더에 파일을 만들지 않습니다

`prompt/` 와 `source/src/` 에는 `__init__.py` 가 없어서 평범한 import 가 안 됩니다.
A가 `__init__.py` 를 하나 넣으면 그 폴더는 더 이상 그 사람만의 것이 아니게 되고
머지 충돌이 시작됩니다.

그래서 패키지 import 대신 **파일 경로로 직접 모듈을 읽는 로더**를 A쪽에 뒀습니다.
통합 테스트에 이 경계를 감시하는 항목도 있습니다.

### 숫자는 한 곳에서만 셉니다

차트가 자기 손으로 세고 리포트가 또 세면, 같은 데이터인데 차트는 89건
리포트는 90건이 되는 일이 반드시 생깁니다.

`chart/modules/stats.py` 의 `calculate_stats()` 하나가 6칸을 만들고,
쓰는 쪽은 **자기 칸만** 봅니다.

```python
{
    "meta":       {...},   # 생성 시각 · 필터
    "summary":    {...},   # ← 리포트(C)
    "chart_data": {...},   # ← 차트(A)
    "quality":    {...},   # ← 리포트(C)
    "top_n":      {...},   # ← 리포트(C) · 개선 우선순위 포함
    "alerts":     [...],   # ← CLI · 리포트. 임계치 판정 결과
}
```

---

## 3. 설치

```bash
pip install -r chart/requirements.txt

cp chart/.env.example chart/.env
# .env 에 GEMINI_API_KEY 를 넣습니다. analyze / extract 는 키가 있어야 돕니다.
```

Python 3.9 이상. 의존성은 네 개뿐입니다 — `google-genai` · `python-dotenv` ·
`matplotlib` · `openpyxl`. 뒤의 둘은 없어도 죽지 않습니다
(차트를 건너뛰거나 xlsx 가 csv 로 떨어집니다).

---

## 4. 빠른 시작

```bash
# 1. 수집 + 정제 + DB 저장  (B 모듈 사용)
python main.py import --file source/input/cosmetics_reviews_100.csv
#    .xlsx 도 됩니다 — A가 CSV 로 눕혀 B에게 넘깁니다

# 2. 감정 분석  (C 모듈 사용 · Gemini 호출)
python main.py analyze --unanalyzed --limit 25

# 3. AI 인사이트 추출  (C 모듈 사용 · Gemini 호출)
python main.py extract

# 4. 통계 · 경고 · 개선 우선순위 확인
python main.py stats

# 5. 대시보드 차트 + 종합 리포트  (A → C 전체 연결)
python main.py dashboard
```

2번과 3번만 실제 Gemini 를 부릅니다. 키가 없으면 시작 전에 멈춥니다.
99건을 다 부르기 전에 `--limit 5` 로 한 번 확인해 보세요.

나머지는 키가 없어도 돕니다. 이미 분석해 둔 결과가 DB에 있으면
`dashboard` 만으로 차트와 리포트가 다시 나옵니다.

---

## 5. 명령어

| 명령 | 하는 일 | 사용 모듈 | 키 |
|---|---|---|---|
| `import` | CSV·Excel → raw → 정제 → DB | B | |
| `add` | 리뷰 1건 직접 추가 | A | |
| `clean` | 원본 파일 없이 raw 재정제 | B | |
| `analyze` | AI 감정 분석 → DB 저장 | C | 필요 |
| `extract` | AI 키워드·요약·개선 제안 | C | 필요 |
| `list` | 필터·정렬·페이지네이션 조회 | A | |
| `show` | 리뷰 1건 상세 | A | |
| `stats` | 통계 + 경고 + 개선 우선순위 | A | |
| `dashboard` | 통계 + 차트 7종 + 리포트 | A→C | |
| `export` | CSV/JSONL/XLSX 내보내기 | A | |
| `review` | AI 결과 사람 검수 (표본 → 라벨 → 점수) | A | |
| `status` | 저장소·모듈 현황 | A | |

주요 옵션

```bash
python main.py list --sentiment negative --sort rating --page 2 --size 5
python main.py analyze --unanalyzed --limit 20 --force
python main.py extract --sentiment negative --product "데일리 선크림"
python main.py stats --skin-type 지성 --date-from 2025-01-01
python main.py dashboard --no-charts
python main.py export --format xlsx --rating-min 4
python main.py review sample --size 30
python main.py review load --file <검수완료.csv> --reviewer 영휘
python main.py review score
python main.py status
```

전역 플래그 `--verbose` / `--quiet` 는 서브커맨드 앞뒤 어디에 붙여도 됩니다.

**종료 코드** — 성공 `0`, 실패 `1`, **일부 실패 `2`**, 사용자 중단 `130`.
`2` 는 `analyze` 에서 일부 리뷰만 실패했거나 `review score` 의 일치율이
기준 미달일 때 나옵니다. 셸 체이닝(`&&`)이나 CI 에서 구분할 수 있습니다.

### `dashboard` 가 만드는 차트 7종

`chart/output/` 에 저장되고 그대로 리포트에 실립니다.

| 파일 | 답하는 질문 |
|---|---|
| `kpi_summary.png` | 그래서 몇 건이고 얼마나 부정적인가 |
| `sentiment_distribution.png` | 감정이 어떻게 나뉘는가 |
| `sentiment_trend.png` | 시간에 따라 나빠지는가 (일/주/월 자동) |
| `rating_distribution.png` | 별점이 어떻게 분포하는가 |
| `rating_sentiment.png` | 별점과 감정이 맞는가 |
| `product_sentiment.png` | 어느 제품이 문제인가 |
| `skin_type_sentiment.png` | 어느 피부타입에서 갈리는가 |

데이터가 없으면 그 장은 건너뜁니다. 어느 장이 빠졌는지는 실행 끝에 찍힙니다.

---

## 6. 설정

### `chart/.env` — API 키

```bash
GEMINI_API_KEY=발급받은_키
```

`analyze` 와 `extract` 만 이 키를 씁니다. `.env` 는 커밋하지 않습니다.

### `chart/config.json` — 동작 설정

파일이 없어도 기본값으로 돌아갑니다. 바꾸고 싶은 키만 적으면 됩니다.

| 키 | 기본값 | 뜻 |
|---|---|---|
| `duplicate_policy` | `skip` | 중복 리뷰 처리. `skip` 무시 · `upsert` 갱신 |
| `database.path` | `""` | 비우면 `chart/db/reviews.db`. 환경변수 `REVIEW_DB_PATH` 가 더 우선 |
| `cleaning.min_review_length` | `5` | `add` 명령의 최소 글자 수 |
| `cleaning.rating_min` / `rating_max` | `1` / `5` | 허용 별점 범위 |
| `cleaning.duplicate_keys` | 제품·본문·날짜 | 중복 판정 해시에 넣을 필드 |
| `ai.model` | `gemini-3.6-flash` | 사용할 모델. `analyses.model` 에 기록 |
| `ai.api_key_env` | `GEMINI_API_KEY` | 키를 읽을 환경변수 이름 |
| `ai.extract_max_reviews` | `60` | `extract` 프롬프트에 넣을 최대 리뷰 수 |
| `visualization.dpi` / `save_format` | `150` / `png` | 차트 해상도·형식 |
| `analysis.default_limit` | `20` | `analyze` 에서 `--limit` 을 안 줬을 때 |
| `analysis.top_n` | `5` | TOP N 집계와 그룹별 차트 항목 수 |
| `logging.level` / `to_file` / `filename` | `INFO` / `true` / `app.log` | 로깅 |

**`alerts`** 는 경고 임계치입니다. 판정 로직과 대응 절차는
[chart/README.md](chart/README.md) 4.10 절에 있습니다.

| 키 | 기본값 | 뜻 |
|---|---|---|
| `negative_ratio_warn` / `_critical` | `0.15` / `0.30` | 전체 부정 비율 경고선 · 심각선 |
| `spike_delta` | `0.10` | 직전 구간 대비 부정률이 이만큼 오르면 급증 |
| `min_bucket_size` | `5` | 표본이 이보다 작은 구간은 판정하지 않음 |
| `group_negative_ratio_warn` | `0.30` | 제품·피부타입별 부정 비율 경고선 |
| `min_group_size` | `5` | 표본이 이보다 작은 그룹은 판정하지 않음 |
| `agreement_warn` | `0.60` | 별점-감정 일치도 하한 |
| `confidence_warn` | `0.65` | 평균 확신도 하한 |

임계치는 **업계 표준이 아니라 이 데이터셋 기준의 출발점**입니다.
제품군이나 수집 채널이 바뀌면 다시 잡아야 합니다.

---

## 7. 데이터가 어디에 쌓이나

SQLite 파일 하나입니다. 기본 경로는 `chart/db/reviews.db` 이고,
OneDrive·네트워크 드라이브 위에서 `disk I/O error` 가 나면
`REVIEW_DB_PATH` 환경변수로 로컬 경로로 옮기세요.

### `raw_reviews` — 원본 보관

| 컬럼 | 설명 |
|---|---|
| `id` | INTEGER PK |
| `source_file` | 어느 파일에서 왔는지 |
| `payload` | 원본 한 행을 JSON 그대로 |
| `imported_at` | 수집 시각 |

정제 규칙을 바꿔 다시 돌릴 때 씁니다. 원본 CSV 가 없어도 `clean` 명령으로 재처리됩니다.

### `reviews` — 정제본

| 컬럼 | 설명 |
|---|---|
| `id` | 리뷰 ID. CLI 의 `--id`, `show <id>` 가 이 값 |
| `review_hash` | **UNIQUE.** 제품·본문·날짜를 정규화한 SHA-256 |
| `product_name` | 제품명. **NULL 가능** |
| `review_text` | 본문. NOT NULL |
| `rating` | 별점 1~5. **NULL 가능** |
| `review_date` | `YYYY-MM-DD`. **NULL 가능** |
| `skin_type` | 피부 타입. **NULL 가능** |
| `source_file` | 출처 |
| `created_at` / `updated_at` | 등록·갱신 시각 |

### `analyses` — 감정 분석 결과

| 컬럼 | 설명 |
|---|---|
| `id` | INTEGER PK |
| `review_id` | **UNIQUE.** `reviews.id` 참조. 리뷰 1건당 최신 1건 |
| `sentiment` | `positive` / `negative` / `neutral` (CHECK 제약) |
| `confidence` | **0.0~1.0** (CHECK 제약). 모델이 스스로 매긴 확신도 |
| `language` | `ko` / `en`. 본문에 한글이 있는지로 A가 채움 |
| `model` | 어느 모델로 분석했는지. 버전별 비교에 씀 |
| `analyzed_at` | 분석 시각 |

`review_id` 가 UNIQUE 라 **재분석해도 행이 늘지 않고 덮어씁니다.**

### `extractions` — 키워드·요약 추출 이력

| 컬럼 | 설명 |
|---|---|
| `id` | INTEGER PK |
| `scope` | 어떤 조건으로 뽑았는지 (JSON) |
| `review_count` | 대상 리뷰 수 |
| `positive_keywords` / `negative_keywords` / `improvements` | JSON 배열 |
| `summary` | 종합 요약 |
| `model` / `created_at` | |

`dashboard` 는 **가장 최근 1건**만 리포트에 싣습니다.

### `human_labels` — 사람이 매긴 검수 라벨

| 컬럼 | 설명 |
|---|---|
| `id` | INTEGER PK |
| `review_id` | `reviews.id` 참조 |
| `batch` | 검수 회차 (`review sample` 이 만든 타임스탬프) |
| `reviewer` | 검수자 이름 |
| `sentiment` | 사람이 매긴 감정 (CHECK 제약) |
| `note` | 메모 (불일치 사유 등) |
| `ai_sentiment` / `ai_confidence` / `ai_model` | **검수 시점의 AI 판정 스냅샷** |
| `labeled_at` | 검수 시각 |

`(review_id, batch, reviewer)` 가 UNIQUE 라 다시 매기면 덮어씁니다.

AI 판정을 스냅샷으로 함께 두는 이유는, `analyses` 가 재분석 시 덮어써지기 때문입니다.
스냅샷이 없으면 프롬프트를 바꾼 뒤 "그때 무엇과 비교했는지" 가 사라져
버전별 A/B 비교가 불가능해집니다.

---

## 8. 파트별 요약

각 파트의 설계 결정과 근거는 링크한 문서에 있습니다.

### A · `chart/` — DB · CLI · 집계 · 대시보드 · 통합

8,224줄 · 모듈 10개 · 함수 220개. SQLite 스키마와 저장·조회, 중복 판정 해시,
6칸 통계 집계, 임계치 판정과 급증 감지, 대시보드 차트 7종, 세 형식 export,
AI 검수와 프롬프트 A/B 비교, CLI 12개 명령, 그리고 B·C 를 이어 붙이는 창구와
계약 검증기.

특징적인 결정 몇 가지:

- **감정 분석에 별점을 넘기지 않습니다.** DB에서 13개 키를 읽지만 C에게는
  `id` 와 `review_text` 두 개만 줍니다. 별점이 프롬프트에 들어가면
  '별점-감정 일치도' 가 항상 100% 가 되어 지표가 죽습니다. 실측 81.8%
- **차트 색을 검증기로 골랐습니다.** 초록/회색 조합이 적록색약에서 ΔE 1.2 로
  구분되지 않아 파랑↔빨강 diverging 으로 바꿨습니다
- **경고는 원인을 단정하지 않습니다.** "어디에 몰려 있는가" 까지만 말하고
  `확인 후보` · `다음 지표` 로 이름을 나눴습니다. 판정과 동시에 로그에 남겨
  회차별 추이를 추적할 수 있습니다
- **AI 정확도를 사람 라벨로 잽니다.** `review` 명령으로 표본을 뽑아 검수하고
  일치율·혼동 방향·프롬프트 버전별 A/B 를 산출합니다. 프롬프트를 고치는 건
  C 영역이라, A는 고칠 근거가 되는 숫자까지만 냅니다

→ [chart/README.md](chart/README.md)

### B · `source/` — 수집과 정제

229줄 · 파일 2개 · 함수 10개. **표준 라이브러리만** 씁니다.

CSV 를 `utf-8-sig` 로 읽어(Excel BOM 대응) 필수 5컬럼을 확인하고,
원본을 JSONL 로 그대로 보존한 뒤, 본문 5자·별점 1~5·날짜 세 형식을 기준으로
정제해 다섯 키짜리 레코드로 내보냅니다. 날짜 표기(`-` `/` `.`)를
`YYYY-MM-DD` 하나로 통일하는 것과 파일 안 중복 제거가 여기 몫입니다.

→ [source/README.md](source/README.md)

### C · `prompt/` — AI 감정 분석 · 인사이트 · 리포트

693줄 · 파일 3개. Gemini 호출과 결과 검증, Markdown 리포트 생성.

- `analyze_reviews()` 는 여러 건을 **한 프롬프트에 묶어** 부르고,
  실패하면 스스로 반으로 쪼개 재시도합니다. 입력한 id 는
  `results` 아니면 `failed_ids` 중 한쪽에 반드시 남습니다
- `extract_insights()` 는 실패해도 예외 대신 `None` 을 돌려줍니다.
  인사이트 하나 때문에 통계와 차트까지 못 보게 되면 안 되니까요
- 리포트는 `summary` · `quality` · `top_n` 세 칸만 읽고 `chart_data` 는 건드리지 않습니다

→ [prompt/README.md](prompt/README.md)

---

## 9. 통합 계약

세 사람이 주고받는 것은 **함수 다섯 개**가 전부입니다.
전문은 [INTERFACE.md](INTERFACE.md), C 담당이 볼 요약은 [C_인터페이스.md](C_인터페이스.md).

```python
# B → A
import_reviews(file_path, output_path) -> list[dict]
clean_reviews(input_path, output_path) -> list[dict]   # 5키 · rating 은 int

# A → C → A
analyze_reviews([{id, review_text}])
    -> {"results": [{id, sentiment, confidence}], "failed_ids": [int]}

extract_insights([str])
    -> {positive_keywords, negative_keywords, summary, improvements} | None

generate_markdown_report(stats, insights, chart_paths, output_path) -> str
```

계약의 핵심 세 가지입니다.

1. **id 는 사라지지 않습니다.** 넣은 id 는 `results` 아니면 `failed_ids` 중
   한쪽에 반드시 나타납니다. 둘 다에 없으면 그 리뷰는 조용히 사라진 것이고
   아무도 모릅니다
2. **한 건의 실패는 `failed_ids`, 부르는 쪽의 버그는 예외.** 100건 돌리다
   50번째에서 API 가 흔들렸다고 앞의 49건을 버리면 안 됩니다
3. **`rating` 은 감정 분석에 넘어가지 않습니다.** 합의가 아니라 넘기는 키를
   줄여서 구조적으로 막습니다

---

## 10. 동작 흐름

```
CSV · Excel
 └─ [A] Excel 이면 첫 시트를 임시 CSV 로 변환
     └─ [B] importer.import_reviews()   → source/raw/reviews.jsonl
         └─ [A] save_raw()              → SQLite raw_reviews
 └─ [B] cleaner.clean_reviews()         → source/clean/reviews.jsonl
     └─ [A] save_clean()                → SQLite reviews  (해시 중복 판정)
         └─ [C] analyze_reviews()       → sentiment / confidence
             └─ [A] 계약 검증 → save_sentiment_results()
                 └─ [A] calculate_stats()   6칸
                     ├─ [A] generate_charts()          → PNG 7장
                     └─ [C] generate_markdown_report() → chart/output/report_*.md
```

차트 경로는 A가 **리포트 파일 기준 상대경로**로 바꿔 C에게 넘깁니다.
절대경로를 그대로 넣으면 만든 사람 PC 에서만 이미지가 보이고 GitHub 에서는 깨집니다.

---

## 11. 검증

```bash
python chart/check_contract.py           # 계약 자가 점검 (B/C/A 전체)
python chart/tests/test_integration.py   # A 통합 테스트 58개
python main.py review score              # AI 정확도 (사람 라벨 대비)
```

**둘 다 API 키 없이 돕니다.** 분석 결과가 필요한 구간은 각 테스트 파일 안의
대역이 대신합니다. 테스트 한 번에 과금되면 아무도 테스트를 안 돌리게 됩니다.

### 자가 점검의 네 가지 표시

| 표시 | 뜻 |
|---|---|
| `[OK]` | 약속대로 동작 |
| `[FAIL]` | **만들었는데 약속과 다름.** 이것만 고치면 됨 |
| `[SKIP]` | 아직 안 만듦. 실패로 치지 않음 |
| `[TODO]` | 약속 위반이 아니라 **새로 부탁하는 것** |

`[TODO]` 를 `[FAIL]` 과 섞지 않은 이유가 있습니다. 전달 조건이
"자기 영역에 FAIL 없을 것" 이라, 새 요청이 빨간불로 뜨면 다 만든 사람도
빨간불이 되고 그러면 진짜 `[FAIL]` 을 보고도 아무도 안 움직이게 됩니다.

### 2026-08-14 결과

| 영역 | 계약 점검 | 자동 테스트 |
|---|---|---|
| A 영휘 | `[OK]` 8 / 8 | 58개 통과 (직접 확인) |
| B 세인 | `[OK]` 2 / 2 | 없음 |
| C 민규 | `[OK]` 4 · `[FAIL]` 1 · `[TODO]` 3 | 25개 통과 (민규님 보고 · 아래 참고) |

C의 단위 테스트 25개는 민규님 문서에 실행 결과가 적혀 있지만
**`prompt/tests/` 폴더가 아직 레포에 올라오지 않아** 여기서 직접 돌려보지 못했습니다.
계약 점검(`check_contract.py --c`)은 실제 `prompt/*.py` 를 불러 확인한 결과입니다.

end-to-end — 빈 DB → import(CSV·xlsx) → analyze → extract → stats →
dashboard → export 전 구간 정상.

실제 데이터 99건 기준:

```
분석 완료 99건 (100.0%)   평균 별점 3.65   평균 확신도 0.91
긍정 57 (57.6%) · 중립 38 (38.4%) · 부정 4 (4.0%)
별점-감정 일치도 81.8%    데이터 완전성 100.0%
차트 7/7장 · 리포트 생성 완료

경고 1건 — 2025-05 부정 비율 급증 (0% → 14%, +14%p)
개선 우선순위 1위 — '유분 증가' (8건, 부정 25%, 평균 별점 2.75 / 전체 3.65)
```

---

## 12. 폴더 구조

```
review_dashboard/
├── main.py                     # 루트 런처 (python main.py)
│
├── source/                     # B(세인) 전용
│   ├── src/importer.py         #   CSV → raw JSONL
│   ├── src/cleaner.py          #   raw → clean JSONL
│   ├── input/  raw/  clean/    #   원본 CSV · B 산출물
│   └── README.md
│
├── prompt/                     # C(민규) 전용
│   ├── analyzer.py             #   Gemini 감정 분석
│   ├── extractor.py            #   인사이트 추출
│   ├── reporter.py             #   Markdown 리포트
│   └── README.md
│                               #   tests/ 는 아직 미커밋
│
├── chart/                      # A(영휘) 전용
│   ├── main.py                 #   CLI 본체 (11개 명령)
│   ├── config.json             #   설정 · 경고 임계치
│   ├── check_contract.py       #   계약 자가 점검
│   ├── modules/
│   │   ├── paths.py            #   경로 해석 + B/C 모듈 로더
│   │   ├── bridge.py           #   외부 폴더 호출 창구 · Excel→CSV
│   │   ├── database.py         #   SQLite + 중복 판정 해시
│   │   ├── stats.py            #   집계 6칸 · 임계치 · 우선순위
│   │   ├── visualizer.py       #   대시보드 차트 7종
│   │   ├── exporter.py         #   csv / jsonl / xlsx
│   │   ├── interfaces.py       #   계약 검증기
│   │   ├── config.py  logger.py
│   ├── tests/                  #   A 통합 테스트 43개
│   ├── db/  output/  logs/     #   실행 시 생성 (gitignore)
│   └── README.md
│
├── INTERFACE.md                # 3인 공통 계약 (v5)
└── C_인터페이스.md              # C 담당이 볼 명세만 추린 것
```

---

## 13. 남은 항목

A·B 영역은 `[FAIL]` 이 없습니다. 아래는 C(민규) 영역이고,
자세한 내용과 목표 마크다운은 [C_인터페이스.md](C_인터페이스.md) 6번에 있습니다.

| 구분 | 내용 |
|---|---|
| `[FAIL]` | `validate_insight_result()` 가 `improvements` 를 2개 이상 요구 — 계약에 없는 조건. 모델이 1개만 준 날 `extract` 가 통째로 실패 |
| `[TODO]` | 리포트가 `chart_paths` 의 키를 버리고 `차트 1~7` 로 번호를 매김 |
| `[TODO]` | 리포트가 `stats["meta"]` 를 안 읽어 생성 시각·필터 범위가 없음 |
| `[TODO]` | `product_name` 이 `None` 인 리뷰에서 문자열 `"None"` 이 찍힘 |

셋 다 A가 **이미 넘기고 있는 값**입니다. A쪽에서 더 보낼 것은 없고,
쓸지 말지가 리포트를 만드는 쪽의 몫이라 `[TODO]` 로 뒀습니다.

그 밖에:

- **`prompt/tests/` 가 레포에 없습니다.** 민규님 문서에는 25개 통과로 적혀 있는데
  폴더가 커밋되지 않아 다른 사람이 돌려볼 수 없습니다. 커밋만 하면 됩니다
- **B 영역 자동 테스트가 없습니다.** A 통합 테스트가 접점은 보고 있지만,
  정제 규칙 자체(경계값 4자/5자, 별점 0/1/5/6, 날짜 세 형식)는
  B 영역 테스트로 두는 게 맞습니다. [source/README.md](source/README.md) 7번 표가
  그대로 테스트 케이스가 됩니다
- **날짜가 없으면 리뷰 전체가 버려집니다.** `review_date` 는 계약상 nullable 인데
  정제 단계에서 drop 합니다. 지금 데이터는 100건 전부 날짜가 정상이라 드러나지 않습니다
- Gemini 가 503(과부하)을 내면 C가 배치를 반으로 쪼개 재시도하는데
  **그 사이에 대기가 없습니다.** 실제로 99건 시도 중 뒤쪽 49건이 이렇게 실패했고,
  `analyze --unanalyzed --limit 25` 로 나눠 돌려 복구했습니다

---

## 14. 참고

- **API 키 없이 확인**할 수 있는 것: `import` · `stats` · `dashboard` · `export` ·
  `list` · `show` · `status` · `add` · `clean`, 그리고 자동 테스트와 계약 점검 전체
- **차트 한글 폰트**: Windows 는 맑은 고딕이 기본 포함이라 그대로 나옵니다.
  Linux 에서 한글이 두부(□)로 나오면 `apt install fonts-nanum` 후 다시 실행하세요.
  폰트를 못 찾으면 차트 라벨이 자동으로 영문으로 바뀝니다
- `.env` 는 커밋하지 않습니다. `.venv/`, `.idea/`, `chart/db/`, `chart/output/`,
  `chart/logs/` 도 `.gitignore` 에 있습니다
