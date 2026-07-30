# backend/tests/notify/test_notify.py
import json
from datetime import datetime, timezone, timedelta

from notify.scheduler import (
    KST,
    active_alert_events,
    alert_events_to_send,
    has_active_ad_pass,
    has_weekend_rain,
    is_ad_pass_valid,
    is_within_window,
    last_notified_updates,
    load_weather_map,
    minutes_until_rain,
    normalize_location_id,
    process_notifications_for_users,
    resolve_morning_hour,
    resolve_morning_time,
    should_send_notification,
    weather_age_seconds,
)
from notify.toss import build_bulk_payload, send_bulk_smart_messages, template_code_for

# 2026-07-28은 화요일, 2026-07-31은 금요일입니다.
TUESDAY = (2026, 7, 28)
FRIDAY = (2026, 7, 31)


def kst(year_month_day, hour, minute=0):
    year, month, day = year_month_day
    return datetime(year, month, day, hour, minute, tzinfo=KST)


def make_user(**overrides):
    now = datetime.now(timezone.utc)
    user = {
        "userKey": "anon-key-01",
        "notificationLocationId": "seoul_south",
        "notificationLocationName": "서울 강남",
        "isNotificationEnabled": True,
        "notificationTypes": {
            "morning": True,
            "preRain": True,
            "evening": True,
            "alert": True,
            "weekend": True,
        },
        "morningTime": "07:30",
        "adPass": {"active": True, "expiresAt": (now + timedelta(days=5)).isoformat()},
        "lastNotified": {},
    }
    user.update(overrides)
    return user


def umbrella_weather(rain_start_time="14:00"):
    return {"recommendation": {"state_code": "UMBRELLA", "rain_start_time": rain_start_time}}


def prepared_weather(*types):
    return {"recommendation": {"state_code": types[0], "preparations": [{"type": item} for item in types]}}


# --- 리워드 이용권 ---

def test_is_ad_pass_valid():
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)

    valid_expires = (now + timedelta(days=7)).isoformat()
    assert is_ad_pass_valid(valid_expires, now) is True

    expired_iso = (now - timedelta(days=1)).isoformat()
    assert is_ad_pass_valid(expired_iso, now) is False


def test_ad_pass_requires_active_flag():
    """만료 전이어도 active가 False면 발송하지 않습니다."""
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    future = (now + timedelta(days=5)).isoformat()

    assert has_active_ad_pass({"adPass": {"active": True, "expiresAt": future}}, now) is True
    assert has_active_ad_pass({"adPass": {"active": False, "expiresAt": future}}, now) is False
    assert has_active_ad_pass({}, now) is False


def test_expired_ad_pass_blocks_notification():
    now = kst(TUESDAY, 12, 30)
    user = make_user(adPass={"active": True, "expiresAt": (now - timedelta(hours=1)).isoformat()})

    should_send, _ = should_send_notification("preRain", user, umbrella_weather(), now)
    assert should_send is False


def test_expired_ad_pass_also_blocks_weather_alert():
    """기상 특보도 이용권이 만료되면 차단합니다."""
    now = kst(TUESDAY, 12, 0)
    user = make_user(adPass={"active": True, "expiresAt": (now - timedelta(hours=1)).isoformat()})
    weather = {"recommendation": {"state_code": "ALERT", "alert_event": "호우주의보"}}

    should_send, _ = should_send_notification("alert", user, weather, now)
    assert should_send is False

    valid_user = make_user()
    should_send, dedup = should_send_notification("alert", valid_user, weather, now)
    assert should_send is True
    assert dedup == "2026-07-28_호우주의보"


def test_alert_events_are_sent_once_per_name_each_day():
    now = kst(TUESDAY, 12, 0)
    user = make_user()
    weather = {
        "recommendation": {
            "state_code": "ALERT",
            "alert_events": ["폭염주의보", "열대야주의보", "폭염주의보"],
            "preparations": [{"type": "ALERT"}],
        }
    }

    assert active_alert_events(weather["recommendation"]) == ["폭염주의보", "열대야주의보"]
    assert alert_events_to_send(user, weather, now) == ["폭염주의보", "열대야주의보"]

    user["lastNotified"] = {"alerts": {"폭염주의보": "2026-07-28"}}
    assert alert_events_to_send(user, weather, now) == ["열대야주의보"]
    assert alert_events_to_send(user, weather, kst((2026, 7, 29), 12)) == ["폭염주의보", "열대야주의보"]


