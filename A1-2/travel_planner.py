#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""국내 여행 추천 API 연동 프로그램.

흐름:
    [1/3] LLM(Gemini) API   -> 여행 시기 기반 도시 추천 + 날씨/행사 JSON
    [2/3] 지도/장소 API      -> 도시별 맛집 검색 (Kakao Local 또는 Naver Local)
    [3/3] LLM(Gemini) API   -> 최종 여행 리포트(Markdown) 생성

실행 예)
    python travel_planner.py -date "2026-03-15"

API 키는 절대 코드에 작성하지 않는다. 환경변수 또는 .env 파일에서 읽는다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

try:  # python-dotenv 가 없어도 환경변수만으로 동작해야 한다.
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


# --------------------------------------------------------------------------
# 상수
# --------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"

KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
NAVER_LOCAL_URL = "https://openapi.naver.com/v1/search/local.json"

HTTP_TIMEOUT = 30  # 초
DEFAULT_PLACE_COUNT = 5

# 로그/결과물에 키가 찍히는 사고를 막기 위한 마스킹 대상(실행 시 채워진다)
_SECRETS: list[str] = []


# --------------------------------------------------------------------------
# 공통 유틸
# --------------------------------------------------------------------------


class ApiError(Exception):
    """외부 API 호출/파싱 과정에서 발생한 오류.

    error_type 은 결과 JSON 의 errors[].type 으로 그대로 기록된다.
    (AUTH_ERROR / QUOTA_ERROR / NETWORK_ERROR / PARSE_ERROR / HTTP_ERROR ...)
    """

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


def scrub(text: Any) -> str:
    """문자열에 섞여 들어간 API 키를 마스킹하고, 너무 긴 응답은 잘라낸다."""
    safe = str(text)
    for secret in _SECRETS:
        if secret and secret in safe:
            safe = safe.replace(secret, "***REDACTED***")
    return safe if len(safe) <= 500 else safe[:500] + " ...(생략)"


def log(message: str) -> None:
    print(scrub(message), flush=True)


class ErrorCollector:
    """단계별 오류를 모아 결과 JSON / 리포트의 errors 섹션으로 내보낸다."""

    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def add(self, step: str, error_type: str, message: str) -> None:
        item = {"step": step, "type": error_type, "message": scrub(message)}
        self.items.append(item)
        log("  - 오류: [{}/{}] {}".format(step, error_type, item["message"]))

    def as_list(self) -> list[dict[str, str]]:
        # 캐시에서 이어받은 오류가 재실행마다 중복 누적되지 않도록 중복 제거.
        seen: set[tuple[str, str, str]] = set()
        unique: list[dict[str, str]] = []
        for item in self.items:
            key = (item.get("step", ""), item.get("type", ""), item.get("message", ""))
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique


