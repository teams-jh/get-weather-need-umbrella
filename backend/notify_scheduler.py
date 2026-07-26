# backend/notify_scheduler.py
# 우산 알림 스케줄러: Firebase Firestore DB 연동 및 5가지 유스케이스 타입별 독립 중복 방지

import os
import json
from datetime import datetime, timezone, timedelta
try:
    from backend.toss_smart_message import send_bulk_smart_messages, format_notification_payload
except ImportError:
    from toss_smart_message import send_bulk_smart_messages, format_notification_payload

# KST 시간대 정의 (+09:00)
KST = timezone(timedelta(hours=9))

def init_firebase_admin():
    """Firebase Admin SDK 초기화 (환경 변수 또는 JSON 파일 지원)"""
    try:
        import firebase_admin
        from firebase_admin import credentials
        if not firebase_admin._apps:
            key_json_str = os.environ.get("FIREBASE_SERVICE_ACCOUNT_KEY")
            key_path = os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH", "serviceAccountKey.json")

            if key_json_str:
                cred_dict = json.loads(key_json_str)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
                print("[Backend] Firebase Admin initialized from FIREBASE_SERVICE_ACCOUNT_KEY env.")
            elif os.path.exists(key_path):
                cred = credentials.Certificate(key_path)
                firebase_admin.initialize_app(cred)
                print(f"[Backend] Firebase Admin initialized from {key_path}.")
            else:
                print("[Backend] Firebase key file not found. Running in mock/offline mode.")
    except Exception as e:
        print(f"[Backend] Firebase Admin init notice: {e}")

def fetch_active_users_from_firestore() -> list:
    """Firestore 'users' 컬렉션에서 알림 활성 유저 조회"""
    init_firebase_admin()
    try:
        import firebase_admin
        from firebase_admin import firestore
        if not firebase_admin._apps:
            return []

        db = firestore.client()
        docs = db.collection("users").where("isNotificationEnabled", "==", True).stream()

        users = []
        for doc in docs:
            data = doc.to_dict()
            data["userKey"] = doc.id
            users.append(data)
        return users
    except Exception as err:
        print(f"[Backend] Firestore fetch error: {err}")
        return []

def update_last_notified_in_firestore(user_key: str, use_case: str, dedup_val: str) -> bool:
    """발송 성공 시 Firestore의 lastNotified 맵 업데이트"""
    init_firebase_admin()
    try:
        import firebase_admin
        from firebase_admin import firestore
        if not firebase_admin._apps:
            return False

        db = firestore.client()
        user_ref = db.collection("users").document(user_key)
        user_ref.set({
            "lastNotified": {
                use_case: dedup_val
            },
            "updatedAt": datetime.now(timezone.utc).isoformat()
        }, merge=True)
        print(f"[Backend] Updated lastNotified for user {user_key} [{use_case} => {dedup_val}]")
        return True
    except Exception as err:
        print(f"[Backend] Failed to update lastNotified in Firestore: {err}")
        return False

def is_ad_pass_valid(expires_at_iso: str, now_dt: datetime) -> bool:
    """7일 리워드 이용권 만료 여부 검사"""
    if not expires_at_iso:
        return False
    try:
        expires_dt = datetime.fromisoformat(expires_at_iso.replace('Z', '+00:00'))
        return expires_dt > now_dt
    except Exception:
        return False

