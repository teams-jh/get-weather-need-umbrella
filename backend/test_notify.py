# backend/test_notify.py
import pytest
from datetime import datetime, timezone, timedelta
from notify_scheduler import is_ad_pass_valid, should_send_notification, process_notifications_for_users
from toss_smart_message import format_notification_payload, send_bulk_smart_messages

KST = timezone(timedelta(hours=9))

def test_is_ad_pass_valid():
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    
    # 7일 후 만료
    valid_expires = (now + timedelta(days=7)).isoformat()
    assert is_ad_pass_valid(valid_expires, now) is True

    # 어제 만료
    expired_iso = (now - timedelta(days=1)).isoformat()
    assert is_ad_pass_valid(expired_iso, now) is False

def test_notification_deduplication_by_type():
    now = datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc) # 17:00 KST
    kst_now = now.astimezone(KST)
    today_str = kst_now.strftime("%Y-%m-%d")

    user_doc = {
        "userKey": "test_user_01",
        "locationId": "SEOUL_GANGNAM",
        "isNotificationEnabled": True,
        "notificationTypes": {
            "morning": True,
            "preRain": True,
            "evening": True,
            "alert": True,
            "weekend": True,
        },
        "adPass": {
            "expiresAt": (now + timedelta(days=5)).isoformat()
        },
        "lastNotified": {
            "morning": today_str, # 아침 알림은 오늘 이미 수신함
        }
    }

    weather_umbrella = {
        "recommendation": {
            "state_code": "UMBRELLA",
            "rain_start_time": "18:00"
        }
    }

    # 1. 아침 알림: 이미 받아있으므로 스킵되어야 함
    should_send_m, _ = should_send_notification("morning", user_doc, weather_umbrella, now)
    assert should_send_m is False

    # 2. 비 1시간전 알림: 아침 알림을 받았더라도 비 알림은 독립적이므로 발송 대상이어야 함!
    should_send_pr, dedup_val = should_send_notification("preRain", user_doc, weather_umbrella, now)
    assert should_send_pr is True
    assert dedup_val == now.isoformat()

def test_expired_ad_pass_blocks_notification():
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    expired_user = {
        "userKey": "test_user_expired",
        "locationId": "SEOUL_GANGNAM",
        "isNotificationEnabled": True,
        "adPass": {
            "expiresAt": (now - timedelta(hours=1)).isoformat() # 만료됨
        },
        "lastNotified": {}
    }
    weather = {"recommendation": {"state_code": "UMBRELLA", "rain_start_time": "14:00"}}

    should_send, _ = should_send_notification("preRain", expired_user, weather, now)
    assert should_send is False

def test_toss_smart_message_formatting():
    payload = format_notification_payload("user_abc_123", "morning", "서울 강남")
    assert payload["userKey"] == "user_abc_123"
    assert payload["context"]["locationName"] == "서울 강남"
    assert payload["templateCode"] == "NEED_UMBRELLA_MORNING"

def test_send_bulk_smart_messages_mock():
    dispatch_list = [
        {"userKey": "user_1", "useCase": "morning", "locationName": "서울 강남"},
        {"userKey": "user_2", "useCase": "preRain", "locationName": "부산 해운대"}
    ]
    res = send_bulk_smart_messages(dispatch_list)
    assert res["total"] == 2
    assert res["success"] == 2
