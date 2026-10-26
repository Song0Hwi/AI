"""
AI 챗봇 및 도구 호출(Function Calling) 서비스 (ai_service.py)
- 1단계: /api/data/summary 요약을 조회하여 시스템 프롬프트에 컨텍스트 주입(Context Injection)
- 2단계: 보너스 과제 - 질문 의도를 분석하여 필요한 내부 도구(Function Calling) 호출 및 근거 기록
- 3단계: OpenAI GPT API 호출 (키 미인증/크레딧 부족 시 Gemini 3.6 Flash 및 데이터 분석 엔진 자동 폴백)
- 4단계: 대화 내용을 Firestore 'conversations' 컬렉션에 자동 저장
"""
import json
from typing import List, Dict, Any, Optional, Tuple

from openai import OpenAI
from config import settings
from schemas import SummaryResponse
from services.firebase_service import firebase_service, now_iso
from services.analytics_service import analytics_service


# =====================================================================
# OpenAI Function Calling 도구 스키마 정의 (보너스 과제 1)
# =====================================================================
OPENAI_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_data_summary",
            "description": "시계열 데이터의 전체 기간, 레코드 수, 주요 지표(합계/평균/최대/최소) 및 최근 트렌드 요약을 조회합니다.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_timeseries_data",
            "description": "특정 연도/날짜 구간, 계절/지역 키워드, 또는 값 기준 상위/하위 시계열 레코드를 상세 검색합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "조회 시작일 (YYYY-MM-DD)"},
                    "end_date": {"type": "string", "description": "조회 종료일 (YYYY-MM-DD)"},
                    "keyword": {"type": "string", "description": "검색 키워드 (예: 여름, 겨울, 경기도, 서울, 2024, 2025)"},
                    "sort_by": {
                        "type": "string",
                        "enum": ["date_asc", "date_desc", "value_desc", "value_asc"],
                        "description": "정렬 방식 (기본: date_desc)",
                    },
                    "limit": {"type": "integer", "description": "반환할 최대 레코드 수 (기본: 10)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_advanced_statistics",
            "description": "연도별/계절별 평균, 변동계수(CV), 이상치(급증/급감 구간), 지역별/시간대별 분포 및 향후 4주 예측치를 조회합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "enum": ["all", "seasonal", "yearly", "outliers", "forecast", "regional"],
                        "description": "집중 분석 항목",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_conversations",
            "description": "최근 저장된 사용자-AI 대화 목록과 주제를 조회합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "조회할 대화 개수 (기본: 5)"}
                },
                "required": [],
            },
        },
    },
]


