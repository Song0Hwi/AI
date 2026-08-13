# A 파트 · chart/ — DB · CLI · 집계 · 대시보드 · 통합

> 담당 **영휘** · 2026-08-13
> 전체 프로젝트 소개는 루트 [README.md](../README.md),
> 3인 공통 계약은 [INTERFACE.md](../INTERFACE.md) 를 보세요.

리뷰 데이터를 **받아서 저장하고, 세고, 그리고, 다른 두 사람의 코드를 이어 붙이는** 자리입니다.
B(세인)는 파일을 읽고 정제하고, C(민규)는 모델을 부릅니다.
그 사이의 저장·조회·집계·시각화와 전체 실행 흐름이 A 영역입니다.

---

## 1. 담당 범위

| 맡은 것 | 안 맡은 것 |
|---|---|
| SQLite 스키마 · 저장 · 조회 · 중복 판정 | CSV 읽기 · 정제 규칙 (B) |
| 통계 집계 (프로젝트에서 숫자를 세는 유일한 곳) | 감정 분석 프롬프트 · 모델 호출 (C) |
| 대시보드 차트 7종 | 리포트 마크다운 형식 (C) |
| CSV / JSONL / XLSX 내보내기 | |
| CLI 11개 명령과 종료 코드 | |
| B·C 모듈 호출 창구, 계약 검증, 통합 테스트 | |

**규모** — `chart/` 6,047줄 (제품 코드 4,443 · 테스트 791 · 자가 점검 813), 모듈 9개, 함수 118개.

---

## 2. 폴더 구조

```
chart/
├── main.py               1,140줄  CLI 본체 (11개 명령)
├── config.json                    설정
├── check_contract.py       813줄  계약 자가 점검 (B/C/A)
├── requirements.txt
├── .env.example
├── modules/
│   ├── paths.py            153줄  경로 해석 + B/C 모듈 로더
│   ├── bridge.py           162줄  외부 폴더(source/, prompt/) 호출 창구
│   ├── config.py           174줄  설정 로딩·검증
│   ├── logger.py            97줄  콘솔 + 파일 로깅
│   ├── database.py         778줄  SQLite · 중복 판정 해시
│   ├── stats.py            536줄  집계 (5칸)
│   ├── visualizer.py       846줄  대시보드 차트 7종
│   ├── exporter.py         231줄  csv / jsonl / xlsx
│   └── interfaces.py       326줄  계약 검증기
├── tests/test_integration.py 791줄  통합 테스트 29개
└── db/ output/ logs/              실행 시 생성 (.gitignore)
```

---

## 3. 실행

```bash
pip install -r chart/requirements.txt
cp chart/.env.example chart/.env      # GEMINI_API_KEY 를 넣습니다
```

레포 루트에서 실행합니다. `main.py` 는 `chart/main.py` 를 불러주는 런처입니다.

```bash
python main.py import --file source/input/cosmetics_reviews_100.csv   # 수집 → 정제 → DB
python main.py analyze --unanalyzed --limit 25                        # 감정 분석 (C)
python main.py extract                                                # 인사이트 추출 (C)
python main.py dashboard                                              # 차트 7장 + 리포트
```

### 명령 11개

| 명령 | 하는 일 | API 키 |
|---|---|---|
| `import` | CSV → 정제 → DB. 중복은 해시로 차단 | |
| `add` | 리뷰 1건 직접 추가 | |
| `clean` | 원본 CSV 없이 DB의 raw 를 재정제 | |
| `analyze` | 감정 분석 → DB 저장 | 필요 |
| `extract` | 키워드 · 요약 · 개선 제안 | 필요 |
| `list` | 필터 · 정렬 · 페이지네이션 조회 | |
| `show` | 리뷰 1건 상세 | |
| `stats` | 통계 요약 (콘솔) | |
| `dashboard` | 통계 + 차트 7장 + 리포트 | |
| `export` | csv / jsonl / xlsx | |
| `status` | 저장소 · 모듈 · 폰트 현황 | |

**11개 중 9개가 키 없이 돕니다.** 모델을 부르는 것은 `analyze` 와 `extract` 둘뿐입니다.

### 종료 코드

| 코드 | 뜻 |
|---|---|
| 0 | 성공 |
| 1 | 실패 |
| **2** | **일부 실패** — `analyze` 에서 몇 건만 실패 |
| 130 | 사용자 중단 |

