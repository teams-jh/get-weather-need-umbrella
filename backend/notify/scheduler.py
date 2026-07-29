# backend/notify/scheduler.py
# 우산 알림 스케줄러: Firebase Firestore DB 연동 및 5가지 유스케이스 타입별 독립 중복 방지

import os
import json
from datetime import datetime, timezone, timedelta

import paths
from notify.toss import real_send_enabled, send_bulk_smart_messages

# KST 시간대 정의 (+09:00)
KST = timezone(timedelta(hours=9))

# 발송 대상 유스케이스. 순서가 곧 처리 순서입니다.
USE_CASES = ("morning", "preRain", "evening", "alert", "weekend")

# 우산이 필요한 상태 코드
UMBRELLA_STATES = ("UMBRELLA", "ALERT")

# 발송해도 되는 거점 상태. weather.pipeline 의 STATUS_OK 와 같은 값입니다.
# 실제 응답으로 채워진 거점만 해당하며, 수집 실패(failed)나 프리셋(preset)은
# 발송 대상이 아닙니다. 없는 날씨를 지어내 알리느니 알리지 않는 편이 낫습니다.
SENDABLE_STATUS = "ok"

# 아침 알림 허용 시간대(KST). 유저가 지정한 morningTime을 이 범위로 클램프합니다.
MORNING_HOUR_MIN = 6
MORNING_HOUR_MAX = 9
DEFAULT_MORNING_TIME = "07:30"

# 퇴근 알림 / 주말 알림 발송 시간대(KST)
EVENING_HOURS = (17, 18)
WEEKEND_HOURS = (18, 19)

# 돌발 비 알림은 비 시작 60~120분 전에만 발송합니다.
PRE_RAIN_MIN_MINUTES = 60
PRE_RAIN_MAX_MINUTES = 120
PRE_RAIN_COOLDOWN_SECONDS = 6 * 3600

# Firestore 배치 쓰기 상한은 500건이므로 여유를 두고 끊습니다.
FIRESTORE_BATCH_SIZE = 400

# 예보가 이보다 오래됐으면 발송하지 않습니다.
# 수집(weather_update)은 최대 3시간 간격으로 돌기 때문에, 한 번 걸러도 알림이 멈추지
# 않도록 두 배인 6시간을 상한으로 둡니다. 두 번 연속 실패하면 발송을 건너뜁니다.
MAX_WEATHER_AGE_SECONDS = int(os.environ.get("MAX_WEATHER_AGE_SECONDS", 6 * 3600))

# 프론트엔드 초기 버전이 저장한 구형 locationId를 현재 거점 ID로 매핑합니다.
LEGACY_LOCATION_ALIASES = {
    "SEOUL_GANGNAM": "seoul_south",
    "BUSAN_HAEUNDAE": "busan_east",
}
DEFAULT_LOCATION_ID = "seoul_south"


def weather_json_path() -> str:
    """weather_all.json 경로. 환경 변수로 재정의할 수 있습니다."""
    return os.environ.get("WEATHER_JSON_PATH") or paths.WEATHER_JSON


def weather_age_seconds(meta: dict, now_dt: datetime):
    """
    수집 시각(meta.updated_at)으로부터 흐른 초. 판별 불가 시 None.

    updated_at 은 수집 파이프라인이 KST 오프셋을 붙여 기록하지만, 오프셋이 없는
    값이 들어오면 KST 로 읽습니다. 수집 쪽이 KST 로만 쓰기 때문입니다.
    """
    raw = meta.get("updated_at")
    if not raw:
        return None
    try:
        updated = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=KST)
    return (now_dt - updated).total_seconds()