def test_legacy_alert_deduplication_is_honored_for_same_day():
    now = kst(TUESDAY, 12, 0)
    user = make_user(lastNotified={"alert": "2026-07-28_호우주의보"})
    weather = {"recommendation": {"state_code": "ALERT", "alert_event": "호우주의보"}}

    assert alert_events_to_send(user, weather, now) == []


def test_umbrella_notifications_use_independent_preparation():
    now = kst(TUESDAY, 7, 30)
    user = make_user()
    heat_alert = {"recommendation": {"state_code": "ALERT", "alert_event": "폭염주의보", "preparations": [{"type": "ALERT"}]}}
    alert_with_rain = prepared_weather("ALERT", "UMBRELLA")

    assert should_send_notification("morning", user, heat_alert, now)[0] is False
    assert should_send_notification("morning", user, alert_with_rain, now)[0] is True


# --- 시간 게이트 ---

def test_resolve_morning_hour_clamps_to_allowed_range():
    assert resolve_morning_hour({"morningTime": "07:30"}) == 7
    assert resolve_morning_hour({"morningTime": "06:00"}) == 6
    assert resolve_morning_hour({"morningTime": "03:00"}) == 6   # 하한 클램프
    assert resolve_morning_hour({"morningTime": "23:00"}) == 9   # 상한 클램프
    assert resolve_morning_hour({}) == 7                          # 기본값 07:30
    assert resolve_morning_hour({"morningTime": "쓰레기"}) == 7    # 파싱 실패 시 기본값
    assert resolve_morning_time({"morningTime": "07:45"}) == (7, 45)


def test_morning_window_uses_configured_minute_and_two_hour_recovery():
    user = make_user(morningTime="07:30")
    assert is_within_window("morning", kst(TUESDAY, 7, 29), user) is False
    assert is_within_window("morning", kst(TUESDAY, 7, 30), user) is True
    assert is_within_window("morning", kst(TUESDAY, 9, 30), user) is True
    assert is_within_window("morning", kst(TUESDAY, 9, 31), user) is False
    assert is_within_window("morning", kst(TUESDAY, 3), user) is False


def test_evening_window_is_weekday_evening_only():
    user = make_user()
    assert is_within_window("evening", kst(TUESDAY, 17, 59), user) is False
    assert is_within_window("evening", kst(TUESDAY, 18), user) is True
    assert is_within_window("evening", kst(TUESDAY, 19, 59), user) is True
    assert is_within_window("evening", kst(TUESDAY, 20), user) is True
    assert is_within_window("evening", kst(TUESDAY, 20, 1), user) is False
    # 토요일 저녁은 퇴근길 알림 대상이 아닙니다.
    assert is_within_window("evening", kst((2026, 8, 1), 17), user) is False


def test_weekend_window_is_friday_evening_only():
    user = make_user()
    assert is_within_window("weekend", kst(FRIDAY, 18, 59), user) is False
    assert is_within_window("weekend", kst(FRIDAY, 19), user) is True
    assert is_within_window("weekend", kst(FRIDAY, 21), user) is True
    assert is_within_window("weekend", kst(FRIDAY, 21, 1), user) is False
    assert is_within_window("weekend", kst(FRIDAY, 12), user) is False
    assert is_within_window("weekend", kst(TUESDAY, 18), user) is False


def test_pre_rain_and_alert_have_no_time_window():
    user = make_user()
    assert is_within_window("preRain", kst(TUESDAY, 3), user) is True
    assert is_within_window("alert", kst(TUESDAY, 3), user) is True


def test_morning_outside_window_is_not_dispatched():
    """날씨 조건을 만족해도 시간대가 아니면 발송하지 않습니다."""
    user = make_user(morningTime="07:30")
    assert should_send_notification("morning", user, umbrella_weather(), kst(TUESDAY, 7))[0] is False
    assert should_send_notification("morning", user, umbrella_weather(), kst(TUESDAY, 7, 43))[0] is True
    assert should_send_notification("morning", user, umbrella_weather(), kst(TUESDAY, 1))[0] is False


# --- 비 시작 시각 ---

def test_minutes_until_rain():
    now = kst(TUESDAY, 12, 30)
    assert minutes_until_rain("14:00", now) == 90
    assert minutes_until_rain("12:00", now) == -30
    assert minutes_until_rain(None, now) is None
    assert minutes_until_rain("", now) is None
    assert minutes_until_rain("잘못된값", now) is None