2를 따로 둔 이유는 셸 체이닝에서 구분하기 위해서입니다.
`analyze && dashboard` 로 이으면 한 건이라도 실패했을 때 대시보드로 넘어가지 않습니다.

---

## 4. 설계 결정과 근거

이 파트에서 실제로 시간을 쓴 곳입니다. 코드보다 **왜 그렇게 했는지**가 남습니다.

### 4.1 감정 분석에 별점을 넘기지 않는다

`analyze` 는 DB에서 13개 키를 읽어오지만 C에게는 **두 개만** 넘깁니다.

```python
payload = [{"id": r["id"], "review_text": r["review_text"]} for r in reviews]
```

`rating` 이 프롬프트에 들어가면 모델이 별점을 그대로 따라갑니다.
그러면 품질 지표인 **별점-감정 일치도가 항상 100%** 가 되고, 순환논리라 아무것도 못 재게 됩니다.
주석이나 합의로 막지 않고 **넘기는 키를 줄여서 구조적으로** 막았습니다.

실제 측정값은 **81.8%** 로 나왔습니다. 100%가 아니라는 것 자체가 지표가 살아 있다는 증거입니다.

### 4.2 집계는 `stats.py` 한 곳에서만

차트가 자기 손으로 세고 리포트가 또 세면, 같은 데이터인데 차트는 89건 리포트는 90건이 되는 일이 반드시 생깁니다.
반올림 방식이나 미분석 포함 여부 같은 사소한 차이로 갈립니다.

그래서 `calculate_stats()` 하나가 5칸을 만들고, 쓰는 쪽은 자기 칸만 봅니다.

```python
{
    "meta":       {...},   # 생성 시각 · 필터
    "summary":    {...},   # ← 리포트(C)
    "chart_data": {...},   # ← 차트(A)
    "quality":    {...},   # ← 리포트(C)
    "top_n":      {...},   # ← 리포트(C)
}
```

KPI 요약 타일까지 이 규칙을 지킵니다. `chart_data["kpi_summary"]` 는 **새로 세는 값이 하나도 없고**
`summary` · `quality` 에서 옮겨오기만 합니다. 검증기가 이걸 직접 확인합니다.

```python
if kpi["total"] != summary["total"]:
    problems.append("KPI 는 다시 세지 않고 옮겨오기만 해야 합니다.")
```

### 4.3 중복 판정은 DB에서, 정규화된 해시로

B의 cleaner 는 **이번 파일 안의 중복**만 볼 수 있습니다. **이미 DB에 있는 중복**은 DB만 압니다.
그래서 `(product_name, review_text, review_date)` 를 공백 정규화·소문자화한 뒤 SHA-256 을 내고,
`reviews.review_hash` 에 UNIQUE 를 걸어 그 위에서 정책을 갈랐습니다.

```
skip   → INSERT OR IGNORE
upsert → INSERT ... ON CONFLICT(review_hash) DO UPDATE
```

세 컬럼에 그냥 composite UNIQUE 를 걸어도 될 것 같지만 두 가지가 새어 나갑니다.

- **정규화** — `"좋아요"` 와 `"좋아요 "` 가 다른 행이 됩니다. 같은 CSV 를 두 번 넣을 때마다 DB가 불어납니다
- **NULL** — SQLite 의 UNIQUE 는 NULL 을 서로 다른 값으로 봅니다. `add -t "..."` 를 `--product` 없이 두 번 치면 못 막습니다. 해시는 `None` 을 `""` 로 정규화해서 막습니다

### 4.4 실패를 한 칸 안에 가둔다

세 군데에서 같은 원칙을 씁니다.

| 상황 | 처리 |
|---|---|
| 리뷰 한 건 분석 실패 | 그 id 만 `failed_ids`, 나머지는 저장. 종료 코드 2 |
| 차트 한 장 실패 | 로그 남기고 나머지 6장 + 리포트는 그대로 |
| matplotlib 미설치 | `ImportError` 만 따로 잡아 차트를 건너뛰고 통계·리포트는 출력 |

100건 돌리다 50번째에서 API 가 흔들렸다고 앞의 49건을 버리면 안 됩니다.
그림 하나 때문에 통계까지 못 보게 되는 것도 마찬가지고요.

### 4.5 계약 검증을 저장 **앞에** 둔다

`interfaces.py` 가 C의 결과를 받자마자 확인합니다. 어긋나면 **DB에 값이 들어가기 전에** 멈춥니다.