def http_request(method: str, url: str, **kwargs: Any) -> requests.Response:
    """requests 호출의 공통 오류 처리(네트워크 / 인증 / 쿼터 / HTTP)."""
    try:
        response = requests.request(method, url, timeout=HTTP_TIMEOUT, **kwargs)
    except requests.exceptions.Timeout as exc:
        raise ApiError("NETWORK_ERROR", f"요청 시간 초과({HTTP_TIMEOUT}s): {exc}") from exc
    except requests.exceptions.ConnectionError as exc:
        raise ApiError("NETWORK_ERROR", f"네트워크 연결 실패: {exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise ApiError("NETWORK_ERROR", f"요청 실패: {exc}") from exc

    if response.status_code in (401, 403):
        raise ApiError(
            "AUTH_ERROR",
            f"HTTP {response.status_code} 인증 실패. API 키 / 권한 / 헤더명 / 도메인 설정을 "
            f"확인하세요. ({response.text})",
        )
    if response.status_code == 429:
        raise ApiError(
            "QUOTA_ERROR",
            f"HTTP 429 호출 한도(쿼터) 초과. 잠시 후 다시 시도하세요. ({response.text})",
        )
    if response.status_code >= 400:
        raise ApiError("HTTP_ERROR", f"HTTP {response.status_code}: {response.text}")
    return response


def extract_json_object(text: str) -> dict[str, Any]:
    """LLM 응답 텍스트에서 JSON 객체를 추출/파싱한다.

    코드펜스나 앞뒤 설명 문장이 섞여 있어도 첫 번째 JSON 객체를 찾아낸다.
    """
    if not text or not text.strip():
        raise ApiError("PARSE_ERROR", "LLM 응답이 비어 있습니다.")

    cleaned = re.sub(r"^\s*```(?:json)?|```\s*$", "", text.strip(), flags=re.MULTILINE).strip()

    try:
        parsed: Any = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = None

    if parsed is None:
        start = cleaned.find("{")
        if start == -1:
            raise ApiError("PARSE_ERROR", f"응답에서 JSON 객체를 찾지 못했습니다: {cleaned[:200]}")
        depth, end, in_str, escaped = 0, -1, False, False
        for idx in range(start, len(cleaned)):
            ch = cleaned[idx]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = idx + 1
                    break
        if end == -1:
            raise ApiError("PARSE_ERROR", f"JSON 객체가 닫히지 않았습니다: {cleaned[:200]}")
        try:
            parsed = json.loads(cleaned[start:end])
        except json.JSONDecodeError as exc:
            raise ApiError("PARSE_ERROR", f"JSON 파싱 실패: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ApiError("PARSE_ERROR", f"JSON 최상위가 객체가 아닙니다: {type(parsed).__name__}")
    return parsed


def strip_tags(text: str) -> str:
    """네이버 응답 title 의 <b> 태그 등 HTML 태그 제거."""
    return re.sub(r"<[^>]+>", "", text or "").strip()


# --------------------------------------------------------------------------
# 1) LLM (Google Gemini) 클라이언트
# --------------------------------------------------------------------------


class GeminiClient:
    """Gemini generateContent REST API(POST) 래퍼."""

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self.url = GEMINI_ENDPOINT.format(model=model)

    def generate(self, prompt: str, *, json_mode: bool = False,
                 temperature: float = 0.7) -> str:
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
             "generationConfig": {"temperature": temperature},
        }
        if json_mode:
            # 구조화된 출력: 모델이 JSON 이외의 문장을 덧붙이지 못하게 강제한다.
            payload["generationConfig"]["responseMimeType"] = "application/json"

        response = http_request(
            "POST",
            self.url,
            headers={
                "Content-Type": "application/json",
                # 키는 환경변수에서 읽은 값만 사용한다(코드에 하드코딩 금지).
                "x-goog-api-key": self.api_key,
            },
            json=payload,
        )

        try:
            data = response.json()
        except ValueError as exc:
            raise ApiError("PARSE_ERROR", f"LLM 응답이 JSON 형식이 아닙니다: {exc}") from exc

        candidates = data.get("candidates") or []
        if not candidates:
            feedback = data.get("promptFeedback", {})
            raise ApiError("PARSE_ERROR", f"LLM 응답에 candidates 가 없습니다. promptFeedback={feedback}")

        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        if not text.strip():
            raise ApiError(
                "PARSE_ERROR",
                f"LLM 응답 본문이 비어 있습니다. finishReason={candidates[0].get('finishReason')}",
            )
        return text


# --------------------------------------------------------------------------
# 2) 1차 추천(날씨/행사) - LLM
# --------------------------------------------------------------------------

RECOMMEND_PROMPT = """당신은 국내(대한민국) 여행 플래너입니다.
여행 날짜: {date}

이 시기에 여행하기 좋은 국내 도시 {count}곳을 추천하고, 각 도시의 일반적인 날씨와 행사/축제 후보를 정리하세요.
실제 예보가 아니라 '해당 시기의 일반적인 계절 특성' 기준으로 작성하면 됩니다.

아래 JSON 스키마를 정확히 지켜서 JSON "만" 출력하세요. 설명 문장, 코드펜스, 주석을 절대 붙이지 마세요.

{{
  "recommended_city": "가장 추천하는 도시 1곳 (문자열)",
  "weather": "recommended_city 의 해당 시기 일반적 날씨 요약 (문자열)",
  "events": ["행사/축제 후보 1~3개 (문자열 배열)"],
  "reason": "추천 근거 2~4문장 (문자열)",
  "recommended_cities": [
    {{
      "city": "도시명",
      "weather": "해당 시기 일반적 날씨 요약",
      "events": ["행사/축제 후보 1~3개"],
      "reason": "추천 근거 2~4문장"
    }}
  ]
}}

조건:
- recommended_cities 배열에는 정확히 {count}개의 도시를 담습니다.
- recommended_cities[0] 의 값은 최상위 recommended_city / weather / events / reason 과 동일해야 합니다.
- 도시명은 "제주", "강릉", "경주" 처럼 장소 검색에 바로 쓸 수 있는 짧은 지역명으로 씁니다.
- 모든 값은 한국어로 작성합니다.
"""

RETRY_PROMPT = """이전 응답이 JSON 으로 파싱되지 않았습니다.
여행 날짜 {date} 기준 국내 여행지 {count}곳에 대해, 아래 필수 키만 담은 JSON 객체 하나만 출력하세요.
코드펜스 / 설명 / 주석 없이 JSON 만 출력합니다.

{{"recommended_city": "도시명", "weather": "날씨 요약", "events": ["행사1"], "reason": "추천 이유", "recommended_cities": [{{"city": "도시명", "weather": "날씨 요약", "events": ["행사1"], "reason": "추천 이유"}}]}}
"""


def normalize_recommendation(raw: dict[str, Any], count: int) -> dict[str, Any]:
    """1차 JSON 을 최소 스키마에 맞게 검증/정규화한다. 실패 시 ApiError(PARSE_ERROR)."""

    def as_event_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()][:3]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    cities: list[dict[str, Any]] = []
    for entry in raw.get("recommended_cities") or []:
        if isinstance(entry, dict):
            name = str(entry.get("city") or entry.get("recommended_city") or "").strip()
            if not name:
                continue
            cities.append({
                "city": name,
                "weather": str(entry.get("weather") or "").strip(),
                "events": as_event_list(entry.get("events")),
                "reason": str(entry.get("reason") or "").strip(),
            })
        elif isinstance(entry, str) and entry.strip():
            cities.append({"city": entry.strip(), "weather": "", "events": [], "reason": ""})

    top_city = str(raw.get("recommended_city") or "").strip()
    if not top_city and cities:
        top_city = cities[0]["city"]
    if not top_city:
        raise ApiError("PARSE_ERROR", "필수 키 recommended_city 가 없습니다.")

    weather = str(raw.get("weather") or "").strip()
    reason = str(raw.get("reason") or "").strip()
    events = as_event_list(raw.get("events"))

    if not cities:
        cities = [{"city": top_city, "weather": weather, "events": events, "reason": reason}]
    else:
        # 최상위 값이 비어 있으면 첫 번째 도시 값으로 채운다.
        weather = weather or cities[0]["weather"]
        reason = reason or cities[0]["reason"]
        events = events or cities[0]["events"]

    if not weather or not reason:
        raise ApiError("PARSE_ERROR", "필수 키 weather / reason 값이 비어 있습니다.")

    return {
        "recommended_city": top_city,
        "weather": weather,
        "events": events,
        "reason": reason,
        "recommended_cities": cities[:count],
    }


