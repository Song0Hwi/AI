# 코드 설명 자료 — 국내 여행 추천 API 연동

평가 항목 1~4의 질문에 하나씩 답하는 문서입니다. 모든 줄 번호는 `travel_planner.py` 기준입니다.

## 전체 구조 한눈에

```
main()  :694
 ├─ parse_args()        :630   CLI 파싱 + 날짜 검증
 ├─ load_api_keys()     :662   .env/환경변수에서 키 읽기, 없으면 즉시 종료
 ├─ [캐시 확인]          :709   같은 날짜 원본 JSON 있으면 1·2단계 건너뜀
 ├─ [1/3] fetch_recommendation()  :343  ─ GeminiClient.generate()   :205
 │                                      ─ extract_json_object()     :136
 │                                      ─ normalize_recommendation():288
 ├─ [2/3] search_restaurants()    :470  ─ resolve_place_provider()  :376
 │                                      ─ search_places_kakao()     :397
 │                                      ─ search_places_naver()     :431
 ├─ [3/3] generate_report()       :593  ─ build_fallback_report()   :539 (실패 시)
 └─ 저장                                 ─ append_error_section()   :615
```

공통 기반: `ApiError` :60 · `ErrorCollector` :86 · `http_request()` :109 · `scrub()` :73

---

# 항목 1 — 기능 요구사항

## 1-1. `-date` 옵션 실행 + 날짜 형식 오류 시 사용법 출력 후 종료

CLI는 `argparse`로 만들었습니다 (`parse_args()` :630).

```python
parser.add_argument("-date", "--date", dest="date", required=True,
                    metavar="YYYY-MM-DD", help="여행 날짜 (필수, 형식: YYYY-MM-DD)")
```

`-date`와 `--date`를 같은 `dest="date"`에 묶어서 둘 다 받습니다. `required=True`라 빠지면 argparse가 usage를 출력하고 종료합니다.

형식 검증은 argparse가 못 하므로 파싱 직후에 직접 합니다 (:649).

```python
try:
    datetime.strptime(args.date, "%Y-%m-%d")
except ValueError:
    parser.error(f'날짜 형식이 올바르지 않습니다: "{args.date}" (예: -date "2026-03-15")')
```

**`parser.error()`를 쓴 이유**: `sys.exit()`로 직접 끝내면 usage가 안 나옵니다. `parser.error()`는 usage + 에러 메시지를 stderr로 출력하고 종료 코드 2로 끝냅니다 — "사용법을 출력하고 종료한다"는 요구사항을 한 줄로 만족합니다.

`strptime`을 쓰면 `2026-13-45`처럼 **존재하지 않는 날짜**도 걸러집니다. 정규식(`\d{4}-\d{2}-\d{2}`)만 썼다면 통과했을 값입니다.

```text
$ python travel_planner.py -date "2026-99-99"
usage: travel_planner.py [-h] -date YYYY-MM-DD [--cities N] ...
travel_planner.py: error: 날짜 형식이 올바르지 않습니다: "2026-99-99" (예: -date "2026-03-15")
```

## 1-2. 1차 LLM 응답이 JSON으로 파싱되고 필수 키 4개가 모두 존재하는가

3단 방어입니다.

**① 생성 단계에서 강제** — `GeminiClient.generate()` :211

```python
if json_mode:
    payload["generationConfig"]["responseMimeType"] = "application/json"
```

Gemini API의 구조화 출력 기능입니다. 모델이 `"네, 알겠습니다"` 같은 말이나 코드펜스를 붙이지 못합니다.

**② 파싱 단계에서 복구** — `extract_json_object()` :136
코드펜스 제거 → `json.loads()` 시도 → 실패하면 첫 `{`부터 **중괄호 깊이를 세면서** 짝이 맞는 `}`를 찾아 그 구간만 다시 파싱합니다. 문자열 안의 `{`, 이스케이프(`\"`)를 건너뛰므로 `{"a": "b{c"}` 같은 값도 안전합니다.

**③ 검증 단계에서 확인** — `normalize_recommendation()` :288
필수 키가 없으면 `ApiError("PARSE_ERROR", ...)`를 던집니다.

```python
if not top_city:
    raise ApiError("PARSE_ERROR", "필수 키 recommended_city 가 없습니다.")
...
if not weather or not reason:
    raise ApiError("PARSE_ERROR", "필수 키 weather / reason 값이 비어 있습니다.")
```

## 1-3. `recommended_city`를 지도 API 입력으로 사용하고, 실패해도 다음 단계로 가는가

`main()` :754에서 1차 결과를 꺼내 2단계로 넘깁니다.

