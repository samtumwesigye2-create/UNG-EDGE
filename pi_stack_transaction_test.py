#!/usr/bin/env python3
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone

EDGE = "http://127.0.0.1:8080"
CORE = "http://127.0.0.1:8101"
ORACLE = "http://127.0.0.1:8113"


def get_json(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, json.loads(r.read().decode())


def post_json(url, body, headers=None):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers=h,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = r.read().decode()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            body = json.loads(raw)
        except Exception:
            body = {"raw": raw}
        return e.code, body


def main():
    result = {
        "test": "EDGE-CORE-ORACLE-PHYSICAL",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    edge_status, edge = get_json(EDGE + "/health")
    core_status, core = get_json(CORE + "/health")
    oracle_status, oracle = get_json(ORACLE + "/health")
    result["health"] = {
        "edge": {"http": edge_status, "body": edge},
        "core": {"http": core_status, "body": core},
        "oracle": {"http": oracle_status, "body": oracle},
    }

    analysis_request = {
        "items": [
            {
                "item_code": "EDGE-TEST-001",
                "description": "Physical edge integration sample",
                "annual_usage_qty": 120,
                "unit_price": 15.5,
            },
            {
                "item_code": "EDGE-TEST-002",
                "description": "Physical edge integration sample B",
                "annual_usage_qty": 40,
                "unit_price": 8.0,
            },
        ]
    }
    oracle_http, oracle_analysis = post_json(ORACLE + "/v1/abc/analyze", analysis_request)
    result["oracle_transaction"] = {"http": oracle_http, "body": oracle_analysis}

    edge_event = {
        "topic": "EDGE.CORE.ORACLE.TEST",
        "target_system": "UNG-ORACLE",
        "priority": 1,
        "payload": {
            "core_health": core,
            "oracle_analysis": oracle_analysis,
            "source_node": edge.get("node_id", "ung-edge-001"),
        },
    }
    edge_http, edge_record = post_json(EDGE + "/v1/events", edge_event)
    result["edge_record"] = {"http": edge_http, "body": edge_record}

    core_publish = {
        "event_type": "EDGE_INTEGRATION_TEST",
        "target_system": "UNG-ORACLE",
        "payload": {
            "edge_event_id": edge_record.get("event_id"),
            "oracle_status": oracle_http,
            "source_node": edge.get("node_id", "ung-edge-001"),
        },
        "correlation_id": edge_record.get("event_id"),
        "max_attempts": 3,
    }
    core_http, core_body = post_json(CORE + "/v1/event-delivery/publish", core_publish)
    result["core_publish"] = {"http": core_http, "body": core_body}

    result["summary"] = {
        "edge_healthy": edge_status == 200,
        "core_healthy": core_status == 200,
        "oracle_healthy": oracle_status == 200,
        "oracle_transaction_ok": 200 <= oracle_http < 300,
        "edge_record_ok": 200 <= edge_http < 300,
        "core_publish_ok": 200 <= core_http < 300,
        "core_publish_note": "CORE event publish requires IAM bearer authentication" if core_http == 401 else None,
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