def load_weather_map(path: str = None, now_dt: datetime = None) -> dict:
    """
    수집 파이프라인이 만든 weather_all.json에서 거점별 날씨 데이터를 읽습니다.

    파일이 너무 오래됐으면 빈 맵을 돌려줍니다. 수집 워크플로가 며칠 멈춰도 파일은
    그대로 남아 있기 때문에, 존재 여부만 보면 낡은 예보로 계속 발송하게 됩니다.
    특히 preRain 은 지나간 rain_start_time 을 그대로 믿고 엉뚱한 시각에 나갑니다.
    """
    if path is None:
        path = weather_json_path()
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as err:
        print(f"[Backend] Failed to load weather data from {path}: {err}")
        return {}

    data = payload.get("data", {})
    if not isinstance(data, dict):
        print(f"[Backend] Unexpected weather data shape in {path}.")
        return {}

    meta = payload.get("meta", {})
    age = weather_age_seconds(meta, now_dt)
    if age is None:
        print(f"[Backend] Weather meta.updated_at is missing or unparsable in {path}; skipping.")
        return {}
    if age > MAX_WEATHER_AGE_SECONDS:
        print(
            f"[Backend] Weather data is stale ({age / 3600:.1f}h old, limit "
            f"{MAX_WEATHER_AGE_SECONDS / 3600:.0f}h). Check the weather_update workflow."
        )
        return {}

    print(
        f"[Backend] Loaded weather for {len(data)} locations "
        f"(updated_at={meta.get('updated_at')}, {age / 3600:.1f}h old)."
    )
    # 부분 실패는 런을 멈출 이유가 아닙니다. 파일 자체는 신선하므로 성공한 거점은
    # 정상 발송하고, 실패한 거점만 아래에서 건너뜁니다. 규모는 로그에 남깁니다.
    failed_count = meta.get("failed_count")
    if failed_count:
        print(f"[Backend] {failed_count} location(s) failed collection and will be skipped: {meta.get('failed_locations')}")
    return data


def normalize_location_id(location_id: str, weather_map: dict) -> str:
    """유저 문서의 locationId를 weather_all.json의 거점 ID 체계로 정규화합니다."""
    if location_id in weather_map:
        return location_id
    aliased = LEGACY_LOCATION_ALIASES.get(location_id)
    if aliased in weather_map:
        return aliased
    return DEFAULT_LOCATION_ID


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


def update_last_notified_batch(dispatched_items: list) -> int:
    """
    발송에 성공한 항목들의 lastNotified를 Firestore 배치 쓰기로 한 번에 갱신합니다.
    같은 유저의 여러 유스케이스는 하나의 문서 쓰기로 합칩니다.
    """
    if not dispatched_items:
        return 0

    updates: dict = {}
    for item in dispatched_items:
        updates.setdefault(item["userKey"], {})[item["useCase"]] = item["updateDedupKey"]

    init_firebase_admin()
    try:
        import firebase_admin
        from firebase_admin import firestore
        if not firebase_admin._apps:
            return 0

        db = firestore.client()
        now_iso = datetime.now(timezone.utc).isoformat()
        written = 0
        pending = list(updates.items())

        for offset in range(0, len(pending), FIRESTORE_BATCH_SIZE):
            batch = db.batch()
            chunk = pending[offset:offset + FIRESTORE_BATCH_SIZE]
            for user_key, last_notified in chunk:
                user_ref = db.collection("users").document(user_key)
                batch.set(user_ref, {"lastNotified": last_notified, "updatedAt": now_iso}, merge=True)
            batch.commit()
            written += len(chunk)

        print(f"[Backend] Updated lastNotified for {written} users in {-(-written // FIRESTORE_BATCH_SIZE)} batch(es).")
        return written
    except Exception as err:
        print(f"[Backend] Failed to update lastNotified in Firestore: {err}")
        return 0


def is_ad_pass_valid(expires_at_iso: str, now_dt: datetime) -> bool:
    """리워드 이용권 만료 여부 검사"""
    if not expires_at_iso:
        return False
    try:
        expires_dt = datetime.fromisoformat(expires_at_iso.replace('Z', '+00:00'))
        return expires_dt > now_dt
    except Exception:
        return False


def has_active_ad_pass(user_doc: dict, now_dt: datetime) -> bool:
    """리워드 이용권이 활성 상태이며 아직 만료되지 않았는지 검사합니다."""
    ad_pass = user_doc.get("adPass", {})
    if ad_pass.get("active") is not True:
        return False
    return is_ad_pass_valid(ad_pass.get("expiresAt", ""), now_dt)


