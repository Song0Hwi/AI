# 국내 여행 추천 API 연동 프로그램

LLM API(Google Gemini)와 지도/장소 검색 API(Kakao Local 또는 Naver 지역검색)를 조합해서,
입력한 여행 날짜에 맞는 **국내 여행 리포트(Markdown)** 를 자동으로 만들어 주는 CLI 프로그램입니다.

## 1. 프로그램 개요

날짜 하나만 입력하면 아래 3단계가 순서대로 실행됩니다.

| 단계 | 사용 API | 하는 일 | HTTP |
|---|---|---|---|
| [1/3] | Gemini `generateContent` | 해당 시기에 좋은 국내 도시 + 날씨 + 행사/축제를 **JSON** 으로 생성 | `POST` |
| [2/3] | Kakao Local / Naver Local | 1단계에서 받은 도시명으로 **맛집 검색** | `GET` |
| [3/3] | Gemini `generateContent` | 1·2단계 결과를 합쳐 **최종 여행 리포트(Markdown)** 작성 | `POST` |

핵심은 "1단계 LLM 출력을 JSON으로 구조화해서 → 2단계 장소 검색 API의 입력으로 넘기는" 연결 흐름입니다.

```
-date 2026-03-15
        │
        ▼
  [LLM] {"recommended_city": "제주", "weather": ..., "events": [...], "reason": ...}
        │  recommended_city
        ▼
  [지도 API] "제주 맛집" 검색 → [{name, address, category, url, lat, lng}, ...]
        │
        ▼
  [LLM] 최종 리포트(Markdown) → results/2026-03-15_travel_plan.md
```

### 파일 구성

```
travel_planner/
├── travel_planner.py    # 메인 프로그램 (CLI)
├── requirements.txt     # 의존 패키지
├── .env.example         # 환경변수 템플릿 (실제 키 없음)
├── .gitignore           # .env, results/ 제외
├── README.md
└── results/             # 실행 결과가 저장되는 폴더 (자동 생성)
    ├── 2026-03-15_travel_raw.json   # 원본 데이터 (1차 추천 + 맛집 + errors)
    └── 2026-03-15_travel_plan.md    # 최종 여행 리포트
```

## 2. 실행 방법

### 2.1 준비

Python 3.10 이상이 필요합니다.

```bash
pip install -r requirements.txt
```

### 2.2 실행

```bash
python travel_planner.py -date "2026-03-15"
```

실행 화면 예시:

```text
여행 날짜: 2026-03-15 / LLM 모델: gemini-3.6-flash
[1/3] 1차 추천 생성 중(LLM)...
  - recommended_city: "제주"
[2/3] 맛집 검색 중(지도/장소 API)...
  - 지도 API: kakao
  - 제주: 맛집 5곳 검색 완료
[3/3] 최종 리포트 생성 중(LLM)...
  - 리포트 생성 완료

완료! .../results/2026-03-15_travel_plan.md 를 확인하세요.
      원본 데이터: .../results/2026-03-15_travel_raw.json
```

### 2.3 옵션

| 옵션 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `-date` / `--date` | **필수** | - | 여행 날짜 `YYYY-MM-DD`. 형식이 틀리면 사용법을 출력하고 종료합니다. |
| `--cities N` | 선택 | `1` | 추천받을 도시 수(1~3). 2 이상이면 도시별로 맛집을 각각 검색합니다. |
| `--places N` | 선택 | `5` | 도시당 맛집 검색 개수(1~15). |
| `--map-provider` | 선택 | `auto` | `auto` / `kakao` / `naver`. `auto` 는 설정된 키를 보고 자동 선택합니다. |
| `--no-cache` | 선택 | 꺼짐 | 같은 날짜의 원본 JSON 이 있어도 무시하고 API 를 다시 호출합니다. |

```bash
# 여러 지역 추천 + 도시별 맛집 3곳씩
python travel_planner.py -date "2026-03-15" --cities 2 --places 3

# 네이버 지역검색으로 강제 지정
python travel_planner.py -date "2026-05-01" --map-provider naver
```