```python
city_names = [c["city"] for c in recommendation["recommended_cities"]]
restaurants = search_restaurants(city_names, provider, provider_note, args.places, errors)
```

`search_places_kakao()` :399에서 검색어가 됩니다.

```python
query = f"{city} 맛집"
```

**실패해도 계속 가는 구조**는 `search_restaurants()` :470입니다. 도시별 루프 안에서 예외를 잡고 `continue` 합니다 — 함수는 항상 `{도시: [...]}` 딕셔너리를 돌려주고, 절대 예외를 밖으로 던지지 않습니다.

```python
for city in cities:
    try:
        places = searcher(city, size)
    except ApiError as exc:
        errors.add("place_search", exc.error_type, f"[{city}] {exc.message}")
        continue                      # 다음 도시로, 리포트 생성은 계속
    except Exception as exc:          # 예상 못한 오류로도 중단되지 않게
        errors.add("place_search", "UNKNOWN_ERROR", f"[{city}] {exc}")
        continue
    if not places:
        errors.add("place_search", "EMPTY_RESULT", f"0 results for query='{query_of(city)}'")
        continue
    result[city] = places
```

실측: 카카오 키 없이 실행 → `CONFIG_ERROR` 기록 후 리포트 정상 생성. 키 넣고 실행 → 제주 맛집 5곳 검색 완료, `errors: 0`.

## 1-4. `results/`에 원본 JSON과 최종 Markdown이 저장되는가

`main()` :699에서 폴더를 만들고 날짜로 파일명을 짓습니다.

```python
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
raw_path    = RESULTS_DIR / f"{args.date}_travel_raw.json"
report_path = RESULTS_DIR / f"{args.date}_travel_plan.md"
```

`RESULTS_DIR`는 `BASE_DIR / "results"` (:40), `BASE_DIR`는 `Path(__file__).resolve().parent` (:39) — **스크립트 파일 위치 기준**입니다. 어느 폴더에서 실행해도 결과가 같은 곳에 쌓입니다.

원본 JSON에는 명세가 요구한 3가지가 모두 들어갑니다 (:764).

```python
raw_payload = {
    "date": args.date,
    "generated_at": ..., "llm_provider": ..., "llm_model": ..., "place_provider": ...,
    "recommendation": recommendation,   # ① 1차 추천 JSON(파싱 결과)
    "restaurants": restaurants,         # ② 맛집 검색 결과 (0건 가능)
    "restaurant_count": total_places,
    "errors": errors.as_list(),         # ③ 오류 요약 (빈 배열 가능)
}
```

## 1-5. 코드/결과물/README에 API 키가 직접 포함되어 있지 않은가

- 코드에 키 리터럴 없음 — `os.getenv()`로만 읽습니다 (:673).
- `.env`는 `.gitignore`에 등록. 배포용 `.env.example`은 값이 비어 있습니다.
- README에는 발급 링크와 설정 방법만, 실제 값 없음.
- 추가로 **로그·결과 파일에서도 키를 지웁니다** — `scrub()` :73.

```python
def scrub(text: Any) -> str:
    safe = str(text)
    for secret in _SECRETS:
        if secret and secret in safe:
            safe = safe.replace(secret, "***REDACTED***")
    return safe if len(safe) <= 500 else safe[:500] + " ...(생략)"
```

`_SECRETS`는 `load_api_keys()` :667에서 실제 키 값들로 채워지고, 모든 로그 출력(`log()` :82)과 오류 기록(`ErrorCollector.add()` :92)이 이 함수를 거칩니다.

> 왜 필요한가: 일부 API는 **오류 응답 본문에 요청한 키를 그대로 되돌려 줍니다.** 그걸 그대로 `errors`에 넣으면 제출용 JSON에 키가 박힙니다. 실제로 403 응답에 키를 넣어 테스트해 `***REDACTED***`로 치환되는 것을 확인했습니다.

---

# 항목 2 — 구조와 설계

## 2-1. "1차 추천 → 맛집 검색 → 리포트" 흐름을 어떻게 분리했는가

**계층으로 나눴습니다.** 각 단계는 자기 일만 하고, 조립은 `main()` 한 곳에서만 합니다.

| 계층 | 함수 | 책임 | 모르는 것 |
|---|---|---|---|
| 조립 | `main()` :694 | 순서 제어, 파일 저장 | HTTP 세부사항 |
| 단계 | `fetch_recommendation()` :343<br>`search_restaurants()` :470<br>`generate_report()` :593 | 한 단계의 로직·재시도·오류 수집 | 다른 단계의 존재 |
| 제공자 | `search_places_kakao()` :397<br>`search_places_naver()` :431<br>`GeminiClient` :197 | 특정 API의 요청 형식·응답 필드 | 전체 흐름 |
| 공통 | `http_request()` :109 | 네트워크·상태코드 → `ApiError` 변환 | 어느 API인지 |