def fetch_recommendation(llm: GeminiClient, date_str: str, count: int,
                         errors: ErrorCollector) -> dict[str, Any]:
    """1차 추천 JSON 생성. JSON 파싱 실패 시 재요청은 최대 1회."""
    prompts = [
        RECOMMEND_PROMPT.format(date=date_str, count=count),
        RETRY_PROMPT.format(date=date_str, count=count),
    ]

    last_error: ApiError | None = None
    for attempt, prompt in enumerate(prompts, start=1):
        try:
            text = llm.generate(prompt, json_mode=True,
                                temperature=0.7 if attempt == 1 else 0.2)
            return normalize_recommendation(extract_json_object(text), count)
        except ApiError as exc:
            last_error = exc
            if exc.error_type != "PARSE_ERROR":
                # 인증 / 쿼터 / 네트워크 오류는 프롬프트를 바꿔도 의미가 없다.
                break
            if attempt == 1:
                errors.add("llm_recommend", exc.error_type,
                           f"(1차 시도 실패, 1회만 재요청) {exc.message}")
                log("  - JSON 파싱 실패 -> 필수 키만 다시 요청합니다(재시도 1회).")

    assert last_error is not None
    raise last_error


# --------------------------------------------------------------------------
# 3) 지도/장소 검색 (Kakao Local / Naver Local)
# --------------------------------------------------------------------------