> **캐시 동작**: 같은 `-date` 로 다시 실행하면 이미 저장된 원본 JSON 을 재사용해
> [1/3]·[2/3] API 호출을 건너뛰고 리포트만 다시 생성합니다. 외부 API 비용/속도를 아끼기 위한 장치이며,
> 새로 호출하려면 `--no-cache` 를 붙입니다.

## 3. API 키 설정 방법

**키 값은 코드에 절대 작성하지 않습니다.** 환경변수 또는 `.env` 파일에서만 읽습니다.

### 3.1 필요한 키

| 환경변수 | 필수 여부 | 발급처 |
|---|---|---|
| `GEMINI_API_KEY` | **필수** | https://aistudio.google.com/apikey |
| `GEMINI_MODEL` | 선택 | 기본값 `gemini-3.6-flash`. 다른 모델을 쓰고 싶을 때만 지정 |
| `KAKAO_REST_API_KEY` | 둘 중 하나 | https://developers.kakao.com → 내 애플리케이션 → REST API 키 |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | 둘 중 하나 | https://developers.naver.com/apps (검색 API 등록) |

> 지도 API 키가 하나도 없어도 프로그램은 멈추지 않습니다.
> 맛집 섹션만 "데이터 없음"으로 표기하고 리포트 생성을 끝까지 진행합니다.

### 3.2 방법 A — `.env` 파일 (권장)

`.env.example` 을 복사해서 `.env` 를 만들고 값만 채웁니다.

```bash
cp .env.example .env     # Windows: copy .env.example .env
```

```dotenv
GEMINI_API_KEY=여기에_발급받은_키
KAKAO_REST_API_KEY=여기에_발급받은_키
```

`.env` 는 `.gitignore` 에 등록되어 있어 커밋되지 않습니다.

### 3.3 방법 B — 환경변수

Windows PowerShell (현재 세션에만 적용):

```powershell
$env:GEMINI_API_KEY="YOUR_KEY"
```

Windows 사용자 환경변수로 영구 등록:

```powershell
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "YOUR_KEY", "User")
```

macOS / Linux (현재 세션에만 적용):

```bash
export GEMINI_API_KEY="YOUR_KEY"
```

`GEMINI_API_KEY` 가 없으면 프로그램은 **즉시 종료**하면서 위 설정 방법을 안내합니다(종료 코드 `2`).

## 4. 결과물 확인 방법

실행이 끝나면 `results/` 폴더에 파일 2개가 생성됩니다.

### 4.1 원본 데이터 — `results/{날짜}_travel_raw.json`

1차 추천 JSON, 맛집 검색 결과, 오류 요약이 모두 들어 있습니다.

```json
{
  "date": "2026-03-15",
  "llm_model": "gemini-3.6-flash",
  "place_provider": "kakao",
  "recommendation": {
    "recommended_city": "제주",
    "weather": "3월 중순의 제주는 포근한 봄기운이 ...",
    "events": ["휴애리 봄 유채꽃 축제", "한림공원 튤립축제"],
    "reason": "3월 중순은 제주 전역에 노란 유채꽃과 ...",
    "recommended_cities": [{ "city": "제주", "weather": "...", "events": ["..."], "reason": "..." }]
  },
  "restaurants": {
    "제주": [
      {
        "name": "○○흑돼지",
        "address": "제주시 ○○로 1",
        "category": "음식점 > 한식 > 육류,고기",
        "url": "http://place.map.kakao.com/...",
        "x": 126.4784, "y": 33.489, "lng": 126.4784, "lat": 33.489
      }
    ]
  },
  "restaurant_count": 5,
  "errors": []
}
```

### 4.2 최종 리포트 — `results/{날짜}_travel_plan.md`

아래 섹션이 포함된 Markdown 리포트입니다. VS Code 미리보기나 GitHub 에서 바로 읽을 수 있습니다.

```markdown
# 2026-03-15 국내 여행 추천 리포트
## 추천 지역
## 추천 이유
## 날씨 요약
## 행사/축제
## 맛집 추천
## 1일 일정 제안
## 오류 요약(errors)
```

## 5. 오류 처리 정책

모든 외부 호출은 `try-except` 로 감싸고, 발생한 오류는 `errors` 리스트에 모아
원본 JSON과 리포트의 `## 오류 요약(errors)` 섹션에 남깁니다. (오류가 없으면 빈 리스트)