**데이터로만 연결됩니다.** 단계 간 전달은 전부 평범한 `dict`/`list`입니다.

```
str(날짜) → fetch_recommendation → dict(추천)
dict(추천).recommended_cities → search_restaurants → dict(도시별 맛집)
dict(추천) + dict(맛집) → generate_report → str(마크다운)
```

그래서 각 함수를 단독으로 테스트할 수 있습니다. 실제로 `FlakyLLM` 같은 가짜 객체를 넣어 재시도 로직만 따로 검증했습니다.

## 2-2. 1차 JSON 스키마를 코드에서 어떻게 검증했는가

`normalize_recommendation()` :288 한 곳에 모았습니다. **"검증(reject)"과 "정규화(fix)"를 구분한 것**이 핵심입니다.

**고칠 수 있으면 고칩니다.**

```python
def as_event_list(value: Any) -> list[str]:          # :291
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()][:3]
    if isinstance(value, str) and value.strip():      # 문자열로 오면 1개짜리 배열로
        return [value.strip()]
    return []                                         # None 이면 빈 배열
```

- `events`가 문자열이면 → 배열로 감쌈
- `events`가 4개 이상이면 → `[:3]`으로 자름 (명세: 1~3개)
- `recommended_cities`가 없으면 → 최상위 값으로 1개짜리 배열 생성 (:326)
- 최상위 `weather`가 비었으면 → `cities[0]`에서 채움 (:331)

**못 고치면 거부합니다.** 도시명·`weather`·`reason`이 없으면 `ApiError("PARSE_ERROR")` → 재시도 로직으로 넘어갑니다.

**타입 확인 방식**: `isinstance()`로 리스트/문자열/딕셔너리를 구분하고, 모든 스칼라 값은 `str(...).strip()`으로 강제 변환합니다. 모델이 숫자나 `None`을 보내도 터지지 않습니다.

> 이 함수 하나만 통과하면 이후 코드는 "`recommended_cities`는 반드시 `city/weather/events/reason`을 가진 dict의 리스트"라고 **가정하고** 쓸 수 있습니다. 검증을 입구 한 곳에 몰아넣는 이유입니다.

## 2-3. 지도 API 제공자를 바꿔도 변경 범위가 최소화되게 한 구조

**세 가지 장치**를 썼습니다.

**① 공통 출력 스키마.** 카카오·네이버 함수가 서로 다른 응답을 **같은 형태의 dict**로 변환합니다.

```python
{"name", "address", "category", "phone", "url", "x", "y", "lng", "lat", "provider", "query"}
```

| 카카오 | 네이버 | → 공통 |
|---|---|---|
| `place_name` | `title` (`<b>` 태그 포함) | `name` (`strip_tags()` :187로 태그 제거) |
| `road_address_name` ‖ `address_name` | `roadAddress` ‖ `address` | `address` (도로명 우선) |
| `x`, `y` (문자열 좌표) | `mapx`, `mapy` (정수 ×10⁷) | `lng`, `lat` (`float` 변환) |
| `place_url` | `link` | `url` |

**② 같은 시그니처.** 두 함수 모두 `(city: str, size: int) -> list[dict]`입니다. 그래서 호출부에서 **함수 자체를 값처럼 골라** 쓸 수 있습니다 (:480).

```python
searcher = search_places_kakao if provider == "kakao" else search_places_naver
for city in cities:
    places = searcher(city, size)     # 어느 쪽인지 신경 쓰지 않음
```

**③ 선택 로직 분리.** `resolve_place_provider()` :376이 "어떤 키가 있는가"만 판단합니다.

```python
if requested == "kakao": ...
if requested == "naver": ...
if kakao:      return "kakao", None      # auto: 있는 키로 자동 선택
if naver_id and naver_secret: return "naver", None
return None, "지도/장소 API 키가 없습니다. ..."
```

**결과**: 세 번째 제공자(예: 구글 Places)를 추가하려면 → ⓐ `search_places_google()` 함수 1개 추가, ⓑ `resolve_place_provider()`에 분기 1줄, ⓒ `--map-provider` choices에 이름 1개. **`main()`·리포트·저장 코드는 한 줄도 안 바뀝니다.**

## 2-4. 오류를 `errors` 목록으로 누적하고 리포트에 반영하는 방식

**`ErrorCollector` 클래스** :86가 단일 창구입니다.

```python
def add(self, step: str, error_type: str, message: str) -> None:
    item = {"step": step, "type": error_type, "message": scrub(message)}
    self.items.append(item)
    log("  - 오류: [{}/{}] {}".format(step, error_type, item["message"]))
```

