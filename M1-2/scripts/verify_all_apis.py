"""
M1-2 전체 API 엔드포인트, Firestore CRUD, AI 컨텍스트 주입 + Function Calling, MCP 멀티채널 통합 검증 스크립트
"""
import os
import sys
import json

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app
from mcp_server import run_self_test


def main():
    client = TestClient(app)

    print("1. [GET /api/health] 헬스체크 및 Firestore 연결 확인")
    r = client.get("/api/health")
    assert r.status_code == 200, r.text
    health = r.json()
    print("  ->", health)
    assert health["firestore_connected"] is True
    assert health["data_count"] >= 100

    print("\n2. [GET /api/data/summary] 데이터 요약 조회")
    r = client.get("/api/data/summary")
    assert r.status_code == 200, r.text
    summary = r.json()
    print("  -> period:", summary["period"], "| count:", summary["count"], "| trend:", summary["trend"])
    assert summary["count"] >= 100

    print("\n3. [GET /api/data/statistics] 보너스 확장 통계 조회")
    r = client.get("/api/data/statistics")
    assert r.status_code == 200, r.text
    stats = r.json()
    print("  -> seasonal keys:", list(stats["seasonal_statistics"].keys()), "| outliers:", stats["outliers_count"])

    print("\n4. [POST/GET/PUT/DELETE /api/data] 데이터 CRUD 전체 검증")
    r_post = client.post(
        "/api/data",
        json={
            "date": "2025-09-22",
            "value": 268400,
            "memo": "[가을] 전국 119 주간 접수 테스트 | 최다: 경기도(21.2%)·서울(17.5%)",
        },
    )
    assert r_post.status_code == 201, r_post.text
    created_item = r_post.json()
    item_id = created_item["id"]
    print("  -> Created ID:", item_id)

    r_put = client.put(
        f"/api/data/{item_id}",
        json={"value": 271900, "memo": "[가을·수정됨] 전국 119 주간 접수 | 최다: 경기도(21.5%)"},
    )
    assert r_put.status_code == 200, r_put.text
    assert r_put.json()["value"] == 271900
    print("  -> Updated value:", r_put.json()["value"])

    r_del = client.delete(f"/api/data/{item_id}")
    assert r_del.status_code == 200, r_del.text
    print("  -> Deleted ID:", item_id)

    print("\n5. [POST /api/chat] AI 데이터 비서 대화 (컨텍스트 주입 + Function Calling + 자동 저장)")
    r_chat = client.post(
        "/api/chat",
        json={
            "message": "이번 달(최근) 119 신고접수 추세가 어때? 그리고 가장 신고가 많았던 때는 언제야?",
            "use_tools": True,
        },
    )
    assert r_chat.status_code == 200, r_chat.text
    chat_res = r_chat.json()
    print("  -> Model used:", chat_res["model_used"])
    print("  -> Conversation ID:", chat_res["conversation_id"])
    print("  -> Tools called:", [t["tool"] for t in chat_res["tool_calls_used"]])
    print("  -> Reply preview:\n", chat_res["reply"][:350], "...\n")

    print("6. [GET /api/conversations/{id}] 저장된 대화 불러오기 검증")
    conv_id = chat_res["conversation_id"]
    r_conv = client.get(f"/api/conversations/{conv_id}")
    assert r_conv.status_code == 200, r_conv.text
    print("  -> Loaded messages count:", len(r_conv.json()["messages"]))

    print("\n7. [POST /api/mcp & CLI] 보너스 MCP 멀티채널 도구 호출 검증")
    run_self_test()
    r_mcp = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {
                "name": "search_timeseries_data",
                "arguments": {"sort_by": "value_desc", "limit": 3},
            },
        },
    )
    assert r_mcp.status_code == 200, r_mcp.text
    print("  -> HTTP /api/mcp response OK!")
    print("\n✅ 모든 필수 및 보너스 요구사항 검증 통과!")


if __name__ == "__main__":
    main()