def test_pre_rain_fires_between_20_and_120_minutes_ahead():
    user = make_user()

    # 90분 전 -> 발송
    assert should_send_notification("preRain", user, umbrella_weather("14:00"), kst(TUESDAY, 12, 30))[0] is True
    # 30분 전 -> 지연 복구 발송
    assert should_send_notification("preRain", user, umbrella_weather("14:00"), kst(TUESDAY, 13, 30))[0] is True
    # 19분 전 -> 너무 늦음
    assert should_send_notification("preRain", user, umbrella_weather("14:00"), kst(TUESDAY, 13, 41))[0] is False
    # 180분 전 -> 너무 이름
    assert should_send_notification("preRain", user, umbrella_weather("14:00"), kst(TUESDAY, 11, 0))[0] is False
    # 이미 지나감
    assert should_send_notification("preRain", user, umbrella_weather("14:00"), kst(TUESDAY, 15, 0))[0] is False


def test_pre_rain_cooldown_blocks_repeat_within_six_hours():
    now = kst(TUESDAY, 12, 30)
    recent = (now - timedelta(hours=2)).isoformat()
    user = make_user(lastNotified={"preRain": recent})

    assert should_send_notification("preRain", user, umbrella_weather("14:00"), now)[0] is False

    stale_user = make_user(lastNotified={"preRain": (now - timedelta(hours=7)).isoformat()})
    assert should_send_notification("preRain", stale_user, umbrella_weather("14:00"), now)[0] is True


# --- 주말 알림 ---

def test_has_weekend_rain_looks_at_upcoming_saturday_and_sunday():
    friday = kst(FRIDAY, 18)
    rainy = {"forecast": [
        {"date": "2026-07-31", "has_rain": False},
        {"date": "2026-08-01", "has_rain": True},
    ]}
    dry = {"forecast": [
        {"date": "2026-07-31", "has_rain": True},   # 금요일 비는 주말 알림과 무관
        {"date": "2026-08-01", "has_rain": False},
        {"date": "2026-08-02", "has_rain": False},
    ]}
    assert has_weekend_rain(rainy, friday) is True
    assert has_weekend_rain(dry, friday) is False
    assert has_weekend_rain({}, friday) is False


def test_weekend_notification_requires_forecast_rain():
    now = kst(FRIDAY, 19)
    user = make_user()

    rainy = {"recommendation": {"state_code": "NONE"},
             "forecast": [{"date": "2026-08-01", "has_rain": True}]}
    should_send, dedup = should_send_notification("weekend", user, rainy, now)
    assert should_send is True
    assert dedup == "2026-W31"

    dry = {"recommendation": {"state_code": "NONE"},
           "forecast": [{"date": "2026-08-01", "has_rain": False}]}
    assert should_send_notification("weekend", user, dry, now)[0] is False


# --- 중복 방지 ---

def test_notification_deduplication_by_type():
    """유스케이스별 중복 방지 키는 서로 독립적이어야 합니다."""
    now = kst(TUESDAY, 12, 30)
    user = make_user(lastNotified={"morning": "2026-07-28"})

    # 아침 알림은 이미 받았고, 시간대도 아니므로 스킵
    assert should_send_notification("morning", user, umbrella_weather(), now)[0] is False

    # 비 1~2시간 전 알림은 독립적이므로 발송 대상
    should_send, dedup_val = should_send_notification("preRain", user, umbrella_weather("14:00"), now)
    assert should_send is True
    assert dedup_val == now.isoformat()


def test_disabled_type_blocks_only_that_use_case():
    now = kst(TUESDAY, 12, 30)
    user = make_user(notificationTypes={"morning": True, "preRain": False, "evening": True,
                                        "alert": True, "weekend": True})
    assert should_send_notification("preRain", user, umbrella_weather("14:00"), now)[0] is False


# --- 지역 정규화 및 파이프라인 ---

def test_normalize_location_id_maps_legacy_ids():
    weather_map = {"seoul_south": {}, "busan_east": {}}
    assert normalize_location_id("seoul_south", weather_map) == "seoul_south"
    assert normalize_location_id("SEOUL_GANGNAM", weather_map) == "seoul_south"
    assert normalize_location_id("BUSAN_HAEUNDAE", weather_map) == "busan_east"
    assert normalize_location_id("존재하지_않는_지역", weather_map) == "seoul_south"