한 번 호출로 **① 화면 출력 ② 목록 누적 ③ 키 마스킹**이 동시에 됩니다. 호출부는 `errors.add(...)` 한 줄만 쓰면 됩니다.

`step`(어느 단계) / `type`(무슨 종류) / `message`(무슨 일)로 고정해서, 나중에 `type`으로 집계하거나 필터링할 수 있습니다.

**리포트 반영은 LLM이 아니라 코드가 합니다** — `append_error_section()` :615.

```python
def append_error_section(report: str, errors: list[dict[str, str]]) -> str:
    lines = [report.rstrip(), "", "## 오류 요약(errors)", ""]
    if not errors:
        lines.append("- 없음")
    else:
        for err in errors:
            lines.append(f"- `{err['step']}` / `{err['type']}`: {err['message']}")
    return "\n".join(lines) + "\n"
```

리포트 프롬프트(:535)에는 `'오류 요약' 섹션은 프로그램이 따로 붙이므로 작성하지 마세요`라고 명시했습니다. **오류 기록은 사실(fact)이므로 모델이 요약하거나 윤색하면 안 됩니다.** LLM 호출이 실패한 경우에도 오류 섹션은 반드시 남아야 하니, 구조상으로도 코드가 붙이는 게 맞습니다.

**중복 제거** — `as_list()` :97. 캐시에서 이어받은 오류가 재실행마다 쌓이지 않도록 `(step, type, message)` 조합으로 중복을 걸러 냅니다.

---

# 항목 3 — API 기초 개념

## 3-1. GET / POST를 어디에 왜 썼는가

| | 사용처 | 코드 | 조건을 어디에 |
|---|---|---|---|
| **GET** | 맛집 검색 (카카오/네이버) | :404, :438 | URL 쿼리스트링 |
| **POST** | LLM 호출 (Gemini) | :215 | 요청 본문(JSON body) |

**GET을 쓴 이유**: 서버 상태를 바꾸지 않는 **조회**이고, 조건이 `query=제주 맛집&size=5&sort=accuracy` 정도로 짧습니다. 같은 URL을 다시 호출하면 같은 결과가 나오므로(멱등) 캐싱·재시도가 안전합니다.

**POST를 쓴 이유**: 프롬프트가 수백~수천 자입니다. URL 길이 제한(실무상 2,000자 내외)을 넘기고, 긴 한글 텍스트는 인코딩하면 3~4배로 부풀어 더 심해집니다. 게다가 URL은 서버 접근 로그·프록시·브라우저 히스토리에 **평문으로 남으므로** 프롬프트를 거기 실으면 안 됩니다.

**공통점**: 인증은 둘 다 **헤더**로 보냅니다. 쿼리스트링에 키를 넣으면 로그에 그대로 찍힙니다.

```python
"x-goog-api-key": self.api_key                              # Gemini   :221
"Authorization": f"KakaoAK {os.environ[...]}"               # Kakao    :403
"X-Naver-Client-Id" / "X-Naver-Client-Secret"               # Naver    :438
```

**URL은 직접 조립하지 않습니다.** `params=` 딕셔너리로 넘기면 `requests`가 인코딩합니다.

```python
params={"query": query, "size": size, "sort": "accuracy"}
# → ?query=%EC%A0%9C%EC%A3%BC+%EB%A7%9B%EC%A7%91&size=5&sort=accuracy
```

문자열로 `"...?query=" + city + " 맛집"` 하면 공백 때문에 400이 납니다.

## 3-2. LLM 출력을 "자유 텍스트"가 아니라 "JSON"으로 강제한 이유와 장점

**이유는 한 줄입니다 — 다음 단계의 입력이기 때문입니다.**

```
"제주는 3월에 좋습니다..."  → 여기서 도시명만 뽑을 방법이 없음
{"recommended_city": "제주"} → data["recommended_city"] 한 줄로 끝
```

자유 텍스트를 받으면 정규식이나 "LLM에게 다시 물어보기"로 파싱해야 하는데, 표현이 매번 달라져서 깨집니다.

**장점 4가지**

1. **기계 판독 가능** — 키로 직접 접근. 파싱 코드가 단순해집니다.
2. **검증 가능** — 필수 키 존재·타입을 코드로 확인할 수 있습니다 (`normalize_recommendation()`). 자유 텍스트는 "잘 왔는지"를 판정할 기준 자체가 없습니다.
3. **실패가 명확** — 깨지면 `PARSE_ERROR`로 즉시 드러나고 재시도 트리거가 됩니다. 자유 텍스트는 조용히 잘못된 값을 넘겨 다음 단계에서 이상하게 터집니다.
4. **계약(contract)이 됨** — 스키마가 문서 역할을 해서, 모델·프롬프트를 바꿔도 뒷단 코드는 그대로입니다.

