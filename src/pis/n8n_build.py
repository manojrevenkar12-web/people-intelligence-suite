"""Build the two n8n workflows from code, so they are reviewed and versioned like code.

1. People self-service: a chat platform posts the question to a webhook; the workflow asks the API and
   replies; handoffs open a ticket in the People team's queue.
2. Payroll sync: every weekday morning, read the change plan, send mechanical fixes to the payroll
   provider with an idempotency key, send judgements to the People team, and acknowledge each item.

Credentials are referenced by name only; secrets live in n8n's credential store, not in these files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pis.settings import ROOT

OUT = ROOT / "n8n" / "workflows"


def node(
    name: str, type_: str, version: float, x: int, y: int, params: dict[str, Any], creds: dict[str, Any] | None = None
) -> dict[str, Any]:
    n = {
        "id": name.lower().replace(" ", "-"),
        "name": name,
        "type": type_,
        "typeVersion": version,
        "position": [x, y],
        "parameters": params,
    }
    if creds:
        n["credentials"] = creds
    return n


def link(*names: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for a, b in zip(names, names[1:]):
        out.setdefault(a, {"main": [[]]})["main"][0].append({"node": b, "type": "main", "index": 0})
    return out


API = "={{ $env.PIS_API_URL }}"
API_AUTH = {"httpHeaderAuth": {"id": "pisApiToken", "name": "people-intelligence API token"}}


def self_service(helpdesk: str = "={{ $env.HELPDESK_URL }}") -> dict[str, Any]:
    nodes = [
        node(
            "Question in",
            "n8n-nodes-base.webhook",
            2,
            0,
            0,
            {
                "httpMethod": "POST",
                "path": "people-help",
                "responseMode": "responseNode",
                "authentication": "headerAuth",
            },
            {"httpHeaderAuth": {"id": "chatWebhookSecret", "name": "chat webhook secret"}},
        ),
        node(
            "Ask the assistant",
            "n8n-nodes-base.httpRequest",
            4.2,
            240,
            0,
            {
                "method": "POST",
                "url": API + "/ask",
                "authentication": "genericCredentialType",
                "genericAuthType": "httpHeaderAuth",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify({ email: $json.body.user.email, question: $json.body.text }) }}",
                "options": {"timeout": 10000},
            },
            API_AUTH,
        ),
        node(
            "Needs a person?",
            "n8n-nodes-base.if",
            2,
            480,
            0,
            {
                "conditions": {
                    "options": {"caseSensitive": True},
                    "combinator": "and",
                    "conditions": [
                        {
                            "leftValue": "={{ $json.kind }}",
                            "rightValue": "handoff",
                            "operator": {"type": "string", "operation": "equals"},
                        }
                    ],
                }
            },
        ),
        node(
            "Open People ticket",
            "n8n-nodes-base.httpRequest",
            4.2,
            720,
            -120,
            {
                "method": "POST",
                "url": helpdesk + "/tickets",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify({ queue: $json.queue, reason: $json.reason, "
                "requester: $('Question in').item.json.body.user.email, "
                "text: $('Question in').item.json.body.text }) }}",
                "options": {"retry": {"maxTries": 3}},
            },
        ),
        node(
            "Reply",
            "n8n-nodes-base.respondToWebhook",
            1.1,
            960,
            0,
            {
                "respondWith": "json",
                "responseBody": "={{ JSON.stringify({ text: $('Ask the assistant').item.json.text, "
                "citations: $('Ask the assistant').item.json.citations, "
                "kind: $('Ask the assistant').item.json.kind }) }}",
            },
        ),
    ]
    connections = {
        "Question in": {"main": [[{"node": "Ask the assistant", "type": "main", "index": 0}]]},
        "Ask the assistant": {"main": [[{"node": "Needs a person?", "type": "main", "index": 0}]]},
        "Needs a person?": {
            "main": [
                [{"node": "Open People ticket", "type": "main", "index": 0}],
                [{"node": "Reply", "type": "main", "index": 0}],
            ]
        },
        "Open People ticket": {"main": [[{"node": "Reply", "type": "main", "index": 0}]]},
    }
    return {
        "id": "peopleSelfService",
        "name": "People self-service",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1", "saveDataSuccessExecution": "none"},
        "active": False,
    }


def payroll_sync(
    provider: str = "={{ $env.PAYROLL_API_URL }}", helpdesk: str = "={{ $env.HELPDESK_URL }}"
) -> dict[str, Any]:
    nodes = [
        node(
            "Weekday 06:30",
            "n8n-nodes-base.scheduleTrigger",
            1.2,
            0,
            0,
            {"rule": {"interval": [{"field": "cronExpression", "expression": "30 6 * * 1-5"}]}},
        ),
        node(
            "Read change plan",
            "n8n-nodes-base.httpRequest",
            4.2,
            240,
            0,
            {
                "method": "GET",
                "url": API + "/sync/plan",
                "authentication": "genericCredentialType",
                "genericAuthType": "httpHeaderAuth",
            },
            API_AUTH,
        ),
        node("One item each", "n8n-nodes-base.splitOut", 1, 480, 0, {"fieldToSplitOut": "items"}),
        node(
            "Mechanical fix?",
            "n8n-nodes-base.if",
            2,
            720,
            0,
            {
                "conditions": {
                    "options": {"caseSensitive": True},
                    "combinator": "and",
                    "conditions": [
                        {
                            "leftValue": "={{ $json.route }}",
                            "rightValue": "payroll",
                            "operator": {"type": "string", "operation": "equals"},
                        }
                    ],
                }
            },
        ),
        node(
            "Send to payroll provider",
            "n8n-nodes-base.httpRequest",
            4.2,
            960,
            -120,
            {
                "method": "POST",
                "url": provider + "/change-requests",
                "sendHeaders": True,
                "headerParameters": {"parameters": [{"name": "Idempotency-Key", "value": "={{ $json.key }}"}]},
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify($json) }}",
                "options": {"retry": {"maxTries": 3, "waitBetweenTries": 2000}},
            },
            {"httpHeaderAuth": {"id": "payrollApi", "name": "payroll provider API"}},
        ),
        node(
            "Send to People team",
            "n8n-nodes-base.httpRequest",
            4.2,
            960,
            120,
            {
                "method": "POST",
                "url": helpdesk + "/tickets",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify({ queue: 'people-ops', action: $json.action, "
                "employee: $json.employee_id, reason: $json.reason, key: $json.key }) }}",
            },
        ),
        node(
            "Acknowledge",
            "n8n-nodes-base.httpRequest",
            4.2,
            1200,
            0,
            {
                "method": "POST",
                "url": API + "/sync/ack",
                "authentication": "genericCredentialType",
                "genericAuthType": "httpHeaderAuth",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify({ key: $('One item each').item.json.key, "
                "outcome: $('One item each').item.json.route === 'payroll' ? 'sent' : 'queued', "
                "reference: $json.id || null }) }}",
            },
            API_AUTH,
        ),
    ]
    connections = {
        "Weekday 06:30": {"main": [[{"node": "Read change plan", "type": "main", "index": 0}]]},
        "Read change plan": {"main": [[{"node": "One item each", "type": "main", "index": 0}]]},
        "One item each": {"main": [[{"node": "Mechanical fix?", "type": "main", "index": 0}]]},
        "Mechanical fix?": {
            "main": [
                [{"node": "Send to payroll provider", "type": "main", "index": 0}],
                [{"node": "Send to People team", "type": "main", "index": 0}],
            ]
        },
        "Send to payroll provider": {"main": [[{"node": "Acknowledge", "type": "main", "index": 0}]]},
        "Send to People team": {"main": [[{"node": "Acknowledge", "type": "main", "index": 0}]]},
    }
    return {
        "id": "payrollSync",
        "name": "Payroll sync",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
        "active": False,
    }


def build(out: Path = OUT) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for wf in (self_service(), payroll_sync()):
        p = out / f"{wf['id']}.json"
        p.write_text(json.dumps(wf, indent=2) + "\n")
        paths.append(p)
    return paths