def test_process_notifications_uses_real_weather_map():
    now = kst(TUESDAY, 12, 30)
    users = [
        make_user(userKey="anon-seoul", notificationLocationId="SEOUL_GANGNAM"),
        make_user(userKey="anon-busan", notificationLocationId="busan_east"),
        make_user(userKey="local:browser-fallback", notificationLocationId="seoul_south"),
    ]
    weather_map = {
        "seoul_south": umbrella_weather("14:00"),
        "busan_east": {"recommendation": {"state_code": "NONE", "rain_start_time": None}},
    }

    dispatch_list = process_notifications_for_users(users, weather_map, now)

    # 로컬 폴백 키는 발송 대상에서 제외됩니다.
    assert all(not item["userKey"].startswith("local:") for item in dispatch_list)
    # 강남(legacy ID) 유저만 비 알림 대상이며, 부산 유저는 비 예보가 없습니다.
    assert [(item["userKey"], item["useCase"]) for item in dispatch_list] == [("anon-seoul", "preRain")]
    assert dispatch_list[0]["locationId"] == "seoul_south"


def test_legacy_location_fields_are_not_used_for_notification_delivery():
    now = kst(TUESDAY, 12, 30)
    user = make_user(
        notificationLocationId=None,
        notificationLocationName=None,
        locationId="seoul_south",
        locationName="서울 강남",
    )
    weather_map = {
        "seoul_south": umbrella_weather("14:00"),
    }

    # 레거시 위치 필드만으로는 발송하면 안 됩니다.
    assert process_notifications_for_users([user], weather_map, now) == []


def test_pipeline_dispatches_each_new_alert_event_separately():
    now = kst(TUESDAY, 12)
    user = make_user(userKey="anon-alert", notificationLocationId="seoul_south")
    weather_map = {
        "seoul_south": {
            "recommendation": {
                "state_code": "ALERT",
                "alert_events": ["폭염주의보", "열대야주의보"],
                "preparations": [{"type": "ALERT"}],
            }
        }
    }

    dispatch_list = process_notifications_for_users([user], weather_map, now)

    assert [(item["useCase"], item["alertEvent"], item["updateDedupKey"]) for item in dispatch_list] == [
        ("alert", "폭염주의보", "2026-07-28"),
        ("alert", "열대야주의보", "2026-07-28"),
    ]


def test_successful_alerts_are_stored_by_event_name():
    updates = last_notified_updates([
        {"userKey": "anon-alert", "useCase": "alert", "alertEvent": "폭염주의보", "updateDedupKey": "2026-07-28"},
        {"userKey": "anon-alert", "useCase": "alert", "alertEvent": "열대야주의보", "updateDedupKey": "2026-07-28"},
        {"userKey": "anon-alert", "useCase": "morning", "updateDedupKey": "2026-07-28"},
    ])

    assert updates == {
        "anon-alert": {
            "alerts": {"폭염주의보": "2026-07-28", "열대야주의보": "2026-07-28"},
            "morning": "2026-07-28",
        }
    }


def test_user_without_notification_location_is_not_dispatched():
    now = kst(TUESDAY, 12, 30)
    user = make_user(notificationLocationId=None, notificationLocationName=None)
    weather_map = {"seoul_south": umbrella_weather("14:00")}

    assert process_notifications_for_users([user], weather_map, now) == []


def test_failed_locations_are_not_dispatched():
    """수집에 실패한 거점은 발송하지 않습니다. 없는 날씨를 알릴 수는 없습니다."""
    now = kst(TUESDAY, 12, 30)
    users = [
        make_user(userKey="anon-seoul", notificationLocationId="seoul_south"),
        make_user(userKey="anon-busan", notificationLocationId="busan_east"),
    ]
    weather_map = {
        # 실패 거점에는 recommendation 키가 아예 없습니다.
        "seoul_south": {"status": "failed", "error": "조회 실패"},
        "busan_east": {"status": "ok", **umbrella_weather("14:00")},
    }

    dispatch_list = process_notifications_for_users(users, weather_map, now)

    assert [item["userKey"] for item in dispatch_list] == ["anon-busan"]


def test_preset_locations_are_not_dispatched():
    """프리셋(더미)으로 채워진 거점도 발송 대상이 아닙니다."""
    now = kst(TUESDAY, 12, 30)
    users = [make_user(userKey="anon-seoul", notificationLocationId="seoul_south")]
    weather_map = {"seoul_south": {"status": "preset", **umbrella_weather("14:00")}}

    assert process_notifications_for_users(users, weather_map, now) == []