class AIService:
    def __init__(self):
        self.openai_key = settings.OPENAI_API_KEY
        self.gemini_key = settings.GEMINI_API_KEY

    def build_system_prompt(
        self,
        summary: SummaryResponse,
        tool_outputs: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """미션 요구사항 7 & 8: 데이터 요약을 시스템 프롬프트에 삽입(컨텍스트 주입)"""
        metrics_dict = {
            "total": summary.metrics.total,
            "average": summary.metrics.average,
            "max": f"{summary.metrics.max:,.0f} ({summary.metrics.max_date})",
            "min": f"{summary.metrics.min:,.0f} ({summary.metrics.min_date})",
            "std_dev": summary.metrics.std_dev,
            "cv_percent": f"{summary.metrics.cv_percent}%",
        }
        base_prompt = f"""당신은 데이터 분석 비서입니다.
현재 서비스는 '소방청 전국 119 신고접수 현황 시계열 데이터(주간 단위 집계)'를 관리하고 분석합니다.

[사용자 데이터 요약]
- 데이터 기간: {summary.period}
- 총 레코드: {summary.count}개
- 주요 지표: {json.dumps(metrics_dict, ensure_ascii=False)}
- 최근 트렌드: {summary.trend}
- 핵심 하이라이트: {" / ".join(summary.highlights or [])}

위 데이터를 기반으로 맞춤형 답변을 제공하세요.
답변 작성 원칙:
1. 반드시 실제 데이터 수치(건수, 날짜, 증감률 %, 지역 비중, 평균 현장도착 소요시간 등)를 근거로 제시하세요.
2. '관찰된 사실(Fact)'과 '원인 해석/인사이트(Insight)' 및 '권장 대응 방안(Action)'을 구분하여 가독성 높은 마크다운으로 답변하세요.
3. 사용자가 특정 시기/계절/최고·최저치/추세/예측을 물으면 아래 [도구 호출(Function Calling) 결과]의 상세 레코드를 적극 인용하세요.
"""
        if tool_outputs:
            tool_section = "\n[도구 호출(Function Calling) 상세 조회 결과]\n"
            for idx, t in enumerate(tool_outputs, start=1):
                tool_section += (
                    f"{idx}. 호출 도구: `{t['tool']}` (호출 근거: {t['reason']})\n"
                    f"   조회 데이터: {json.dumps(t['data'], ensure_ascii=False)}\n"
                )
            base_prompt += tool_section
        return base_prompt

    # =================================================================
    # 내부 도구(Function Calling) 실행기
    # =================================================================
    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "get_data_summary":
            return analytics_service.get_summary().model_dump()

        if tool_name == "search_timeseries_data":
            items = firebase_service.list_data(
                start_date=args.get("start_date"),
                end_date=args.get("end_date"),
                search=args.get("keyword"),
            )
            sort_by = args.get("sort_by", "date_desc")
            if sort_by == "value_desc":
                items.sort(key=lambda x: float(x["value"]), reverse=True)
            elif sort_by == "value_asc":
                items.sort(key=lambda x: float(x["value"]))
            elif sort_by == "date_desc":
                items.sort(key=lambda x: x["date"], reverse=True)
            else:
                items.sort(key=lambda x: x["date"])

            limit = int(args.get("limit", 10))
            sliced = items[:limit]
            avg_v = round(sum(float(x["value"]) for x in items) / len(items), 1) if items else 0
            return {
                "matched_count": len(items),
                "matched_average": avg_v,
                "records": [
                    {"date": r["date"], "value": r["value"], "memo": r.get("memo", "")}
                    for r in sliced
                ],
            }

        if tool_name == "get_advanced_statistics":
            adv = analytics_service.get_advanced_statistics()
            focus = args.get("focus", "all")
            if focus == "seasonal":
                return {"seasonal_statistics": adv["seasonal_statistics"]}
            if focus == "yearly":
                return {"yearly_statistics": adv["yearly_statistics"]}
            if focus == "outliers":
                return {"outliers": adv["outliers"]}
            if focus == "forecast":
                return {"forecast_next_4_weeks": adv["forecast_next_4_weeks"]}
            return {
                "yearly_statistics": adv["yearly_statistics"],
                "seasonal_statistics": adv["seasonal_statistics"],
                "top_outliers": adv["outliers"][:6],
                "forecast_next_4_weeks": adv["forecast_next_4_weeks"],
                "metadata_insights": adv["metadata_insights"],
            }

        if tool_name == "get_recent_conversations":
            limit = int(args.get("limit", 5))
            convs = firebase_service.list_conversations()[:limit]
            return {
                "count": len(convs),
                "conversations": [
                    {
                        "id": c["id"],
                        "title": c["title"],
                        "message_count": c.get("message_count", 0),
                        "updated_at": c.get("updated_at", ""),
                    }
                    for c in convs
                ],
            }

        return {"error": f"Unknown tool: {tool_name}"}

    def plan_and_run_tools(self, user_message: str) -> List[Dict[str, Any]]:
        """
        사용자 질문의 의도를 분석하여 필요한 내부 도구(Function Calling)를 결정하고 실행합니다.
        (어떤 근거로 어떤 도구를 호출했는지 reason 기록 포함)
        """
        q = user_message.lower()
        planned: List[Tuple[str, Dict[str, Any], str]] = []

        # 1. 기본 데이터 요약 도구는 항상 컨텍스트 확인용으로 기록
        planned.append((
            "get_data_summary",
            {},
            "질문 답변의 기준이 되는 전체 기간·평균·최대/최소·최근 추세 요약 지표 확보",
        ))

        # 2. 최고/최저/피크/언제 관련 질문
        if any(k in q for k in ["최고", "최대", "가장 많", "피크", "언제", "높았", "상위", "급증"]):
            planned.append((
                "search_timeseries_data",
                {"sort_by": "value_desc", "limit": 5},
                "질문에 최고치/급증 시기 관련 키워드가 포함되어 상위 5개 피크 주간 레코드 상세 조회",
            ))

        if any(k in q for k in ["최저", "최소", "가장 적", "낮았", "하위", "급감"]):
            planned.append((
                "search_timeseries_data",
                {"sort_by": "value_asc", "limit": 5},
                "질문에 최저치/급감 시기 관련 키워드가 포함되어 하위 5개 주간 레코드 상세 조회",
            ))

        # 3. 특정 연도/계절/지역 검색
        for kw in ["2022", "2023", "2024", "2025", "여름", "겨울", "봄", "가을", "경기", "서울", "부산"]:
            if kw in q:
                planned.append((
                    "search_timeseries_data",
                    {"keyword": kw, "sort_by": "date_desc", "limit": 8},
                    f"사용자 질문에서 '{kw}' 조건이 감지되어 해당 조건의 시계열 레코드 및 메모 필터링 조회",
                ))
                break

        # 4. 최근/이번 달/추세/흐름 질문
        if any(k in q for k in ["최근", "이번", "추세", "트렌드", "변화", "흐름", "어때", "실적", "현황"]):
            planned.append((
                "search_timeseries_data",
                {"sort_by": "date_desc", "limit": 8},
                "최근 시계열 흐름 및 직전 8주간 신고접수 추이를 비교하기 위해 최신 레코드 조회",
            ))

        # 5. 통계/계절성/예측/이상치/지역/도착시간 심화 질문
        if any(k in q for k in ["통계", "계절", "연도", "예측", "전망", "이상치", "지역", "시간", "도착", "분석", "요약", "인사이트"]):
            planned.append((
                "get_advanced_statistics",
                {"focus": "all"},
                "연도별·계절별 통계, 이상치(Z-score), 시도별 비중 및 향후 4주 예측 지표 종합 분석",
            ))

        # 6. 이전 대화 기록 관련 질문
        if any(k in q for k in ["대화", "히스토리", "기록", "이전에"]):
            planned.append((
                "get_recent_conversations",
                {"limit": 5},
                "사용자가 이전 대화 이력을 요청하여 최근 저장된 대화 목록 조회",
            ))

        # 만약 위 조건 중 기본 요약 외에 추가 도구가 없다면 최신 데이터 + 심화 통계 기본 제공
        if len(planned) == 1:
            planned.append((
                "search_timeseries_data",
                {"sort_by": "date_desc", "limit": 6},
                "최근 시계열 데이터 현황 파악을 위한 최신 6주 레코드 조회",
            ))
            planned.append((
                "get_advanced_statistics",
                {"focus": "all"},
                "맞춤형 심층 답변 구성을 위한 계절별·연도별 통계 및 예측 지표 조회",
            ))

        results = []
        seen = set()
        for tool_name, args, reason in planned:
            key = f"{tool_name}:{json.dumps(args, sort_keys=True)}"
            if key in seen:
                continue
            seen.add(key)
            data = self.execute_tool(tool_name, args)
            results.append({
                "tool": tool_name,
                "arguments": args,
                "reason": reason,
                "data": data,
            })
        return results

    # =================================================================
    # 메인 채팅 응답 생성 (OpenAI -> Gemini -> 내장 분석 엔진)
    # =================================================================
    def chat(
        self,
        user_message: str,
        conversation_id: Optional[str] = None,
        use_tools: bool = True,
    ) -> Dict[str, Any]:
        # 1. 데이터 요약 조회 (/api/data/summary)
        summary = analytics_service.get_summary()

        # 2. 보너스: Function Calling 도구 실행
        tool_outputs = self.plan_and_run_tools(user_message) if use_tools else []

        # 3. 시스템 프롬프트에 데이터 요약 및 도구 결과 주입
        system_prompt = self.build_system_prompt(summary, tool_outputs)

        # 이전 대화 맥락 불러오기
        existing_conv = firebase_service.get_conversation(conversation_id) if conversation_id else None
        history_messages = existing_conv.get("messages", []) if existing_conv else []

        reply_text = ""
        model_used = ""

        # A. OpenAI API 호출 시도 (정식 OpenAI SDK + Function Calling)
        if self.openai_key and self.openai_key.startswith("sk-"):
            try:
                client = OpenAI(api_key=self.openai_key)
                oai_messages = [{"role": "system", "content": system_prompt}]
                for m in history_messages[-6:]:
                    oai_messages.append({"role": m["role"], "content": m["content"]})
                oai_messages.append({"role": "user", "content": user_message})

                resp = client.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=oai_messages,
                    tools=OPENAI_TOOLS_SCHEMA if use_tools else None,
                    tool_choice="auto" if use_tools else None,
                    max_tokens=900,
                    temperature=0.3,
                )
                msg = resp.choices[0].message

                # 모델이 추가 tool_calls를 요청한 경우 실행 후 2차 응답 생성
                if getattr(msg, "tool_calls", None):
                    oai_messages.append(msg)
                    for tc in msg.tool_calls:
                        fn_name = tc.function.name
                        fn_args = json.loads(tc.function.arguments or "{}")
                        fn_res = self.execute_tool(fn_name, fn_args)
                        tool_outputs.append({
                            "tool": fn_name,
                            "arguments": fn_args,
                            "reason": "OpenAI GPT 모델이 실시간 추가 검증을 위해 직접 Function Calling 요청",
                            "data": fn_res,
                        })
                        oai_messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(fn_res, ensure_ascii=False),
                        })
                    resp2 = client.chat.completions.create(
                        model=settings.OPENAI_MODEL,
                        messages=oai_messages,
                        max_tokens=900,
                        temperature=0.3,
                    )
                    reply_text = resp2.choices[0].message.content or ""
                else:
                    reply_text = msg.content or ""

                model_used = f"OpenAI ({settings.OPENAI_MODEL})"
            except Exception as e:
                print(f"[AIService] OpenAI 호출 폴백 전환: {e}")

        # B. Gemini 3.6 Flash API 호출 (OpenAI 키가 sk- 형식이 아니거나 한도 초과 시 자동 동작)
        if not reply_text and self.gemini_key:
            try:
                from google import genai
                gclient = genai.Client(api_key=self.gemini_key)
                conv_context = ""
                for m in history_messages[-6:]:
                    role_kr = "사용자" if m["role"] == "user" else "AI 비서"
                    conv_context += f"{role_kr}: {m['content']}\n"

                full_prompt = (
                    f"{system_prompt}\n\n"
                    f"[이전 대화 맥락]\n{conv_context if conv_context else '(첫 질문)'}\n\n"
                    f"[사용자 질문]\n{user_message}\n\n"
                    "위 [사용자 데이터 요약]과 [도구 호출 상세 조회 결과]의 수치를 정확히 인용하여 한국어로 친절하고 체계적으로 답변하세요."
                )
                gresp = gclient.models.generate_content(
                    model=settings.GEMINI_MODEL,
                    contents=full_prompt,
                )
                if gresp and gresp.text:
                    reply_text = gresp.text.strip()
                    model_used = f"AI Engine ({settings.GEMINI_MODEL} + Function Calling)"
            except Exception as e:
                print(f"[AIService] Gemini 호출 폴백 전환: {e}")

        # C. 내장 정밀 데이터 분석 엔진 (네트워크 오프라인/쿼터 초과 시에도 100% 정확한 데이터 기반 답변 보장)
        if not reply_text:
            reply_text = self._generate_analytical_fallback(user_message, summary, tool_outputs)
            model_used = "Data-Aware Analytical Engine (Local Context + Tools)"

        # 4. 대화 내용을 Firestore 'conversations'에 자동 저장 (요구사항 7-4)
        ts = now_iso()
        compact_tools = [
            {
                "tool": t["tool"],
                "arguments": t["arguments"],
                "reason": t["reason"],
            }
            for t in tool_outputs
        ]
        updated_messages = list(history_messages) + [
            {"role": "user", "content": user_message, "timestamp": ts, "tool_calls": []},
            {"role": "assistant", "content": reply_text, "timestamp": ts, "tool_calls": compact_tools},
        ]
        saved_conv = firebase_service.save_conversation(
            messages=updated_messages,
            conv_id=conversation_id,
        )

        return {
            "reply": reply_text,
            "conversation_id": saved_conv["id"],
            "conversation_title": saved_conv["title"],
            "summary_injected": summary,
            "tool_calls_used": compact_tools,
            "model_used": model_used,
        }

    def _generate_analytical_fallback(
        self,
        user_message: str,
        summary: SummaryResponse,
        tool_outputs: List[Dict[str, Any]],
    ) -> str:
        adv = analytics_service.get_advanced_statistics()
        yearly = adv.get("yearly_statistics", {})
        seasonal = adv.get("seasonal_statistics", {})
        forecast = adv.get("forecast_next_4_weeks", [])
        outliers = adv.get("outliers", [])[:3]

        lines = [
            f"### 📊 전국 119 신고접수 데이터 기반 맞춤 분석",
            f"현재 저장된 **{summary.period}** 기간(총 **{summary.count}개** 주간 데이터 포인트)을 기반으로 분석한 결과입니다.",
            "",
            "#### 1. 핵심 지표 요약 (Context Injection)",
            f"- **전체 누적 신고**: **{summary.metrics.total:,.0f}건** (주간 평균 **{summary.metrics.average:,.0f}건**)",
            f"- **최고 피크 시점**: **{summary.metrics.max_date}** (**{summary.metrics.max:,.0f}건**)",
            f"- **최저 시점**: **{summary.metrics.min_date}** (**{summary.metrics.min:,.0f}건**)",
            f"- **최근 트렌드**: **{summary.trend}** (최근 8주 평균 **{summary.recent_average:,.0f}건**)",
            "",
        ]

        if seasonal:
            lines.append("#### 2. 계절별·연도별 패턴 분석")
            s_parts = [f"**{k}** 평균 {v['average']:,.0f}건(최대 {v['max']:,.0f}건)" for k, v in seasonal.items()]
            lines.append("- **계절별 주간 평균**: " + " | ".join(s_parts))
        if yearly:
            y_parts = [f"**{k}년** 평균 {v['average']:,.0f}건" for k, v in yearly.items()]
            lines.append("- **연도별 주간 평균**: " + " | ".join(y_parts))

        if outliers:
            lines.append("")
            lines.append("#### 3. 주요 이상치(급증/급감) 및 현장도착 인사이트")
            for o in outliers:
                lines.append(f"- **{o['date']} ({o['type']}, Z={o['z_score']})**: **{o['value']:,.0f}건** — {o['memo']}")

        if forecast:
            lines.append("")
            lines.append("#### 4. 향후 4주 단기 예측 및 권장 액션")
            f_parts = [f"{f['step']} **{f['predicted_value']:,.0f}건**" for f in forecast]
            lines.append("- **베이스라인 예측**: " + " → ".join(f_parts))
            lines.append("- **권장 대응**: 경기도·서울 등 수도권 집중 지역 및 피크 시간대(09시~16시) 구급대 탄력 배치를 통해 평균 현장도착 시간(9~11분)을 단축하는 것을 권장합니다.")

        return "\n".join(lines)


ai_service = AIService()