- `results` / `failed_ids` 키 존재
- 각 `id` 가 int 이고 중복이 없는가
- 성공과 실패에 **같은 id** 가 들어 있지 않은가
- `sentiment` 가 세 값 중 하나인가, `confidence` 가 0.0~1.0 인가

사람을 못 믿어서가 아니라, 나중에 코드를 고쳤을 때 **조용히 틀린 값이 쌓이는 걸** 막으려는 장치입니다.

### 4.6 차트 색은 검증기를 돌려서 골랐다

1차본은 긍정 초록 / 중립 회색 / 부정 주황이었는데 떨어졌습니다.

```
[FAIL] CVD separation   #888780 ↔ #1D9E75  ΔE 1.2 (적록색약)
[FAIL] Normal-vision    #888780 ↔ #1D9E75  ΔE 11.9  (기준 15)
```

적록색약에서 회색과 초록이 사실상 같은 색으로 보입니다. 감정 분포 차트에서 중립과 긍정이 구분되지 않으면
그 차트는 아무 정보도 주지 못합니다.

감정은 `부정 ← 중립 → 긍정` 의 **극성(polarity)** 이라 categorical 이 아니라 **diverging** 입니다.
초록↔빨강은 색약에서 무너지는 대표 조합이라 파랑↔빨강으로 바꿨습니다.

```
[PASS] CVD separation   최악 인접쌍 ΔE 8.7 (deutan) · 12.7 (tritan)
[PASS] Normal-vision    최악 인접쌍 ΔE 16.2
[PASS] Contrast         3색 모두 배경 대비 3:1 이상
```

색만으로 의미가 전달되지 않도록 **모든 막대에 수치를 직접 표기**하고 범례를 항상 넣었습니다.
색 + 위치 + 숫자, 3중 인코딩입니다.

별점 분포 차트만 감정 3색을 안 씁니다. 4점 막대를 긍정색으로 칠하면 **'4점 = 긍정' 이라는 결론을 차트가 미리 내려버립니다.**
그 대응이 실제로 성립하는지 보려고 바로 옆에 '별점별 감정 구성' 을 두는 것이라, 여기서 색으로 답하면 두 차트가 같은 말을 하게 됩니다.

### 4.7 한글 폰트가 없으면 영문으로 떨어진다

폰트를 못 찾은 채로 한글을 그리면 글자가 전부 두부(□□□)로 나옵니다.
깨진 차트가 리포트에 박히는 것보다 영문이 낫습니다.

```python
resolve_font() -> (폰트명, 한글가능여부)   # 못 찾으면 (None, False), 결과는 캐시
```

Windows(맑은 고딕) → macOS(AppleGothic) → Linux(나눔·Noto) 순으로 찾고,
모든 라벨이 `_title(한글, 영문)` 을 거칩니다.
`axes.unicode_minus = False` 도 함께 걸었습니다 — 한글 폰트에는 유니코드 마이너스가 없는 경우가 많아 음수 눈금만 두부로 나옵니다.

### 4.8 B/C 폴더에 파일을 한 줄도 추가하지 않는다

`prompt/` 와 `source/src/` 에는 `__init__.py` 가 없어서 평범한 import 가 안 됩니다.
`__init__.py` 를 하나만 넣어도 그 폴더는 더 이상 그 사람만의 것이 아니게 되고 머지 충돌이 시작됩니다.

그래서 패키지 import 대신 **파일 경로로 직접 모듈을 읽는 로더**를 A쪽에 뒀습니다.

```python
spec = importlib.util.spec_from_file_location("c_analyzer", PROMPT_DIR / "analyzer.py")
```

이렇게 하면 B/C 폴더에 아무것도 안 생기고, `sys.path` 도 오염되지 않아 이름 충돌(`cleaner` 가 둘)이 안 납니다.
통합 테스트에 이 경계를 감시하는 항목도 넣었습니다.

### 4.9 대역(mock)은 연결이 끝나는 순간 걷어낸다

개발 초기에는 API 키 없이 배선을 확인하려고 `modules/mock_ai.py` 라는 규칙 기반 대역을 뒀습니다.
C의 Gemini 연결이 끝난 뒤 **파일과 `--mock` 플래그를 모두 제거**했습니다.