def resolve_place_provider(requested: str) -> tuple[str | None, str | None]:
    """사용 가능한 지도 API 제공자를 결정한다. -> (provider, 안내 메시지)"""
    kakao = os.getenv("KAKAO_REST_API_KEY")
    naver_id = os.getenv("NAVER_CLIENT_ID")
    naver_secret = os.getenv("NAVER_CLIENT_SECRET")

    if requested == "kakao":
        return ("kakao", None) if kakao else (None, "KAKAO_REST_API_KEY 가 설정되지 않았습니다.")
    if requested == "naver":
        if naver_id and naver_secret:
            return "naver", None
        return None, "NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 가 설정되지 않았습니다."

    if kakao:
        return "kakao", None
    if naver_id and naver_secret:
        return "naver", None
    return None, ("지도/장소 API 키가 없습니다. KAKAO_REST_API_KEY 또는 "
                  "NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 를 설정하세요.")


def search_places_kakao(city: str, size: int) -> list[dict[str, Any]]:
    """Kakao Local 키워드 검색(GET). 인증은 Authorization: KakaoAK {키} 헤더."""
    query = f"{city} 맛집"
    response = http_request(
        "GET",
        KAKAO_KEYWORD_URL,
        headers={"Authorization": f"KakaoAK {os.environ['KAKAO_REST_API_KEY']}"},
        params={"query": query, "size": size, "sort": "accuracy"},
    )
    try:
        documents = response.json().get("documents", [])
    except ValueError as exc:
        raise ApiError("PARSE_ERROR", f"Kakao 응답 JSON 파싱 실패: {exc}") from exc

    places: list[dict[str, Any]] = []
    for doc in documents[:size]:
        lng = float(doc["x"]) if doc.get("x") else None  # x = 경도(longitude)
        lat = float(doc["y"]) if doc.get("y") else None  # y = 위도(latitude)
        places.append({
            "name": doc.get("place_name", ""),
            "address": doc.get("road_address_name") or doc.get("address_name", ""),
            "category": doc.get("category_name", ""),
            "phone": doc.get("phone", ""),
            "url": doc.get("place_url", ""),
            "x": lng,
            "y": lat,
            "lng": lng,
            "lat": lat,
            "provider": "kakao",
            "query": query,
        })
    return places


