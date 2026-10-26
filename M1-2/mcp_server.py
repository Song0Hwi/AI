"""
[보너스 과제 1] MCP (Model Context Protocol) 서버 & 멀티채널 도구 연동 모듈 (mcp_server.py)
- JSON-RPC 2.0 기반 MCP 프로토콜(initialize, tools/list, tools/call)을 지원합니다.
- 표준 입출력(stdio) 모드 및 FastAPI의 HTTP 엔드포인트(/api/mcp) 양쪽에서 동작합니다.
- 실행 검증: `python mcp_server.py --self-test`
"""
import sys
import json
from typing import Dict, Any

from services.ai_service import ai_service, OPENAI_TOOLS_SCHEMA

sys.stdout.reconfigure(encoding="utf-8")


def get_mcp_tools_list() -> list[Dict[str, Any]]:
    mcp_tools = []
    for t in OPENAI_TOOLS_SCHEMA:
        fn = t["function"]
        mcp_tools.append({
            "name": fn["name"],
            "description": fn["description"],
            "inputSchema": fn["parameters"],
        })
    return mcp_tools


def handle_mcp_jsonrpc(request_obj: Dict[str, Any]) -> Dict[str, Any]:
    """MCP JSON-RPC 2.0 요청을 처리하고 응답 객체를 반환합니다."""
    req_id = request_obj.get("id", 1)
    method = request_obj.get("method", "")
    params = request_obj.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {
                    "name": "m1-2-119-timeseries-mcp-server",
                    "version": "1.0.0",
                },
                "capabilities": {"tools": {"listChanged": False}},
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": get_mcp_tools_list()},
        }

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments") or {}
        output = ai_service.execute_tool(tool_name, arguments)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(output, ensure_ascii=False, indent=2),
                    }
                ],
                "isError": "error" in output,
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def run_self_test():
    print("=== [MCP Server 멀티채널 호출 흐름 검증 테스트] ===")
    init_res = handle_mcp_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    print("1. initialize:", init_res["result"]["serverInfo"])

    list_res = handle_mcp_jsonrpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tool_names = [t["name"] for t in list_res["result"]["tools"]]
    print("2. tools/list:", tool_names)

    call_res = handle_mcp_jsonrpc({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "get_data_summary", "arguments": {}},
    })
    summary_data = json.loads(call_res["result"]["content"][0]["text"])
    print("3. tools/call (get_data_summary):", {
        "period": summary_data["period"],
        "count": summary_data["count"],
        "trend": summary_data["trend"],
    })
    print("=== [MCP 검증 성공] ===")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        run_self_test()
    else:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                res = handle_mcp_jsonrpc(req)
                print(json.dumps(res, ensure_ascii=False), flush=True)
            except Exception as exc:
                err_res = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": str(exc)},
                }
                print(json.dumps(err_res, ensure_ascii=False), flush=True)
