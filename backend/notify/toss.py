# backend/notify/toss.py
# 토스 파트너 스마트 메시지 대량 발송 API 통신 모듈
#
# 발송 문구는 토스 콘솔에 등록하고 검수 승인을 받은 템플릿에 고정되어 있습니다.
# 파트너 서버는 templateSetCode로 템플릿을 지정하고, context로 템플릿 변수만 채웁니다.

import os
from datetime import datetime
from typing import Dict, Any, List

import requests

TOSS_API_BASE_URL = os.environ.get("TOSS_API_BASE_URL", "https://apps-in-toss-api.toss.im")
BULK_MESSAGE_PATH = "/api-partner/v1/apps-in-toss/messenger/send-bulk-message"

# 대량 발송 API는 한 번에 최대 2,500건까지 허용합니다.
MAX_BULK_RECIPIENTS = 2500

REQUEST_TIMEOUT_SECONDS = 15

# 유스케이스별 토스 콘솔 발송코드(templateSetCode) 매핑
USE_CASE_TEMPLATE_CODES: Dict[str, str] = {
    "morning": "need-umbrella-NEED_UMBRELLA_MORNING",
    "preRain": "need-umbrella-NEED_UMBRELLA_PRE_RAIN",
    "evening": "need-umbrella-NEED_UMBRELLA_EVENING",
    "alert": "need-umbrella-NEED_UMBRELLA_ALERT",
    "weekend": "need-umbrella-NEED_UMBRELLA_WEEKEND",
}


def template_code_for(use_case: str) -> str:
    """유스케이스에 대응하는 콘솔 등록 템플릿 코드"""
    return USE_CASE_TEMPLATE_CODES.get(
        use_case, f"need-umbrella-NEED_UMBRELLA_{use_case.upper()}"
    )


def build_message_context(item: Dict[str, Any]) -> Dict[str, Any]:
    """콘솔 템플릿의 유스케이스별 동적 변수값을 만듭니다."""
    context = {"notificationLocationName": item.get("notificationLocationName", "")}
    use_case = item.get("useCase")

    if use_case in ("morning", "evening"):
        context["preparationNames"] = join_preparation_names(item.get("preparationNames") or [])
    elif use_case == "preRain":
        context["rainStartTime"] = format_korean_time(item.get("rainStartTime"))
    elif use_case == "alert":
        context["alertEvent"] = item.get("alertEvent", "")
    elif use_case == "weekend":
        date_and_time = item.get("weekendRainStart") or ()
        context["weekendRainStart"] = (
            format_weekend_rain_start(*date_and_time)
            if len(date_and_time) == 2 else ""
        )

    return context


def join_preparation_names(names: List[str]) -> str:
    """조사가 필요 없는 한국어 준비물 목록으로 조합합니다."""
    return ", ".join(name for name in names if name)


def format_korean_time(raw_time: Any) -> str:
    """HH:MM 시각을 알림용 한국어 시각으로 변환합니다."""
    try:
        hour_text, minute_text = str(raw_time).split(":")[:2]
        hour, minute = int(hour_text), int(minute_text)
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError
    except (ValueError, TypeError):
        return ""

    period = "오전" if hour < 12 else "오후"
    hour_12 = hour % 12 or 12
    return f"{period} {hour_12}시" if minute == 0 else f"{period} {hour_12}시 {minute}분"


def format_weekend_rain_start(date: Any, raw_time: Any) -> str:
    """YYYY-MM-DD와 HH:MM을 '토요일 오후 2시' 형식으로 변환합니다."""
    try:
        weekday = ("월", "화", "수", "목", "금", "토", "일")[datetime.fromisoformat(str(date)).weekday()]
    except (ValueError, TypeError):
        return ""
    time = format_korean_time(raw_time)
    return f"{weekday}요일 {time}" if time else ""