def resolve_morning_hour(user_doc: dict) -> int:
    """
    유저가 지정한 morningTime의 '시'를 구합니다.
    스케줄러가 매시 정각에만 돌기 때문에 분 단위는 비교하지 않고 시 단위로만 매칭합니다.
    """
    raw = user_doc.get("morningTime") or DEFAULT_MORNING_TIME
    try:
        hour = int(str(raw).split(":")[0])
    except (ValueError, IndexError):
        hour = int(DEFAULT_MORNING_TIME.split(":")[0])
    return min(max(hour, MORNING_HOUR_MIN), MORNING_HOUR_MAX)


def is_within_window(use_case: str, kst_now: datetime, user_doc: dict) -> bool:
    """유스케이스별 발송 허용 시간대(KST) 검사."""
    if use_case == "morning":
        return kst_now.hour == resolve_morning_hour(user_doc)
    if use_case == "evening":
        return kst_now.weekday() < 5 and kst_now.hour in EVENING_HOURS
    if use_case == "weekend":
        return kst_now.weekday() == 4 and kst_now.hour in WEEKEND_HOURS
    # preRain과 alert은 날씨 조건이 성립하는 즉시 발송해야 하므로 시간 제한이 없습니다.
    return True


def minutes_until_rain(rain_start_time: str, kst_now: datetime):
    """오늘 KST 기준 비 시작 시각까지 남은 분. 판별 불가 시 None."""
    if not rain_start_time or ":" not in str(rain_start_time):
        return None
    try:
        hour_str, minute_str = str(rain_start_time).split(":")[:2]
        rain_dt = kst_now.replace(hour=int(hour_str), minute=int(minute_str), second=0, microsecond=0)
    except ValueError:
        return None
    return (rain_dt - kst_now).total_seconds() / 60


def has_weekend_rain(weather_data: dict, kst_now: datetime) -> bool:
    """이번 주말(금요일 기준 내일/모레)에 비 예보가 있는지 확인합니다."""
    upcoming = {(kst_now + timedelta(days=offset)).strftime("%Y-%m-%d") for offset in (1, 2)}
    for day in weather_data.get("forecast", []):
        if day.get("date") in upcoming and day.get("has_rain"):
            return True
    return False


def should_send_notification(
    use_case: str,
    user_doc: dict,
    weather_data: dict,
    now_dt: datetime
) -> tuple[bool, str]:
    """
    5가지 유스케이스별 시간대/날씨 조건 및 독립 중복 발송 방지 검사
    Returns (should_send: bool, deduplication_key_update: str)
    """
    if not user_doc.get("isNotificationEnabled", True):
        return False, ""

    # 리워드 이용권 검사 (기상 특보 포함 전 유스케이스에 적용)
    if not has_active_ad_pass(user_doc, now_dt):
        return False, ""

    notification_types = user_doc.get("notificationTypes", {})
    if not notification_types.get(use_case, True):
        return False, ""

    # 실제로 수집된 거점만 발송합니다. status 키가 없으면 구버전(2.0) 산출물이라
    # 정상으로 간주합니다. 새 산출물에서는 failed/preset 이 여기서 걸러집니다.
    if weather_data.get("status", SENDABLE_STATUS) != SENDABLE_STATUS:
        return False, ""

    kst_now = now_dt.astimezone(KST)
    if not is_within_window(use_case, kst_now, user_doc):
        return False, ""

    last_notified = user_doc.get("lastNotified", {})
    today_str = kst_now.strftime("%Y-%m-%d")
    # 실패 거점에는 recommendation 키가 아예 없습니다. 기본값을 {} 로 두면
    # 명시적 null 이 들어왔을 때 None 이 되어 아래 .get 에서 터집니다.
    recommendation = weather_data.get("recommendation") or {}

    # 1. 아침 출근 전 우산 알림 (유저가 지정한 morningTime의 시각대)
    if use_case == "morning":
        if last_notified.get("morning") == today_str:
            return False, ""
        if recommendation.get("state_code", "NONE") in UMBRELLA_STATES:
            return True, today_str
        return False, ""

    # 2. 비 오기 1~2시간 전 돌발 알림
    if use_case == "preRain":
        last_pre_rain = last_notified.get("preRain")
        if last_pre_rain:
            try:
                last_dt = datetime.fromisoformat(last_pre_rain.replace('Z', '+00:00'))
                if (now_dt - last_dt).total_seconds() < PRE_RAIN_COOLDOWN_SECONDS:
                    return False, ""
            except Exception:
                pass

        remaining = minutes_until_rain(recommendation.get("rain_start_time"), kst_now)
        if remaining is not None and PRE_RAIN_MIN_MINUTES <= remaining <= PRE_RAIN_MAX_MINUTES:
            return True, now_dt.isoformat()
        return False, ""

    # 3. 퇴근길 우산 챙기기 알림 (평일 17~18시)
    if use_case == "evening":
        if last_notified.get("evening") == today_str:
            return False, ""
        if recommendation.get("state_code", "NONE") in UMBRELLA_STATES:
            return True, today_str
        return False, ""

    # 4. 기상 특보 긴급 알림
    if use_case == "alert":
        alert_event = recommendation.get("alert_event")
        if not alert_event:
            return False, ""
        alert_key = f"{today_str}_{alert_event}"
        if last_notified.get("alert") == alert_key:
            return False, ""
        return True, alert_key

    # 5. 금요일 주말 비 소식 알림 (금요일 18~19시)
    if use_case == "weekend":
        week_key = f"{kst_now.year}-W{kst_now.isocalendar()[1]}"
        if last_notified.get("weekend") == week_key:
            return False, ""
        if has_weekend_rain(weather_data, kst_now):
            return True, week_key
        return False, ""

    return False, ""