대역이 제품 코드 폴더에 남아 있으면 "지금 도는 게 진짜 분석인가 대역인가" 를 실행할 때마다 플래그로 확인해야 하고,
규칙 기반 결과가 DB에 섞여 들어가도 `model` 컬럼을 열어보기 전까지는 아무도 모릅니다.

테스트와 자가 점검이 쓰던 대역은 **각 테스트 파일 안으로** 옮겼습니다.
그 덕에 키 없이도 통합 테스트 29개와 계약 점검 전체가 그대로 돕니다.

---

## 5. 모듈별 구현

### `database.py` — SQLite (778줄)

테이블 4개입니다.

| 테이블 | 컬럼 | 역할 |
|---|---|---|
| `raw_reviews` | 4 | 원본 그대로 보관. 정제 규칙을 바꿔 다시 돌릴 때 씀 |
| `reviews` | 10 | 정제본. `review_hash` UNIQUE |
| `analyses` | 7 | 감정 분석. `review_id` UNIQUE (리뷰 1건당 최신 1건) |
| `extractions` | 9 | 키워드 · 요약 추출 이력 |

`analyses.review_id` 에 UNIQUE 를 건 덕에 **재분석해도 행이 늘지 않고 덮어씁니다.**
`migrate_schema()` 가 기존 DB 파일에 새 컬럼이 없으면 붙여줘서, 스키마가 바뀌어도 DB를 지우지 않아도 됩니다.

`REVIEW_DB_PATH` 환경변수로 DB 위치를 옮길 수 있습니다 — OneDrive·네트워크 드라이브 위에서 SQLite 가 `disk I/O error` 를 내는 경우가 있어서입니다.

### `stats.py` — 집계 (536줄)

`calculate_stats(filters)` 하나가 5칸을 만듭니다. 눈여겨볼 두 가지:

**분모가 다릅니다.** `analysis_rate` 는 전체 기준, `sentiment_ratios` 는 분석된 것 기준입니다. 섞으면 숫자가 안 맞습니다.

**추이의 집계 단위를 자동으로 바꿉니다.**

```
14일 이하  → 일별
120일 이하 → 주별 (그 주 월요일 날짜로 표기)
그 이상    → 월별
```

하루 1건씩 들어오는 데이터를 일별로 그리면 누적 차트가 바코드처럼 보여서 아무 정보도 주지 못합니다.

### `visualizer.py` — 대시보드 차트 7종 (846줄)

| 파일 | 형태 | 답하는 질문 |
|---|---|---|
| `kpi_summary.png` | 숫자 타일 6칸 | 그래서 몇 건이고 얼마나 부정적인가 |
| `sentiment_distribution.png` | 가로 막대 | 감정이 어떻게 나뉘는가 |
| `sentiment_trend.png` | 누적 막대 + 비율 선 | 시간에 따라 나빠지는가 |
| `rating_distribution.png` | 세로 막대 | 별점이 어떻게 분포하는가 |
| `rating_sentiment.png` | 100% 누적 가로 | 별점과 감정이 맞는가 |
| `product_sentiment.png` | 100% 누적 가로 | 어느 제품이 문제인가 |
| `skin_type_sentiment.png` | 100% 누적 가로 | 어느 피부타입에서 갈리는가 |

**입력은 `stats["chart_data"]` 뿐입니다.** 이 파일에서 숫자를 세지 않습니다.

이름 하나가 네 군데를 묶습니다.

```
stats.chart_data 의 키  ==  CHART_ORDER  ==  DRAWERS 키  ==  출력 파일명
```

하나만 오타가 나도 에러가 아니라 **차트가 조용히 한 장 사라집니다.** 그래서 테스트에 `set(chart_data) == set(CHART_ORDER)` 를 박아뒀습니다.

설계 선택 두 가지:

- **추이에 이중 축(dual-axis)을 안 씁니다.** '건수'와 '비율'은 단위가 다른데 y축 두 개를 세우면 두 계열의 교차점이 눈금 맞추기에 따라 마음대로 움직입니다. 아무 의미 없는 교차가 인과처럼 읽혀서, 위아래 패널로 나누고 x축만 공유합니다
- **그룹별 차트는 건수가 아니라 비율로 그립니다.** 5점 33건 / 1점 8건인데 건수로 그리면 막대 길이가 '리뷰가 몇 개인지'만 말합니다. 각 막대를 100%로 맞춰야 그룹 사이 비교가 됩니다. 대신 **건수를 막대 오른쪽에 따로** 적습니다 — 3건짜리 100% 와 30건짜리 100% 를 같은 무게로 읽으면 안 되니까요