def build_bulk_payload(use_case: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    대량 발송 요청 바디를 만듭니다.
    수신자는 헤더가 아니라 contextList 항목의 anonKey로 전달합니다.
    """
    return {
        "templateSetCode": template_code_for(use_case),
        "contextList": [
            {
                # 유저 문서 ID가 곧 토스 사용자 식별키(anonKey)입니다.
                "anonKey": str(item["userKey"]),
                "context": build_message_context(item),
            }
            for item in items
        ],
    }


def real_send_enabled() -> bool:
    """실발송 스위치. 기본값은 꺼짐이며, 꺼져 있으면 모의 발송만 수행합니다."""
    return os.environ.get("ENABLE_REAL_TOSS_PUSH", "false").lower() == "true"


def toss_mtls_certificate():
    """서버 간 통신에 필요한 mTLS 클라이언트 인증서 경로. 미설정 시 None."""
    cert_path = os.environ.get("TOSS_MTLS_CERT_PATH")
    key_path = os.environ.get("TOSS_MTLS_KEY_PATH")
    if not cert_path or not key_path:
        return None
    return cert_path, key_path


def _chunk(items: List[Dict[str, Any]], size: int):
    for offset in range(0, len(items), size):
        yield items[offset:offset + size]


def send_bulk_message_batch(use_case: str, items: List[Dict[str, Any]]) -> bool:
    """
    단일 배치(최대 2,500건)를 토스 대량 발송 API로 전송합니다.
    HTTP 200이어도 resultType이 SUCCESS가 아니면 실패로 처리합니다.
    """
    payload = build_bulk_payload(use_case, items)

    certificate = toss_mtls_certificate()
    if certificate is None:
        print("[SmartMessage Configuration Error] TOSS_MTLS_CERT_PATH and TOSS_MTLS_KEY_PATH are required for real delivery.")
        return False

    try:
        response = requests.post(
            f"{TOSS_API_BASE_URL}{BULK_MESSAGE_PATH}",
            json=payload,
            headers={"Content-Type": "application/json"},
            cert=certificate,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as err:
        print(f"[SmartMessage Network Error] {use_case} x{len(items)}: {err}")
        return False

    try:
        body = response.json()
    except ValueError:
        body = {"rawResponse": response.text}

    if not response.ok or body.get("resultType") != "SUCCESS":
        print(f"[SmartMessage API Failed] {use_case} x{len(items)} | Status: {response.status_code} | Body: {body}")
        return False

    # 알림 미동의/철회 유저는 토스 서버가 자동으로 제외하므로
    # 발송 건수가 요청 건수보다 적을 수 있습니다. 이는 실패가 아닙니다.
    sent = body.get("success", {}).get("msgCount", 0)
    print(f"[SmartMessage Success] {use_case} | requested: {len(items)} | sent: {sent}")
    return True


def send_bulk_smart_messages(dispatch_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    유스케이스별로 묶어 대량 발송한 뒤, 성공한 발송 항목을 반환합니다.
    대량 발송 API는 템플릿 코드 하나당 한 번 호출하므로 유스케이스 단위로 그룹핑합니다.
    응답이 수신자별 성공 여부를 알려주지 않기 때문에 성공/실패는 배치 단위로 판정합니다.
    """
    success_count = 0
    fail_count = 0
    succeeded_items: List[Dict[str, Any]] = []

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in dispatch_list:
        grouped.setdefault(item["useCase"], []).append(item)

    enable_real_send = real_send_enabled()

    for use_case, items in grouped.items():
        for batch in _chunk(items, MAX_BULK_RECIPIENTS):
            # 실발송 옵션이 켜져있지 않은 경우(기본값) 안전하게 모의 발송(Mock Dispatch) 처리
            if not enable_real_send:
                print(f"[SmartMessage Mock Dispatch] {use_case} | Code: {template_code_for(use_case)} | Recipients: {len(batch)}")
                ok = True
            else:
                ok = send_bulk_message_batch(use_case, batch)

            if ok:
                success_count += len(batch)
                succeeded_items.extend(batch)
            else:
                fail_count += len(batch)

    return {
        "success": success_count,
        "fail": fail_count,
        "total": len(dispatch_list),
        "succeededItems": succeeded_items,
    }