def process_notifications_for_users(users: list, weather_map: dict, now_dt: datetime) -> list:
    """발송 대상 유저 및 업데이트할 중복 방지 키 계산"""
    dispatch_list = []
    skipped_locations = set()
    for user in users:
        # Browser-only fallback identifiers are not valid x-anon-key values and
        # must never enter the real Toss Smart Message delivery pipeline.
        if str(user.get("userKey", "")).startswith("local:"):
            continue
        loc_id = normalize_location_id(user.get("locationId", DEFAULT_LOCATION_ID), weather_map)
        weather = weather_map.get(loc_id, {})
        # 수집에 실패한 거점은 조용히 건너뜁니다. weather_map 에서 실패 거점을
        # 아예 빼면 normalize_location_id 가 기본 거점으로 폴백해 그 지역
        # 유저에게 서울 날씨를 보내게 되므로, 엔트리는 두고 여기서 거릅니다.
        if weather.get("status", SENDABLE_STATUS) != SENDABLE_STATUS:
            skipped_locations.add(loc_id)
            continue
        loc_name = user.get("locationName") or weather.get("name", "")

        for use_case in USE_CASES:
            should_send, dedup_val = should_send_notification(use_case, user, weather, now_dt)
            if should_send:
                dispatch_list.append({
                    "userKey": user["userKey"],
                    "useCase": use_case,
                    "locationId": loc_id,
                    "locationName": loc_name,
                    "updateDedupKey": dedup_val
                })

    if skipped_locations:
        print(f"[Backend] Skipped {len(skipped_locations)} location(s) without usable weather: {sorted(skipped_locations)}")
    return dispatch_list


def run_notification_pipeline(now_dt: datetime = None) -> dict:
    """알림 파이프라인 전체 실행 함수"""
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)

    users = fetch_active_users_from_firestore()
    if not users:
        print("[Backend] No active users found in Firestore.")
        return {"total_users": 0, "dispatched": 0}

    weather_map = load_weather_map(now_dt=now_dt)
    if not weather_map:
        print("[Backend] Weather data unavailable or stale; skipping this run.")
        return {"total_users": len(users), "dispatched": 0}

    dispatch_list = process_notifications_for_users(users, weather_map, now_dt)
    result = send_bulk_smart_messages(dispatch_list)

    # 토스 API 호출에 성공한 항목만 중복 발송 방지 키를 갱신합니다.
    # 실패한 알림은 다음 스케줄에서 다시 발송할 수 있어야 합니다.
    #
    # 모의 발송일 때는 갱신하지 않습니다. 실제로 나가지 않은 알림에 중복 방지 키를 남기면
    # 나중에 실발송을 켰을 때 그 유저들이 이미 받은 것으로 취급되어 차단됩니다.
    if real_send_enabled():
        update_last_notified_batch(result["succeededItems"])
    else:
        print(f"[Backend] Mock dispatch: skipping lastNotified update for {len(result['succeededItems'])} item(s).")

    print(f"[{now_dt.isoformat()}] Notification Pipeline Result: {result}")
    return result