def test_failed_location_does_not_fall_back_to_default_location():
    """
    실패 거점 유저에게 기본 거점(서울) 날씨가 나가면 안 됩니다.
    weather_map 에서 실패 거점을 빼면 normalize_location_id 가 서울로 폴백하므로,
    엔트리를 남기고 status 로 거르는 방식이어야 합니다.
    """
    now = kst(TUESDAY, 12, 30)
    users = [make_user(userKey="anon-gangneung", notificationLocationId="gangwon_gangneung")]
    weather_map = {
        "seoul_south": {"status": "ok", **umbrella_weather("14:00")},
        "gangwon_gangneung": {"status": "failed", "error": "조회 실패"},
    }

    assert process_notifications_for_users(users, weather_map, now) == []


# --- 토스 발송 페이로드 ---

def test_build_bulk_payload_uses_anon_key_and_empty_context():
    items = [
        {"userKey": "anon-1", "useCase": "morning"},
        {"userKey": "anon-2", "useCase": "morning"},
    ]
    payload = build_bulk_payload("morning", items)

    assert payload["templateSetCode"] == "need-umbrella-NEED_UMBRELLA_MORNING"
    assert payload["contextList"] == [
        {"anonKey": "anon-1", "context": {}},
        {"anonKey": "anon-2", "context": {}},
    ]
    # 수신자는 헤더가 아니라 바디로만 전달합니다.
    assert "userKey" not in payload["contextList"][0]


def test_template_code_for_known_and_unknown_use_cases():
    assert template_code_for("preRain") == "need-umbrella-NEED_UMBRELLA_PRE_RAIN"
    assert template_code_for("unknown") == "need-umbrella-NEED_UMBRELLA_UNKNOWN"


def test_send_bulk_smart_messages_groups_by_use_case(monkeypatch, capsys):
    monkeypatch.delenv("ENABLE_REAL_TOSS_PUSH", raising=False)
    dispatch_list = [
        {"userKey": "anon-1", "useCase": "morning", "updateDedupKey": "2026-07-28"},
        {"userKey": "anon-2", "useCase": "morning", "updateDedupKey": "2026-07-28"},
        {"userKey": "anon-3", "useCase": "preRain", "updateDedupKey": "ts"},
    ]

    result = send_bulk_smart_messages(dispatch_list)

    assert result["total"] == 3
    assert result["success"] == 3
    assert result["fail"] == 0
    assert len(result["succeededItems"]) == 3

    # 유스케이스별로 한 번씩만 호출되므로 모의 발송 로그도 2줄입니다.
    dispatch_logs = [line for line in capsys.readouterr().out.splitlines() if "Mock Dispatch" in line]
    assert len(dispatch_logs) == 2


# --- weather_all.json 로딩 ---

def write_weather_file(tmp_path, updated_at="2026-07-28T06:00:00+09:00"):
    payload = {
        "meta": {"version": "2.1", "updated_at": updated_at},
        "data": {"seoul_south": {"recommendation": {"state_code": "UMBRELLA"}, "forecast": []}},
    }
    path = tmp_path / "weather_all.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_load_weather_map_reads_generated_file(tmp_path):
    path = write_weather_file(tmp_path)

    weather_map = load_weather_map(path, now_dt=kst(TUESDAY, 7))
    assert weather_map["seoul_south"]["recommendation"]["state_code"] == "UMBRELLA"


def test_load_weather_map_returns_empty_on_missing_or_broken_file(tmp_path):
    """파일이 없거나 깨졌으면 빈 맵을 돌려주고, 파이프라인은 발송을 건너뜁니다."""
    now = kst(TUESDAY, 7)
    assert load_weather_map(str(tmp_path / "does_not_exist.json"), now_dt=now) == {}

    broken = tmp_path / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    assert load_weather_map(str(broken), now_dt=now) == {}

    wrong_shape = tmp_path / "wrong.json"
    wrong_shape.write_text(json.dumps({"data": []}), encoding="utf-8")
    assert load_weather_map(str(wrong_shape), now_dt=now) == {}


# --- 예보 신선도 ---

def test_weather_age_seconds():
    now = kst(TUESDAY, 12)
    assert weather_age_seconds({"updated_at": "2026-07-28T09:00:00+09:00"}, now) == 3 * 3600
    # 오프셋이 없으면 KST 로 읽습니다 (수집 쪽이 KST 로만 기록).
    assert weather_age_seconds({"updated_at": "2026-07-28T09:00:00"}, now) == 3 * 3600
    assert weather_age_seconds({}, now) is None
    assert weather_age_seconds({"updated_at": "어제쯤"}, now) is None


