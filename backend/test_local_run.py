# backend/test_local_run.py
# 로컬 스마트 메시지 푸시 발송 시뮬레이션 테스트

from datetime import datetime, timezone, timedelta
from notify_scheduler import process_notifications_for_users
from toss_smart_message import send_bulk_smart_messages

def run_local_notification_test():
    now = datetime.now(timezone.utc)
    print(f"=== [로컬 알림 발송 시뮬레이션 테스트 시작 ({now.isoformat()})] ===")

    # 모의 활성 유저 샘플 2명 (7일 이용권 활성화 상태)
    mock_users = [
        {
            "userKey": "test_user_seoul_01",
            "locationId": "SEOUL_GANGNAM",
            "locationName": "서울 강남",
            "isNotificationEnabled": True,
            "notificationTypes": {
                "morning": True,
                "preRain": True,
                "evening": True,
                "alert": True,
                "weekend": True,
            },
            "adPass": {
                "active": True,
                "expiresAt": (now + timedelta(days=5)).isoformat() # 5일 남음
            },
            "lastNotified": {}
        },
        {
            "userKey": "test_user_busan_02",
            "locationId": "BUSAN_HAEUNDAE",
            "locationName": "부산 해운대",
            "isNotificationEnabled": True,
            "notificationTypes": {
                "morning": True,
                "preRain": True,
                "evening": True,
                "alert": True,
                "weekend": True,
            },
            "adPass": {
                "active": True,
                "expiresAt": (now + timedelta(days=2)).isoformat() # 2일 남음
            },
            "lastNotified": {}
        }
    ]

    # 실시간 날씨 데이터 가상 수신 (우산 필요 상황)
    weather_map = {
        "SEOUL_GANGNAM": {
            "recommendation": {
                "state_code": "UMBRELLA",
                "rain_start_time": "14:00"
            }
        },
        "BUSAN_HAEUNDAE": {
            "recommendation": {
                "state_code": "ALERT",
                "alert_event": "호우주의보"
            }
        }
    }

    # 1. 수신 대상 필터링 & 중복 방지 키 검사
    dispatch_list = process_notifications_for_users(mock_users, weather_map, now)
    print(f"\n[1. 수신 대상 필터링 결과]: 총 {len(dispatch_list)}건 추출됨")
    for item in dispatch_list:
        print(f"  - 유저: {item['userKey']} | 지역: {item['locationName']} | 유스케이스: {item['useCase']}")

    # 2. 토스 스마트 메시지 모의/실제 발송
    print(f"\n[2. 토스 스마트 메시지 발송 연동 시뮬레이션]:")
    result = send_bulk_smart_messages(dispatch_list)
    print(f"\n=== [테스트 통계 결과]: {result} ===")

if __name__ == "__main__":
    run_local_notification_test()