| 상황 | 기록되는 `type` | 프로그램 동작 |
|---|---|---|
| `GEMINI_API_KEY` 미설정 | - | **즉시 종료** + 설정 방법 안내 (exit 2) |
| 지도 API 키 미설정 | `CONFIG_ERROR` | 맛집 "데이터 없음" 처리 후 리포트 생성 **계속** |
| 지도 API 401/403 | `AUTH_ERROR` | 맛집 "데이터 없음" 처리 후 **계속** (키/헤더명/도메인 설정 점검 안내) |
| 호출 한도 초과(429) | `QUOTA_ERROR` | 맛집 "데이터 없음" 처리 후 **계속** |
| 네트워크 실패/타임아웃 | `NETWORK_ERROR` | 맛집 "데이터 없음" 처리 후 **계속** |
| 검색 결과 0건 | `EMPTY_RESULT` | `- 데이터 없음 (장소 검색 결과 0건)` 으로 표기 후 **계속** |
| LLM JSON 파싱 실패 | `PARSE_ERROR` | "필수 키만 다시 JSON으로 출력" 프롬프트로 **재요청 1회만** (무한 재시도 금지) |
| 리포트 생성 LLM 실패 | (해당 타입) | 로컬 템플릿으로 리포트를 대신 생성하여 결과물은 항상 남김 |
| 1차 추천 완전 실패 | (해당 타입) | 기준 데이터가 없으므로 오류 요약만 JSON에 저장하고 종료 (exit 1) |

오류 요약 예시:

```json
{
  "errors": [
    { "step": "place_search", "type": "AUTH_ERROR", "message": "HTTP 401 인증 실패 ..." }
  ]
}
```

## 6. API 키 유출 주의 사항 (중요)

- **코드에 키를 직접 쓰지 않습니다.** 키는 `os.getenv()` 로 환경변수/`.env` 에서만 읽습니다.
- **`.env` 는 커밋하지 않습니다.** `.gitignore` 에 `.env` 가 등록되어 있습니다.
  공유·제출용으로는 값이 비어 있는 `.env.example` 만 포함합니다.
- **로그와 결과 파일에도 키가 남지 않습니다.** 오류 메시지에 키 문자열이 섞여 들어오면
  `***REDACTED***` 로 마스킹한 뒤 출력/저장합니다 (`scrub()` 함수).
- **키는 URL 쿼리스트링이 아니라 헤더로 보냅니다.** (`x-goog-api-key`, `Authorization: KakaoAK ...`,
  `X-Naver-Client-Id/Secret`) URL 에 담으면 프록시·서버 접근 로그·브라우저 히스토리에 그대로 기록됩니다.
- 결과물(`results/`)을 제출/커밋할 때는 파일 안에 키가 들어가 있지 않은지 한 번 더 확인하세요.
  (프로그램은 키를 결과 파일에 기록하지 않습니다.)
- 키가 노출된 것 같으면 **즉시 발급처에서 폐기(revoke) 후 재발급**하세요. 환경변수로 관리하면
  코드를 고치지 않고 키만 교체할 수 있습니다.

### 왜 환경변수로 관리하나요?

1. 협업/공유 시 실수로 키가 공개되는 사고를 막습니다.
2. 키를 교체해도 코드를 수정할 필요가 없습니다(운영/배포에 유리).
3. 과금·쿼터가 걸린 서비스에서 키 유출로 인한 요금 사고를 예방합니다.

## 7. 참고 — REST API 요청/응답 구조

| 구분 | 이번 프로그램에서 | 설명 |
|---|---|---|
| `GET` | 맛집 검색 (Kakao/Naver) | 조회 요청. 조건을 **URL 쿼리스트링**(`?query=제주 맛집&size=5`)에 담음 |
| `POST` | LLM 호출 (Gemini) | 생성 요청. 프롬프트 같은 **긴 데이터를 요청 본문(JSON body)** 에 담음 |

공통적으로 **인증 정보는 헤더**에 싣고, 응답은 **JSON 본문 + HTTP 상태 코드**로 받습니다.
상태 코드는 `200`(성공), `401/403`(인증 실패), `429`(호출 한도 초과), `5xx`(서버 오류)로 나눠 처리했습니다.