def should_send_notification(
    use_case: str,
    user_doc: dict,
    weather_data: dict,
    now_dt: datetime
) -> tuple[bool, str]:
    """
    5가지 유스케이스별 독립 중복 발송 방지 검사
    Returns (should_send: bool, deduplication_key_update: str)
    """
    if not user_doc.get("isNotificationEnabled", True):
        return False, ""

    # 리워드 이용권 검사
    ad_pass = user_doc.get("adPass", {})
    if not is_ad_pass_valid(ad_pass.get("expiresAt", ""), now_dt):
        return False, ""

    notification_types = user_doc.get("notificationTypes", {})
    if not notification_types.get(use_case, True):
        return False, ""

    last_notified = user_doc.get("lastNotified", {})
    kst_now = now_dt.astimezone(KST)
    today_str = kst_now.strftime("%Y-%m-%d")

    # 1. 아침 출근 전 우산 알림 (07:00 ~ 08:30)
    if use_case == "morning":
        if last_notified.get("morning") == today_str:
            return False, ""
        state = weather_data.get("recommendation", {}).get("state_code", "NONE")
        if state in ["UMBRELLA", "ALERT"]:
            return True, today_str
        return False, ""

    # 2. 비 오기 1~2시간 전 돌발 알림
    elif use_case == "preRain":
        last_pre_rain = last_notified.get("preRain")
        if last_pre_rain:
            try:
                last_dt = datetime.fromisoformat(last_pre_rain.replace('Z', '+00:00'))
                if (now_dt - last_dt).total_seconds() < 6 * 3600:
                    return False, ""
            except Exception:
                pass

        rain_start = weather_data.get("recommendation", {}).get("rain_start_time")
        if rain_start:
            return True, now_dt.isoformat()
        return False, ""

    # 3. 퇴근길 우산 챙기기 알림 (평일 17:30 ~ 18:30)
    elif use_case == "evening":
        if kst_now.weekday() >= 5:
            return False, ""
        if last_notified.get("evening") == today_str:
            return False, ""
        state = weather_data.get("recommendation", {}).get("state_code", "NONE")
        if state in ["UMBRELLA", "ALERT"]:
            return True, today_str
        return False, ""

    # 4. 기상 특보 긴급 알림
    elif use_case == "alert":
        alert_event = weather_data.get("recommendation", {}).get("alert_event")
        if not alert_event:
            return False, ""
        alert_key = f"{today_str}_{alert_event}"
        if last_notified.get("alert") == alert_key:
            return False, ""
        return True, alert_key

    # 5. 금요일 주말 비 소식 알림 (금요일 19:00)
    elif use_case == "weekend":
        if kst_now.weekday() != 4:
            return False, ""
        week_key = f"{kst_now.year}-W{kst_now.isocalendar()[1]}"
        if last_notified.get("weekend") == week_key:
            return False, ""
        return True, week_key

    return False, ""

def process_notifications_for_users(users: list, weather_map: dict, now_dt: datetime) -> list:
    """발송 대상 유저 및 업데이트할 중복 방지 키 계산"""
    dispatch_list = []
    for user in users:
        loc_id = user.get("locationId", "SEOUL_GANGNAM")
        loc_name = user.get("locationName", "서울 강남")
        weather = weather_map.get(loc_id, {})

        for use_case in ["morning", "preRain", "evening", "alert", "weekend"]:
            should_send, dedup_val = should_send_notification(use_case, user, weather, now_dt)
            if should_send:
                dispatch_list.append({
                    "userKey": user["userKey"],
                    "useCase": use_case,
                    "locationId": loc_id,
                    "locationName": loc_name,
                    "updateDedupKey": dedup_val
                })
    return dispatch_list

def run_notification_pipeline(now_dt: datetime = None) -> dict:
    """알림 파이프라인 전체 실행 함수"""
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)

    users = fetch_active_users_from_firestore()
    if not users:
        print("[Backend] No active users found in Firestore.")
        return {"total_users": 0, "dispatched": 0}

    # 최신 날씨 수집 데이터 모의 또는 실제 요청
    weather_map = {
        "SEOUL_GANGNAM": {
            "recommendation": {
                "state_code": "UMBRELLA",
                "rain_start_time": "14:00"
            }
        }
    }

    dispatch_list = process_notifications_for_users(users, weather_map, now_dt)
    result = send_bulk_smart_messages(dispatch_list)

    # 성공한 유저의 lastNotified 키 Firestore에 업데이트
    for item in dispatch_list:
        update_last_notified_in_firestore(item["userKey"], item["useCase"], item["updateDedupKey"])

    print(f"[{now_dt.isoformat()}] Notification Pipeline Result: {result}")
    return result

if __name__ == "__main__":
    run_notification_pipeline()