데이터가 없어 못 그린 장은 결과 dict 에 넣지 않고, 실행 끝에 어느 장이 빠졌는지 이름을 찍어줍니다.
분석이 0건인 경우처럼 **이유를 적을 수 있을 때는** 빈 축 대신 그 문장을 적은 그림을 남깁니다.
차트가 통째로 사라지면 리포트를 보는 사람이 빠뜨린 건지 없는 건지 구분할 수 없습니다.

### `bridge.py` — 외부 호출 창구 (162줄)

`main.py` 는 `source/` 나 `prompt/` 를 직접 import 하지 않습니다. 전부 이 파일을 거칩니다.
의존 방향은 **A → B, A → C 한 방향**이고, B/C 는 A를 import 하지 않습니다. 그래야 두 사람이 자기 폴더만으로 테스트할 수 있습니다.

초기에는 어댑터가 539줄이었는데 C와 합의해 계약을 맞추면서 162줄로 줄었습니다. 사라진 것들:

| 없앤 것 | 이유 |
|---|---|
| id 매핑 73줄 | C가 id 를 그대로 들고 다니게 됨 |
| 부분 실패 흡수 | C가 `failed_ids` 를 함께 반환 |
| stats 평면화 77줄 | 리포트 형식은 리포트를 만드는 쪽이 정함 |
| 배치 나누기 | C가 직접 배치로 부름 |
| mock 분기 | 연결 완료 |

**변환 코드가 줄어든 만큼 계약이 맞춰진 것**이라 보고 있습니다.

### `interfaces.py` — 계약 검증기 (326줄)

실행되는 문서입니다. `INTERFACE.md` 와 어긋나면 코드가 기준입니다.
`validate_stats` / `validate_analysis_output` / `validate_insights` / `validate_chart_paths` 네 개.

`validate_chart_paths` 는 경로만 돌려주고 저장에 실패한 경우를 리포트 단계 **전에** 잡습니다. 파일 존재까지 확인합니다.
필수로 보는 것은 3장뿐입니다 — 나머지까지 필수로 걸면 데이터가 부족한 날 `dashboard` 가 통째로 멈춰서 통계도 리포트도 못 보게 됩니다.

### `exporter.py` — 내보내기 (231줄)

csv / jsonl / xlsx 세 형식. 두 가지를 신경 썼습니다.

- **CSV 에 BOM 을 붙입니다.** utf-8 로 쓰면 Excel 이 cp949 로 읽어 한글이 전부 깨집니다
- **openpyxl 이 없으면 xlsx 요청이 csv 로 떨어집니다.** 그때 요청 경로가 아니라 **실제 저장된 경로**를 반환합니다

---

## 6. 데이터 흐름

```
CSV
 └─ B importer.import_reviews()      → source/raw/reviews.jsonl
     └─ A save_raw()                 → SQLite raw_reviews
 └─ B cleaner.clean_reviews()        → source/clean/reviews.jsonl
     └─ A save_clean()               → SQLite reviews  (해시 중복 판정)
         └─ C analyze_reviews()      → sentiment / confidence
             └─ A validate → save_sentiment_results()
                 └─ A calculate_stats()
                     ├─ A generate_charts()          → PNG 7장
                     └─ C generate_markdown_report() → chart/output/report_*.md
```