def test_stale_weather_is_not_used(tmp_path):
    """수집이 멈춰 파일이 낡으면 발송하지 않습니다. 파일 존재만으로는 부족합니다."""
    path = write_weather_file(tmp_path, updated_at="2026-07-28T06:00:00+09:00")

    # 5시간 경과 -> 한도(6시간) 안이므로 사용
    assert load_weather_map(path, now_dt=kst(TUESDAY, 11)) != {}
    # 7시간 경과 -> 한도 초과이므로 건너뜀
    assert load_weather_map(path, now_dt=kst(TUESDAY, 13)) == {}
    # 며칠 묵은 파일
    assert load_weather_map(path, now_dt=kst((2026, 7, 31), 6)) == {}


def test_missing_updated_at_is_treated_as_stale(tmp_path):
    """수집 시각을 확인할 수 없으면 발송하지 않습니다."""
    path = tmp_path / "no_meta.json"
    path.write_text(json.dumps({"data": {"seoul_south": {}}}), encoding="utf-8")
    assert load_weather_map(str(path), now_dt=kst(TUESDAY, 7)) == {}


def test_pipeline_skips_dispatch_on_stale_weather(monkeypatch, tmp_path):
    """낡은 예보에서는 토스 발송까지 가지 않아야 합니다."""
    import notify.scheduler as notify_scheduler

    monkeypatch.delenv("ENABLE_REAL_TOSS_PUSH", raising=False)
    monkeypatch.setattr(notify_scheduler, "fetch_active_users_from_firestore",
                        lambda: [make_user(userKey="anon-1")])
    monkeypatch.setenv("WEATHER_JSON_PATH", write_weather_file(tmp_path))

    sent = []
    monkeypatch.setattr(notify_scheduler, "send_bulk_smart_messages", sent.append)

    result = notify_scheduler.run_notification_pipeline(kst((2026, 7, 31), 12))

    assert result["dispatched"] == 0
    assert sent == []


def test_weekend_notification_skipped_when_forecast_missing():
    """forecast 필드가 없는 구버전 weather_all.json에서는 주말 알림을 보내지 않습니다."""
    now = kst(FRIDAY, 18)
    legacy_weather = {"recommendation": {"state_code": "UMBRELLA", "rain_start_time": "14:00"}}
    assert should_send_notification("weekend", make_user(), legacy_weather, now)[0] is False


def test_mock_dispatch_does_not_touch_firestore(monkeypatch):
    """모의 발송에서는 lastNotified를 갱신하지 않아야 합니다."""
    import notify.scheduler as notify_scheduler

    monkeypatch.delenv("ENABLE_REAL_TOSS_PUSH", raising=False)
    monkeypatch.setattr(notify_scheduler, "fetch_active_users_from_firestore",
                        lambda: [make_user(userKey="anon-1")])
    monkeypatch.setattr(notify_scheduler, "load_weather_map",
                        lambda *args, **kwargs: {"seoul_south": umbrella_weather("14:00")})

    written = []
    monkeypatch.setattr(notify_scheduler, "update_last_notified_batch", written.append)

    result = notify_scheduler.run_notification_pipeline(kst(TUESDAY, 12, 30))

    assert result["success"] == 1
    assert written == []


def test_real_dispatch_updates_firestore(monkeypatch):
    """실발송이 켜져 있으면 성공 항목의 lastNotified를 갱신합니다."""
    import notify.scheduler as notify_scheduler
    import notify.toss as toss_smart_message

    monkeypatch.setenv("ENABLE_REAL_TOSS_PUSH", "true")
    monkeypatch.setattr(toss_smart_message, "send_bulk_message_batch", lambda use_case, items: True)
    monkeypatch.setattr(notify_scheduler, "fetch_active_users_from_firestore",
                        lambda: [make_user(userKey="anon-1")])
    monkeypatch.setattr(notify_scheduler, "load_weather_map",
                        lambda *args, **kwargs: {"seoul_south": umbrella_weather("14:00")})

    written = []
    monkeypatch.setattr(notify_scheduler, "update_last_notified_batch", written.append)

    notify_scheduler.run_notification_pipeline(kst(TUESDAY, 12, 30))

    assert len(written) == 1
    assert [item["useCase"] for item in written[0]] == ["preRain"]