**강제 방법은 2중입니다.** API 기능(`responseMimeType: "application/json"` :213)과 프롬프트 지시(:256)를 함께 씁니다.

> 아래 JSON 스키마를 정확히 지켜서 JSON "만" 출력하세요. 설명 문장, 코드펜스, 주석을 절대 붙이지 마세요.

API 기능만 믿지 않는 이유는, 모델이 JSON 형식은 지켜도 **키 이름을 마음대로 바꿀 수 있기** 때문입니다. 스키마를 프롬프트에 그대로 써 주면 키 이름까지 맞춰집니다.

## 3-3. 401/403의 대표 원인과 디버깅 순서

`http_request()` :112에서 잡아 `AUTH_ERROR`로 변환합니다.

```python
if response.status_code in (401, 403):
    raise ApiError("AUTH_ERROR",
        f"HTTP {response.status_code} 인증 실패. API 키 / 권한 / 헤더명 / 도메인 설정을 확인하세요. ...")
```

**대표 원인**

| 원인 | 자주 나는 실수 |
|---|---|
| 키 값 오류 | 앞뒤 공백·줄바꿈, 복사 누락, 따옴표까지 값에 포함 |
| **키를 안 읽음** | `.env` 대신 `.env.example`에 적음, 파일명이 `.env.txt` |
| 헤더명 오타 | `Authorization: KakaoAK ` 뒤 공백 누락, `X-Naver-Client-Secret` 철자 |
| 키 종류 혼동 | 카카오 REST API 키 자리에 JavaScript 키/네이티브 키 |
| 플랫폼/도메인 미등록 | 카카오 콘솔에 웹 플랫폼 미등록 |
| 권한 미활성 | 네이버 앱에 "검색" API 미추가 |
| 401 vs 403 | **401 = 누구인지 모름**(키 없음/틀림) · **403 = 누군지는 알지만 권한 없음** |

**디버깅 순서 (싼 것부터)**

1. **키가 프로그램까지 도달했나** — 값이 아니라 **길이**를 찍어 봅니다. `print(len(os.getenv("KAKAO_REST_API_KEY") or ""))` → `0`이면 API 문제가 아니라 설정 문제입니다.
2. **어느 파일을 읽었나** — `.env` 위치(`BASE_DIR`), 파일명, 환경변수와의 우선순위 확인.
3. **헤더 스펠링·접두어** — 문서와 한 글자씩 대조.
4. **401인가 403인가** — 401이면 키 자체, 403이면 콘솔의 권한/도메인 설정.
5. **응답 본문 확인** — 대부분 `errorType`/`message`로 사유를 알려 줍니다. 코드가 그걸 `ApiError` 메시지에 담아 둡니다(키는 마스킹됨).
6. **최소 재현** — `curl`이나 파이썬 3줄로 API만 단독 호출. 프로그램 로직과 분리합니다.

> 실제로 이번에 겪은 사례가 2번이었습니다. 키를 `.env.example`에 적어서 프로그램이 못 읽었고, 401이 아니라 `CONFIG_ERROR`(키 자체가 없음)로 잡혔습니다.

## 3-4. API 키를 `.env`/환경변수로 관리해야 하는 이유 (보안/운영)

**보안 관점**

- **유출 차단** — 코드에 쓰면 커밋·푸시·스크린샷·화면 공유로 새어 나갑니다. 깃 히스토리에 한 번 들어가면 나중에 지워도 과거 커밋에 남습니다.
- **과금 사고 예방** — 유출된 키는 봇이 긁어가 곧바로 쓰입니다. 쿼터 소진, 요금 청구로 이어집니다.
- **권한 분리** — 개발자가 코드는 봐도 운영 키는 못 보게 할 수 있습니다.

**운영 관점**

- **환경별 분리** — 개발/스테이징/운영이 **같은 코드, 다른 키**로 돕니다. 코드에 박으면 환경마다 코드를 고쳐야 합니다.
- **키 교체(rotation)가 쉬움** — 유출 의심 시 `.env` 값만 바꾸면 끝. 코드 수정·리뷰·재배포가 필요 없습니다.
- **12-Factor App 원칙** — "설정은 환경에 저장한다". 컨테이너·CI/CD의 표준 주입 방식이라 배포 도구와 그대로 맞물립니다.

**코드에서의 실행** — `load_api_keys()` :662