`dashboard` 는 차트 절대경로를 **리포트 파일 기준 상대경로**로 바꿔 C에게 넘깁니다.
절대경로를 그대로 넣으면 만든 사람 PC 에서만 이미지가 보이고 GitHub 에서는 전부 깨집니다.
Windows 의 `\` 도 `/` 로 치환합니다.

---

## 7. 검증

```bash
python chart/check_contract.py           # 계약 자가 점검 (B/C/A 전체)
python chart/tests/test_integration.py   # 통합 테스트 29개
```

**둘 다 API 키 없이 돕니다.** 분석 결과가 필요한 구간은 각 파일 안의 대역이 대신합니다.
테스트 한 번에 과금되면 아무도 테스트를 안 돌리게 되기 때문입니다.

### 자가 점검의 네 가지 표시

| 표시 | 뜻 |
|---|---|
| `[OK]` | 약속대로 동작 |
| `[FAIL]` | **만들었는데 약속과 다름.** 이것만 고치면 됨 |
| `[SKIP]` | 아직 안 만듦. 실패로 치지 않음 |
| `[TODO]` | 약속 위반이 아니라 **새로 부탁하는 것** |

`[TODO]` 를 `[FAIL]` 과 섞지 않은 이유가 있습니다.
전달 조건이 "자기 영역에 FAIL 없을 것" 이라, 새 요청이 빨간불로 뜨면 다 만든 사람도 빨간불이 되고
그러면 진짜 `[FAIL]` 을 보고도 아무도 안 움직이게 됩니다.

### 2026-08-13 결과

| 영역 | 결과 |
|---|---|
| B (세인) | `[OK]` 2 / 2 |
| C (민규) | `[OK]` 4 · `[FAIL]` 1 · `[TODO]` 3 |
| **A (영휘)** | **`[OK]` 8 / 8** |
| 통합 테스트 | 29개 통과 (키가 필요한 2개는 skip) |
| end-to-end | 빈 DB → import → analyze → stats → dashboard → export 전 구간 정상 |

실제 데이터 99건 기준 산출값:

```
분석 완료 99건 (100.0%)   평균 별점 3.65   평균 확신도 0.91
긍정 57 (57.6%) · 중립 38 (38.4%) · 부정 4 (4.0%)
별점-감정 일치도 81.8%    데이터 완전성 100.0%
차트 7/7장 · 리포트 생성 완료
```

### 통합 테스트가 보는 것

계약이 깨지는 지점만 봅니다. B/C 의 기능 정확도는 각자 테스트가 있습니다.

- B의 clean 레코드 5개 필드가 DB 왕복에서 살아남는가 (`skin_type` 이 조용히 버려지지 않는가)
- 해시가 공백·대소문자를 정규화하는가 / 제품이 다르면 다른 리뷰로 잡는가
- C가 흔들려도 **id 가 사라지지 않는가** — `results` 아니면 `failed_ids` 중 한쪽에는 반드시 있어야 함
- 배치가 실패하면 반으로 쪼개 재시도해서 앞의 결과를 버리지 않는가
- `payload` 에 `rating` 이 섞이지 않는가
- `chart_data` 의 칸 이름과 `CHART_ORDER` 가 어긋나지 않는가
- KPI 가 `summary` 를 다시 세지 않고 옮겨오기만 하는가
- 그룹별 차트의 계열 길이가 labels 와 맞는가 (`zip` 이 조용히 자르지 않는가)
- 선택 필드가 전부 `None` 인 리뷰를 export 3형식이 처리하는가
- A가 B/C 폴더에 파일을 만들지 않았는가
- 걷어낸 모듈(`mock_ai.py` · `hashing.py`)이 되살아나지 않았는가

---

## 8. 남은 항목

A 영역은 `[FAIL]` 이 없습니다. 아래는 C(민규)에게 넘긴 요청이고, 자세한 내용과 목표 마크다운은
[C_인터페이스.md](../C_인터페이스.md) 6번에 있습니다.

| 구분 | 내용 |
|---|---|
| `[FAIL]` | `validate_insight_result()` 가 `improvements` 를 2개 이상 요구 — 계약에 없는 조건. 모델이 1개만 준 날 `extract` 가 통째로 실패 |
| `[TODO]` | 리포트가 `chart_paths` 의 키를 버리고 `차트 1~7` 로 번호를 매김 |
| `[TODO]` | 리포트가 `stats["meta"]` 를 안 읽어 생성 시각·필터 범위가 없음 |
| `[TODO]` | `product_name` 이 `None` 인 리뷰에서 문자열 `"None"` 이 찍힘 |

**A쪽에서 더 넘길 값은 없습니다.** 셋 다 이미 넘어가고 있고, 쓸지 말지가 리포트를 만드는 쪽의 몫입니다.

운영상 알아두면 좋은 것:

- Gemini 가 503(과부하)을 내면 C가 배치를 반으로 쪼개 재시도합니다. **그 사이에 대기가 없어서** 스파이크가 지나가기 전에 다시 부릅니다. 실제로 99건 시도 중 뒤쪽 49건이 이렇게 실패했고, `analyze --unanalyzed --limit 25` 로 나눠 돌려 복구했습니다
- `dashboard` 는 가장 최근 `extract` 결과 하나만 씁니다. 필터를 바꿔 리포트를 뽑을 때는 같은 조건으로 `extract` 를 먼저 다시 돌려야 인사이트와 통계의 범위가 맞습니다
