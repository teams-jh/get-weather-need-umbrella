# backend/tests/notify/test_local_run.py
# 로컬 스마트 메시지 발송 시뮬레이션 (수동 실행용, pytest 수집 대상 아님)
#
# 실행: cd backend && python -m tests.notify.test_local_run
# ENABLE_REAL_TOSS_PUSH를 켜지 않는 한 실제 발송은 일어나지 않습니다.

from datetime import datetime, timedelta, timezone

from notify.scheduler import KST, process_notifications_for_users
from notify.toss import send_bulk_smart_messages


def build_mock_users(now):
    """7일 리워드 이용권이 살아있는 모의 활성 유저"""
    return [
        {
            "userKey": "anon_user_seoul_01",
            "notificationLocationId": "SEOUL_GANGNAM",  # 구형 ID -> seoul_south로 정규화되는지 확인용
            "notificationLocationName": "서울 강남",
            "isNotificationEnabled": True,
            "notificationTypes": {
                "morning": True, "preRain": True, "evening": True, "alert": True, "weekend": True,
            },
            "morningTime": "07:30",
            "adPass": {"active": True, "expiresAt": (now + timedelta(days=5)).isoformat()},
            "lastNotified": {},
        },
        {
            "userKey": "anon_user_busan_02",
            "notificationLocationId": "busan_east",
            "notificationLocationName": "부산 해운대",
            "isNotificationEnabled": True,
            "notificationTypes": {
                "morning": True, "preRain": True, "evening": True, "alert": True, "weekend": True,
            },
            "morningTime": "07:00",
            "adPass": {"active": True, "expiresAt": (now + timedelta(days=2)).isoformat()},
            "lastNotified": {},
        },
    ]


def build_mock_weather(now):
    """비가 90분 뒤 시작하는 상황과 기상 특보 상황을 각각 재현합니다."""
    rain_start = (now.astimezone(KST) + timedelta(minutes=90)).strftime("%H:%M")
    return {
        "seoul_south": {
            "name": "서울_강남",
            "recommendation": {"state_code": "UMBRELLA", "rain_start_time": rain_start},
            "forecast": [],
        },
        "busan_east": {
            "name": "부산_해운대",
            "recommendation": {"state_code": "ALERT", "alert_event": "호우주의보"},
            "forecast": [],
        },
    }


def run_local_notification_test():
    now = datetime.now(timezone.utc)
    print(f"=== [로컬 알림 발송 시뮬레이션 시작 ({now.astimezone(KST).isoformat()} KST)] ===")

    users = build_mock_users(now)
    weather_map = build_mock_weather(now)

    dispatch_list = process_notifications_for_users(users, weather_map, now)
    print(f"\n[1. 수신 대상 필터링 결과]: 총 {len(dispatch_list)}건 추출됨")
    for item in dispatch_list:
        print(f"  - 유저: {item['userKey']} | 지역: {item['locationId']} | 유스케이스: {item['useCase']}")

    print("\n[2. 토스 스마트 메시지 대량 발송 시뮬레이션]:")
    result = send_bulk_smart_messages(dispatch_list)
    print(f"\n=== [시뮬레이션 통계 결과]: {result} ===")


if __name__ == "__main__":
    run_local_notification_test()