```python
load_dotenv(BASE_DIR / ".env")      # .env 를 환경변수로 로드 (없어도 동작)
...
gemini_key = os.getenv("GEMINI_API_KEY")
if not gemini_key:
    print("[오류] GEMINI_API_KEY 가 설정되지 않았습니다. ... 설정 방법 (택 1) ...", file=sys.stderr)
    raise SystemExit(2)
```

- `python-dotenv`가 없어도 환경변수만으로 돌아가게 `try/except ImportError`로 감쌌습니다 (:29).
- 우선순위는 **환경변수 > `.env`** 입니다(`load_dotenv`의 기본 동작). 운영 환경에서 주입한 값이 파일에 덮이면 안 되기 때문입니다.
- 없으면 **즉시 종료 + 설정 방법 안내**(종료 코드 2). 키 없이 호출해서 401을 받고 헤매는 것보다, 시작 지점에서 명확히 끊는 게 낫습니다.

---

# 항목 4 — 예외 상황과 품질

## 4-1. LLM이 깨진 JSON을 내보낼 때의 재시도 전략

**파싱 전략(3단)** 은 1-2에 쓴 대로이고, 그래도 실패하면 **프롬프트를 바꿔 딱 1회** 재요청합니다 — `fetch_recommendation()` :343.

```python
prompts = [
    RECOMMEND_PROMPT.format(date=date_str, count=count),   # 1차: 전체 스키마
    RETRY_PROMPT.format(date=date_str, count=count),       # 2차: 필수 키만
]
for attempt, prompt in enumerate(prompts, start=1):
    try:
        text = llm.generate(prompt, json_mode=True,
                            temperature=0.7 if attempt == 1 else 0.2)
        return normalize_recommendation(extract_json_object(text), count)
    except ApiError as exc:
        last_error = exc
        if exc.error_type != "PARSE_ERROR":
            break                      # 인증/쿼터/네트워크는 재시도 무의미
        ...
raise last_error
```

**재시도 프롬프트를 어떻게 바꿨나** (`RETRY_PROMPT` :280)

| | 1차 | 2차 |
|---|---|---|
| 요구 스키마 | 전체(중첩 `recommended_cities` 포함) | **필수 키만**, 한 줄 예시 |
| 설명·조건문 | 여러 줄 | 최소화 |
| `temperature` | 0.7 | **0.2** (창의성↓, 형식 준수↑) |
| 첫 문장 | 역할 부여 | `"이전 응답이 JSON 으로 파싱되지 않았습니다."` |

**설계 의도 3가지**

1. **재시도 횟수를 리스트 길이로 고정** — `prompts` 리스트가 2개니 구조적으로 2회를 넘길 수 없습니다. 카운터 변수보다 실수 여지가 적습니다. 명세의 "무한 재시도 금지"를 코드 형태로 보장합니다.
2. **재시도할 가치가 있는 오류만 재시도** — `PARSE_ERROR`가 아니면 `break`. 401/429/네트워크 오류는 프롬프트를 바꿔도 결과가 같고, 괜히 쿼터만 더 씁니다.
3. **요구를 줄여서 성공률을 올림** — 모델이 복잡한 중첩 스키마에서 실패했다면, 같은 걸 다시 시키는 건 의미가 적습니다. **요구사항을 최소로 낮춰** 통과시키고, 부족한 필드는 `normalize_recommendation()`이 채웁니다.

검증: 첫 응답을 일부러 깨뜨린 가짜 LLM으로 테스트 → 호출 정확히 2회, 두 번째 응답으로 복구. 끝까지 깨지는 LLM → 호출 2회에서 멈추고 `PARSE_ERROR`.

## 4-2. 검색 결과 0건일 때의 표기/정책

**정책: 조용히 비우지 않고, 명시적으로 "없음"이라고 쓴다.**

빈 섹션이나 누락은 사용자가 "프로그램이 고장 났나, 원래 없나"를 구분할 수 없습니다. 문구를 고정해서 **의도된 상태**임을 드러냅니다.

**① 기록** — `search_restaurants()` :493

```python
if not places:
    errors.add("place_search", "EMPTY_RESULT", f"0 results for query='{query_of(city)}'")
```

`message`에 **실제 검색어**를 넣습니다. 나중에 "왜 0건이었나"를 추적할 유일한 단서입니다.

**② 표기 문구를 프롬프트에 고정** — `REPORT_PROMPT` :531

```text
- 맛집은 제공된 데이터에 있는 가게만 사용합니다. 절대 지어내지 마세요.
- 맛집 목록이 0건인 도시는 정확히 `- 데이터 없음 (장소 검색 결과 0건)` 이라고 표기합니다.
```