def search_places_naver(city: str, size: int) -> list[dict[str, Any]]:
    """Naver 지역 검색(GET). 인증은 X-Naver-Client-Id / Secret 헤더."""
    query = f"{city} 맛집"
    response = http_request(
        "GET",
        NAVER_LOCAL_URL,
        headers={
            "X-Naver-Client-Id": os.environ["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": os.environ["NAVER_CLIENT_SECRET"],
        },
        params={"query": query, "display": size, "sort": "random"},
    )
    try:
        items = response.json().get("items", [])
    except ValueError as exc:
        raise ApiError("PARSE_ERROR", f"Naver 응답 JSON 파싱 실패: {exc}") from exc

    places: list[dict[str, Any]] = []
    for item in items[:size]:
        # mapx / mapy 는 WGS84 좌표에 10^7 을 곱한 정수값이다.
        mapx, mapy = str(item.get("mapx", "")).strip(), str(item.get("mapy", "")).strip()
        lng = float(mapx) / 1e7 if mapx.isdigit() else None
        lat = float(mapy) / 1e7 if mapy.isdigit() else None
        places.append({
            "name": strip_tags(item.get("title", "")),
            "address": item.get("roadAddress") or item.get("address", ""),
            "category": item.get("category", ""),
            "phone": item.get("telephone", ""),
            "url": item.get("link", ""),
            "x": lng,
            "y": lat,
            "lng": lng,
            "lat": lat,
            "provider": "naver",
            "query": query,
        })
    return places


def search_restaurants(cities: list[str], provider: str | None, provider_note: str | None,
                       size: int, errors: ErrorCollector) -> dict[str, list[dict[str, Any]]]:
    """도시별 맛집 검색. 실패하거나 0건이어도 프로그램은 중단되지 않는다."""
    result: dict[str, list[dict[str, Any]]] = {city: [] for city in cities}

    if provider is None:
        errors.add("place_search", "CONFIG_ERROR",
                   f"{provider_note} 맛집 섹션은 '데이터 없음'으로 처리하고 계속 진행합니다.")
        return result

    searcher = search_places_kakao if provider == "kakao" else search_places_naver
    for city in cities:
        try:
            places = searcher(city, size)
        except ApiError as exc:
            errors.add("place_search", exc.error_type, f"[{city}] {exc.message}")
            log("  - 맛집 섹션은 '데이터 없음'으로 처리하고 계속 진행합니다.")
            continue
        except Exception as exc:  # 예상하지 못한 오류로도 중단되지 않게
            errors.add("place_search", "UNKNOWN_ERROR", f"[{city}] {exc}")
            continue

        if not places:
            errors.add("place_search", "EMPTY_RESULT", f"0 results for query='{query_of(city)}'")
            continue

        result[city] = places
        log(f"  - {city}: 맛집 {len(places)}곳 검색 완료")
    return result


def query_of(city: str) -> str:
    return f"{city} 맛집"


# --------------------------------------------------------------------------
# 4) 최종 리포트 생성 - LLM
# --------------------------------------------------------------------------

REPORT_PROMPT = """당신은 국내 여행 리포트를 작성하는 에디터입니다.
아래 데이터를 바탕으로 한국어 Markdown 여행 리포트를 작성하세요.

여행 날짜: {date}

[1차 추천 JSON]
{recommendation}

[맛집 검색 결과 (도시별, 0건일 수 있음)]
{restaurants}

작성 규칙:
- Markdown "만" 출력합니다. 전체를 코드펜스로 감싸지 마세요.
- 최상위 제목은 `# {date} 국내 여행 추천 리포트` 로 시작합니다.
- 아래 섹션을 이 순서로 포함합니다.
  ## 추천 지역
  ## 추천 이유
  ## 날씨 요약
  ## 행사/축제
  ## 맛집 추천
  ## 1일 일정 제안
- 추천 도시가 여러 곳이면 각 섹션에서 도시별로 구분해 정리합니다.
- 맛집은 제공된 데이터에 있는 가게만 사용합니다. 절대 지어내지 마세요.
- 맛집 목록이 0건인 도시는 정확히 `- 데이터 없음 (장소 검색 결과 0건)` 이라고 표기합니다.
- 맛집은 `- **이름** (카테고리) — 주소` 형태로 쓰고, url 이 있으면 뒤에 링크를 붙입니다.
- 1일 일정 제안은 오전 / 오후 / 저녁 3개 구간으로 작성합니다.
- '오류 요약' 섹션은 프로그램이 따로 붙이므로 작성하지 마세요.
"""


def build_fallback_report(date_str: str, recommendation: dict[str, Any],
                          restaurants: dict[str, list[dict[str, Any]]]) -> str:
    """LLM 리포트 생성이 실패해도 리포트 파일은 남기기 위한 로컬 생성기."""
    cities = recommendation.get("recommended_cities") or []
    lines = [f"# {date_str} 국내 여행 추천 리포트", "", "## 추천 지역", ""]
    lines += [f"- {c['city']}" for c in cities] or ["- 데이터 없음"]

    lines += ["", "## 추천 이유", ""]
    for city in cities:
        lines += [f"### {city['city']}", "", city.get("reason") or "데이터 없음", ""]

    lines += ["## 날씨 요약", ""]
    for city in cities:
        lines.append(f"- **{city['city']}**: {city.get('weather') or '데이터 없음'}")

    lines += ["", "## 행사/축제", ""]
    for city in cities:
        lines += [f"### {city['city']}", ""]
        lines += [f"- {e}" for e in (city.get("events") or [])] or ["- 데이터 없음"]
        lines.append("")

    lines += ["## 맛집 추천", ""]
    for city in cities:
        lines += [f"### {city['city']}", ""]
        places = restaurants.get(city["city"]) or []
        if not places:
            lines += ["- 데이터 없음 (장소 검색 결과 0건)", ""]
            continue
        for place in places:
            entry = f"- **{place.get('name', '')}**"
            if place.get("category"):
                entry += f" ({place['category']})"
            if place.get("address"):
                entry += f" — {place['address']}"
            if place.get("url"):
                entry += f" [지도]({place['url']})"
            lines.append(entry)
        lines.append("")

    lines += ["## 1일 일정 제안", ""]
    for city in cities:
        places = restaurants.get(city["city"]) or []
        lunch = places[0]["name"] if places else "현지 맛집"
        dinner = places[1]["name"] if len(places) > 1 else "현지 맛집"
        lines += [
            f"### {city['city']}", "",
            "- 오전: 도심 / 자연 명소 도보 산책",
            f"- 오후: 지역 대표 관광지 관람, {lunch} 에서 늦은 점심",
            f"- 저녁: {dinner} 에서 저녁 식사 후 야경 산책",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def generate_report(llm: GeminiClient, date_str: str, recommendation: dict[str, Any],
                    restaurants: dict[str, list[dict[str, Any]]],
                    errors: ErrorCollector) -> str:
    prompt = REPORT_PROMPT.format(
        date=date_str,
        recommendation=json.dumps(recommendation, ensure_ascii=False, indent=2),
        restaurants=json.dumps(restaurants, ensure_ascii=False, indent=2),
    )
    try:
        text = llm.generate(prompt, temperature=0.6)
    except ApiError as exc:
        errors.add("llm_report", exc.error_type,
                   f"{exc.message} (로컬 템플릿으로 리포트를 생성합니다)")
        return build_fallback_report(date_str, recommendation, restaurants)

    cleaned = text.strip()
    if cleaned.startswith("```"):  # 모델이 전체를 코드펜스로 감싼 경우 제거
        cleaned = re.sub(r"^```(?:markdown|md)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip() + "\n"


def append_error_section(report: str, errors: list[dict[str, str]]) -> str:
    lines = [report.rstrip(), "", "## 오류 요약(errors)", ""]
    if not errors:
        lines.append("- 없음")
    else:
        for err in errors:
            lines.append(f"- `{err['step']}` / `{err['type']}`: {err['message']}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# 5) CLI
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="travel_planner.py",
        description="LLM API + 지도/장소 API 를 조합한 국내 여행 추천 리포트 생성기",
        epilog='사용 예: python travel_planner.py -date "2026-03-15" --cities 2',
    )
    parser.add_argument("-date", "--date", dest="date", required=True,
                        metavar="YYYY-MM-DD", help="여행 날짜 (필수, 형식: YYYY-MM-DD)")
    parser.add_argument("--cities", type=int, default=1, metavar="N",
                        help="추천받을 도시 수 1~3 (기본값: 1)")
    parser.add_argument("--places", type=int, default=DEFAULT_PLACE_COUNT, metavar="N",
                        help=f"도시별 맛집 검색 개수 (기본값: {DEFAULT_PLACE_COUNT})")
    parser.add_argument("--map-provider", choices=["auto", "kakao", "naver"], default="auto",
                        help="지도/장소 API 제공자 (기본값: auto = 설정된 키를 자동 선택)")
    parser.add_argument("--no-cache", action="store_true",
                        help="같은 날짜의 원본 JSON 이 있어도 무시하고 API 를 다시 호출한다")

    args = parser.parse_args(argv)

    # 날짜 형식 검증: 잘못되면 사용법(usage)을 출력하고 종료한다.
    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        parser.error(f'날짜 형식이 올바르지 않습니다: "{args.date}" (예: -date "2026-03-15")')

    if not 1 <= args.cities <= 3:
        parser.error("--cities 는 1~3 사이여야 합니다.")
    if not 1 <= args.places <= 15:
        parser.error("--places 는 1~15 사이여야 합니다.")
    return args


def load_api_keys() -> str:
    """환경변수 / .env 에서 키를 읽는다. LLM 키가 없으면 즉시 종료."""
    if load_dotenv is not None:
        load_dotenv(BASE_DIR / ".env")

    for name in ("GEMINI_API_KEY", "KAKAO_REST_API_KEY",
                 "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"):
        value = os.getenv(name)
        if value:
            _SECRETS.append(value)

    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        print(
            "[오류] GEMINI_API_KEY 가 설정되지 않았습니다.\n"
            "\n"
            "설정 방법 (택 1)\n"
            "  1) .env 파일: 이 폴더에 .env 를 만들고 아래 한 줄을 추가\n"
            "       GEMINI_API_KEY=발급받은_키\n"
            "  2) Windows PowerShell (현재 세션에만 적용):\n"
            '       $env:GEMINI_API_KEY="발급받은_키"\n'
            "  3) macOS / Linux (현재 세션에만 적용):\n"
            '       export GEMINI_API_KEY="발급받은_키"\n'
            "\n"
            "키 발급: https://aistudio.google.com/apikey\n"
            "주의: 키 값은 코드 / README / 결과 파일에 절대 직접 작성하지 마세요.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return gemini_key


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    gemini_key = load_api_keys()
    model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RESULTS_DIR / f"{args.date}_travel_raw.json"
    report_path = RESULTS_DIR / f"{args.date}_travel_plan.md"

    errors = ErrorCollector()
    llm = GeminiClient(gemini_key, model)
    provider: str | None = None

    log(f"여행 날짜: {args.date} / LLM 모델: {model}")

    # ---- 캐시 확인 (보너스 5.2) -------------------------------------------
    cached: dict[str, Any] | None = None
    if raw_path.exists() and not args.no_cache:
        try:
            cached = json.loads(raw_path.read_text(encoding="utf-8"))
            if not cached.get("recommendation"):
                cached = None  # 실패 기록만 있는 파일이면 다시 호출한다.
        except (OSError, json.JSONDecodeError) as exc:
            errors.add("cache", "PARSE_ERROR", f"캐시 파일을 읽지 못해 새로 호출합니다: {exc}")
            cached = None

    if cached:
        log(f"캐시 발견: {raw_path.name} -> [1/3], [2/3] API 호출을 건너뜁니다. "
            f"(강제로 다시 호출하려면 --no-cache)")
        recommendation = cached.get("recommendation") or {}
        restaurants = cached.get("restaurants") or {}
        provider = cached.get("place_provider")
        for item in cached.get("errors") or []:  # 이전 실행의 오류도 이어서 남긴다.
            errors.items.append(item)
    else:
        # ---- [1/3] 1차 추천 ------------------------------------------------
        log("[1/3] 1차 추천 생성 중(LLM)...")
        try:
            recommendation = fetch_recommendation(llm, args.date, args.cities, errors)
        except ApiError as exc:
            errors.add("llm_recommend", exc.error_type, exc.message)
            raw_path.write_text(
                json.dumps({"date": args.date, "recommendation": {}, "restaurants": {},
                            "errors": errors.as_list()}, ensure_ascii=False, indent=2),
                encoding="utf-8")
            print("\n[중단] 1차 추천 생성에 실패했습니다. 리포트를 만들 기준 데이터가 없습니다.",
                  file=sys.stderr)
            if exc.error_type == "AUTH_ERROR":
                print("       GEMINI_API_KEY 값이 유효한지 확인하세요.", file=sys.stderr)
            print(f"       오류 요약은 {raw_path} 에 저장했습니다.", file=sys.stderr)
            return 1

        for city in recommendation["recommended_cities"]:
            log(f'  - recommended_city: "{city["city"]}"')

        # ---- [2/3] 맛집 검색 -----------------------------------------------
        log("[2/3] 맛집 검색 중(지도/장소 API)...")
        provider, provider_note = resolve_place_provider(args.map_provider)
        if provider:
            log(f"  - 지도 API: {provider}")
        city_names = [c["city"] for c in recommendation["recommended_cities"]]
        restaurants = search_restaurants(city_names, provider, provider_note, args.places, errors)

    total_places = sum(len(v) for v in restaurants.values())
    if total_places == 0:
        log("  - 맛집 데이터 0건 -> '데이터 없음'으로 표기하고 리포트 생성을 계속합니다.")

    # ---- [3/3] 리포트 생성 --------------------------------------------------
    log("[3/3] 최종 리포트 생성 중(LLM)...")
    report = generate_report(llm, args.date, recommendation, restaurants, errors)

    raw_payload = {
        "date": args.date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "llm_provider": "google-gemini",
        "llm_model": model,
        "place_provider": provider,
        "recommendation": recommendation,
        "restaurants": restaurants,
        "restaurant_count": total_places,
        "errors": errors.as_list(),
    }
    raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(append_error_section(report, errors.as_list()), encoding="utf-8")

    log("  - 리포트 생성 완료")
    log("")
    log(f"완료! {report_path} 를 확인하세요.")
    log(f"      원본 데이터: {raw_path}")
    if errors.items:
        log(f"      오류 {len(errors.items)}건은 리포트의 '오류 요약(errors)' 섹션에 정리했습니다.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[중단] 사용자에 의해 취소되었습니다.", file=sys.stderr)
        sys.exit(130)
