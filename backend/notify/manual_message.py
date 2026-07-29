"""Send one Apps in Toss Smart Message test notification.

This script is separate from the scheduler. It only sends when run explicitly,
and always uses the fixed morning-notification template.
"""

import json
import os
from typing import Any

import requests

TEMPLATE_SET_CODE = "need-umbrella-NEED_UMBRELLA_MORNING"
TEST_MESSAGE_PATH = "/api-partner/v1/apps-in-toss/messenger/send-test-message"
TOSS_API_BASE = os.getenv("TOSS_API_BASE_URL", "https://apps-in-toss-api.toss.im")


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} must be configured")
    return value


def recipient_header() -> dict[str, str]:
    user_key = os.getenv("TOSS_TEST_USER_KEY")
    anon_key = os.getenv("TOSS_TEST_ANON_KEY")
    if bool(user_key) == bool(anon_key):
        raise ValueError("Configure exactly one of TOSS_TEST_USER_KEY or TOSS_TEST_ANON_KEY")
    return {"x-toss-user-key": user_key} if user_key else {"x-anon-key": anon_key}


def message_context() -> dict[str, Any]:
    raw_context = os.getenv("TOSS_TEST_MESSAGE_CONTEXT") or "{}"
    try:
        context = json.loads(raw_context)
    except json.JSONDecodeError as error:
        raise ValueError("TOSS_TEST_MESSAGE_CONTEXT must be valid JSON") from error
    if not isinstance(context, dict):
        raise ValueError("TOSS_TEST_MESSAGE_CONTEXT must be a JSON object")
    return context


def build_request() -> tuple[dict[str, str], dict[str, Any], tuple[str, str]]:
    headers = {"Content-Type": "application/json", **recipient_header()}
    body = {
        "templateSetCode": TEMPLATE_SET_CODE,
        "deploymentId": required_env("TOSS_TEST_DEPLOYMENT_ID"),
        "context": message_context(),
    }
    certificate = (required_env("TOSS_MTLS_CERT_PATH"), required_env("TOSS_MTLS_KEY_PATH"))
    return headers, body, certificate


def send_test_message() -> dict[str, Any]:
    headers, body, certificate = build_request()
    response = requests.post(
        f"{TOSS_API_BASE}{TEST_MESSAGE_PATH}",
        headers=headers,
        json=body,
        cert=certificate,
        timeout=10,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"rawResponse": response.text}
    if not response.ok or payload.get("resultType") != "SUCCESS":
        raise RuntimeError(f"Toss test message request failed ({response.status_code}): {payload}")
    return payload
