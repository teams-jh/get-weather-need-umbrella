# backend/toss_smart_message.py
# 토스 파트너 스마트 메시지 API 통신 및 메시지 포맷팅 모듈

import os
import json
import requests
from typing import Dict, Any, List, Optional

# 토스 파트너 메시지 API 공식 Endpoint
TOSS_SMART_MESSAGE_API_URL = os.environ.get(
    "TOSS_SMART_MESSAGE_API_URL",
    "https://apps-in-toss-api.toss.im/api-partner/v1/apps-in-toss/messenger/send-message"
)

TOSS_SMART_MESSAGE_BULK_API_URL = os.environ.get(
    "TOSS_SMART_MESSAGE_BULK_API_URL",
    "https://apps-in-toss-api.toss.im/api-partner/v1/apps-in-toss/messenger/send-bulk-message"
)

# 5가지 유스케이스별 알림 메시지 및 토스 콘솔 발송코드(templateCode) 매핑
USE_CASE_TEMPLATES: Dict[str, Dict[str, str]] = {
    "morning": {
        "templateCode": "NEED_UMBRELLA_MORNING",
        "title": "아침 알림",
        "body": "오늘은 비 소식, 출근길 우산 챙겨봐요.",
    },
    "preRain": {
        "templateCode": "NEED_UMBRELLA_PRE_RAIN",
        "title": "비 돌발 알림",
        "body": "약 1시간 뒤 비가 시작돼요.",
    },
    "evening": {
        "templateCode": "NEED_UMBRELLA_EVENING",
        "title": "퇴근 알림",
        "body": "퇴근길 비 소식이 있어요.",
    },
    "alert": {
        "templateCode": "NEED_UMBRELLA_ALERT",
        "title": "기상 특보 알림",
        "body": "기상특보 발령. 안전에 유의해봐요.",
    },
    "weekend": {
        "templateCode": "NEED_UMBRELLA_WEEKEND",
        "title": "주말 알림",
        "body": "이번 주말 비 예보가 있어요. 우산 챙겨봐요.",
    },
}

def format_notification_payload(
    user_key: str,
    use_case: str,
    location_name: str = "서울 강남"
) -> Dict[str, Any]:
    """유저 식별키와 유스케이스별 스마트 메시지 요청 페이로드 생성"""
    template = USE_CASE_TEMPLATES.get(use_case, {
        "templateCode": f"NEED_UMBRELLA_{use_case.upper()}",
        "title": "☂️ 오늘 우산 필요 알림",
        "body": f"[{location_name}] 비 소식이 있으니 우산을 챙기세요!"
    })

    return {
        "userKey": user_key,
        "templateCode": template["templateCode"],
        "context": {
            "locationName": location_name,
            "title": template["title"],
            "body": template["body"]
        }
    }

def send_smart_message(payload: Dict[str, Any]) -> bool:
    """
    토스 파트너 스마트 메시지 단건 발송 API 호출
    `x-toss-user-key` 헤더를 기반으로 전달합니다.
    """
    user_key = payload.get("userKey", "")
    enable_real_send = os.environ.get("ENABLE_REAL_TOSS_PUSH", "false").lower() == "true"

    # 실발송 옵션이 켜져있지 않은 경우(기본값) 안전하게 모의 발송(Mock Dispatch) 처리
    if not enable_real_send:
        try:
            print(f"[SmartMessage Mock Dispatch] To: {user_key} | Code: {payload['templateCode']} | Title: {payload['context']['title']}")
        except UnicodeEncodeError:
            print(f"[SmartMessage Mock Dispatch] To: {user_key} | Code: {payload.get('templateCode')}")
        return True

    headers = {
        "Content-Type": "application/json",
        "x-toss-user-key": str(user_key)
    }

    body_data = {
        "templateSetCode": payload["templateCode"],
        "context": payload.get("context", {})
    }

    try:
        response = requests.post(TOSS_SMART_MESSAGE_API_URL, json=body_data, headers=headers, timeout=5)
        if response.status_code == 200:
            print(f"[SmartMessage Success] User: {user_key} | Code: {payload['templateCode']}")
            return True
        else:
            print(f"[SmartMessage API Failed] Status: {response.status_code} | Body: {response.text}")
            return False
    except Exception as err:
        print(f"[SmartMessage Network Error] {err}")
        return False

def send_bulk_smart_messages(dispatch_list: List[Dict[str, Any]]) -> Dict[str, int]:
    """일괄 알림 발송 처리 및 통계 반환"""
    success_count = 0
    fail_count = 0

    for item in dispatch_list:
        payload = format_notification_payload(
            user_key=item["userKey"],
            use_case=item["useCase"],
            location_name=item.get("locationName", "지정 지역")
        )
        ok = send_smart_message(payload)
        if ok:
            success_count += 1
        else:
            fail_count += 1

    return {"success": success_count, "fail": fail_count, "total": len(dispatch_list)}