**"절대 지어내지 마세요"가 핵심입니다.** 맛집 목록이 비어 있으면 LLM은 자기가 아는 그럴듯한 식당 이름을 채워 넣으려 합니다. 그 순간 리포트는 **검증되지 않은 정보**가 되고, 사용자는 존재하지 않는 가게를 찾아가게 됩니다.

**③ 화면에도 알림** — `main()` :759

```python
if total_places == 0:
    log("  - 맛집 데이터 0건 -> '데이터 없음'으로 표기하고 리포트 생성을 계속합니다.")
```

**④ 나머지는 그대로 유용하게.** 맛집이 없어도 추천 지역·날씨·행사·일정 제안은 전부 나옵니다. 일정 제안은 맛집이 있으면 가게 이름을 끼워 넣고, 없으면 `"현지 맛집"`으로 자연스럽게 대체합니다 (`build_fallback_report()` :581).

```python
lunch  = places[0]["name"] if places else "현지 맛집"
dinner = places[1]["name"] if len(places) > 1 else "현지 맛집"
```

> **"부분 실패는 전체 실패가 아니다"** 가 이 프로그램의 일관된 원칙입니다. 맛집은 리포트의 한 섹션일 뿐이고, 나머지 80%는 여전히 쓸모 있습니다.

## 4-3. 같은 날짜 반복 실행 시 API 비용을 줄이는 방법

**구현: 원본 JSON 재사용 캐시** — `main()` :709 (보너스 5.2)

```python
cached = None
if raw_path.exists() and not args.no_cache:
    try:
        cached = json.loads(raw_path.read_text(encoding="utf-8"))
        if not cached.get("recommendation"):
            cached = None          # 실패 기록만 있는 파일이면 다시 호출
    except (OSError, json.JSONDecodeError) as exc:
        errors.add("cache", "PARSE_ERROR", f"캐시 파일을 읽지 못해 새로 호출합니다: {exc}")
        cached = None

if cached:
    recommendation = cached["recommendation"]    # [1/3] LLM 호출 건너뜀
    restaurants    = cached["restaurants"]       # [2/3] 지도 API 호출 건너뜀
    provider       = cached.get("place_provider")
else:
    ... 실제 API 호출 ...
```

**설계 포인트**

- **캐시 키 = 날짜**입니다. 파일명이 `{date}_travel_raw.json`이라 별도 캐시 저장소가 필요 없습니다. **결과물 자체가 캐시**입니다.
- **깨진 캐시는 무시하고 진행합니다.** JSON이 깨졌거나 실패 기록만 있는 파일이면 `cached = None`으로 되돌려 정상 호출합니다. 캐시 때문에 프로그램이 죽으면 안 됩니다.
- **탈출구를 뒀습니다.** `--no-cache` (:644). 캐시가 있는데 강제로 갱신할 수 없으면 실무에서 못 씁니다.
- **효과**: 2회차부터 API 호출이 **3회 → 1회**(리포트 생성만). 지도 API는 도시 수만큼 호출되므로 `--cities 3`이면 5회 → 1회입니다.

**더 줄이려면 (미구현 아이디어)**

| 방법 | 바꿀 위치 | 내용 |
|---|---|---|
| 리포트까지 재사용 | `main()` :763 | `report_path`가 있으면 3단계도 건너뛰고 기존 `.md` 유지 (`--reuse-report` 플래그) |
| 캐시 만료 | :709 | `generated_at`과 현재 시각을 비교해 N일 지나면 무효화 |
| 도시 단위 캐시 | `search_restaurants()` | 날짜가 달라도 `제주 맛집`은 재사용 — `results/.cache/{city}.json` |
| 모델 다운그레이드 | :43 | 1차 추천은 `flash-lite` 같은 저비용 모델로, 리포트만 상위 모델 |
| 토큰 절약 | `REPORT_PROMPT` :509 | 맛집 JSON을 통째로 넣지 말고 필요한 필드만 추려서 전달 |

## 4-4. (What-if) 추천 도시가 "광역시/도"처럼 너무 넓거나 애매할 때의 입력 정규화

**문제**: `recommended_city`가 `"경상북도"`, `"강원특별자치도"`, `"수도권"`으로 나오면 `"경상북도 맛집"`으로 검색하게 됩니다. 카카오 키워드 검색은 이런 광역 키워드에 약해서 0건이거나 엉뚱한 결과가 나옵니다.

**현재 적용한 것 — 출력 단계에서 막기** (`RECOMMEND_PROMPT` :276)

```text
- 도시명은 "제주", "강릉", "경주" 처럼 장소 검색에 바로 쓸 수 있는 짧은 지역명으로 씁니다.
```

**예시를 3개 준 것**이 핵심입니다. "짧게 쓰세요"라는 추상적 지시보다, 원하는 형태의 샘플을 보여 주는 쪽이 훨씬 잘 지켜집니다. 실측 8회 실행에서 제주·광양·진주·평창·경주·진해가 나왔고 광역 단위는 없었습니다.

**추가로 적용할 정규화 (개선안)** — `search_places_kakao()` 앞에 넣을 전처리입니다.

```python
# 1) 행정 접미사 제거: "경상북도" → "경상북", "제주특별자치도" → "제주"
SUFFIXES = ("특별자치도", "광역시", "특별시", "자치시", "자치도", "도", "시", "군", "구")

# 2) 광역 → 대표 도시 매핑 (검색 가능한 지점으로 좁힘)
WIDE_AREA = {
    "경상북도": "경주", "경상남도": "통영", "강원특별자치도": "강릉",
    "전라남도": "여수", "충청북도": "청주", "제주특별자치도": "제주",
    "수도권": "서울", "영남": "부산", "호남": "전주",
}

def normalize_city(name: str) -> str:
    name = name.strip()
    if name in WIDE_AREA:                 # 광역이면 대표 도시로 치환
        return WIDE_AREA[name]
    for suf in SUFFIXES:                  # 접미사 제거
        if len(name) > len(suf) + 1 and name.endswith(suf):
            return name[:-len(suf)]
    return name
```

**검색 자체의 품질을 올리는 파라미터**(카카오 로컬 API)

| 파라미터 | 효과 |
|---|---|
| `category_group_code=FD6` | **음식점만** 필터. 지금 결과에 카페·초콜릿 전문점이 섞이는 문제가 해결됩니다 |
| `x`, `y`, `radius` | 좌표 중심 반경 검색. 광역 키워드 대신 **중심점 + 반경**으로 범위를 정확히 지정 |
| `page` | 후보를 더 확보해 품질순으로 재정렬 |

**2단계 폴백 전략**도 가능합니다. `"{city} 맛집"`이 0건이면 → `"{정규화된 city} 맛집"` → 그래도 0건이면 → `"{city} 음식점"`. 단, 명세가 "0건이면 재시도하지 않고 다음 단계로 진행"을 허용하므로 **현재는 재시도 없이 0건을 그대로 표기**합니다. 무한 재시도를 막는 원칙과도 일관됩니다.

> **근본 원칙**: 입력 정규화는 **받는 쪽(지도 API)의 요구사항을 주는 쪽(LLM 프롬프트)에 미리 반영**하는 게 1순위이고, 그래도 새는 것을 코드가 보정하는 게 2순위입니다. 프롬프트로 막으면 API 호출 자체가 줄고, 코드로 막으면 예외 케이스가 늘어납니다.

---

## 부록 — 구술 대비 한 줄 요약

| 질문 | 한 줄 답 |
|---|---|
| 날짜 검증 | `strptime` + `parser.error()` → usage 출력 후 exit 2 |
| JSON 보장 | `responseMimeType` 강제 + 중괄호 깊이 파서 + 필수 키 검증 3단 |
| 단계 연결 | `recommended_city` → `f"{city} 맛집"` → 카카오 GET |
| 실패해도 진행 | `search_restaurants`가 예외를 밖으로 안 던지고 빈 배열 반환 |
| 키 보안 | `os.getenv` + `.gitignore` + `scrub()` 마스킹 |
| 계층 분리 | 조립(main) / 단계 / 제공자 / 공통(http_request) 4층, dict로만 연결 |
| 제공자 교체 | 같은 시그니처 + 공통 출력 스키마 → 함수 1개 + 분기 1줄 추가로 끝 |
| 오류 누적 | `ErrorCollector.add()` 한 줄로 출력·누적·마스킹, 리포트 섹션은 **코드가** 부착 |
| GET/POST | 짧은 조회는 GET(쿼리스트링), 긴 프롬프트는 POST(본문). 인증은 항상 헤더 |
| JSON 강제 이유 | 다음 단계 입력이라서. 검증 가능·실패 명확·계약 역할 |
| 401/403 | 401=키 자체, 403=권한. 키 길이 확인 → 읽은 파일 확인 → 헤더 철자 → 콘솔 설정 |
| 재시도 | 프롬프트 리스트 길이로 2회 고정, `PARSE_ERROR`만 재시도, 2차는 요구 최소화 + temp 0.2 |
| 0건 정책 | 고정 문구 표기 + "지어내지 마세요" 제약 + 나머지 섹션은 정상 생성 |
| 비용 절감 | 결과 JSON 자체를 캐시로 사용(날짜 키), `--no-cache`로 강제 갱신 |
| 입력 정규화 | 프롬프트에 예시 3개로 짧은 지역명 유도(1순위) + 접미사 제거·광역 매핑(2순위) |
