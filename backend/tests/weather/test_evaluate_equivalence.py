"""
판정 결과를 고정하는 특성 테스트.

tests/data/evaluate_golden.json 은 provider 계층 도입 이전의 구현
(main.evaluate_weather_v2)이 내놓던 결과를 그대로 굳혀 둔 것이다.
리팩터링으로 판정이 미묘하게 달라지는 것을 막는 것이 목적이므로,
이 파일은 알고리즘을 의도적으로 바꿀 때만 다시 만들어야 한다.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from weather.evaluate import evaluate
from weather.providers.openweather import bundle_from_onecall

GOLDEN_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "evaluate_golden.json")
with open(GOLDEN_PATH, encoding="utf-8") as _f:
    _GOLDEN = json.load(_f)
EXPECTED = _GOLDEN["expected"]

KST = timezone(timedelta(hours=9))


def ts(y, mo, d, h, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=KST).timestamp())


NOW = _GOLDEN["now_ts"]
assert NOW == ts(2026, 7, 24, 12, 0), "골든 파일의 기준 시각이 바뀌었습니다"


def hour(offset_h, **kwargs):
    """NOW 기준 offset 시간 뒤의 hourly 항목."""
    item = {"dt": NOW + offset_h * 3600}
    item.update(kwargs)
    return item


FIXTURES = {
    "alert_최우선": {
        "alerts": [{"event": "호우경보", "description": "많은 비"}],
        "current": {"temp": 22.0, "feels_like": 21.0, "uvi": 2.0},
        "daily": [{"temp": {"min": 18.0, "max": 24.0}, "uvi": 2.0}],
    },
    "alert_event_기본값": {
        # event 키가 없으면 "기상 특보" 로 대체된다
        "alerts": [{"description": "설명만 있음"}],
        "current": {"temp": 22.0},
        "daily": [{"temp": {"min": 18.0, "max": 24.0}}],
    },
    "umbrella_minutely": {
        "alerts": [],
        "minutely": [{"dt": ts(2026, 7, 24, 14, 15), "precipitation": 1.5}],
        "daily": [{"temp": {"min": 18.0, "max": 25.0}, "uvi": 3.0}],
    },
    "umbrella_hourly_weather_id": {
        "alerts": [],
        "minutely": [],
        "hourly": [hour(2, temp=23.0, weather=[{"id": 500}], pop=0.2)],
        "daily": [{"temp": {"min": 18.0, "max": 25.0}, "uvi": 3.0}],
    },
    "umbrella_hourly_pop_threshold": {
        "alerts": [],
        "hourly": [hour(3, temp=23.0, weather=[{"id": 801}], pop=0.5)],
        "daily": [{"temp": {"min": 18.0, "max": 25.0}, "uvi": 3.0}],
    },
    "강수아님_weather_비었고_pop높음": {
        # weather 배열이 비면 pop 이 높아도 강수로 보지 않는다 (기존 동작)
        "alerts": [],
        "hourly": [hour(3, temp=23.0, weather=[], pop=0.9)],
        "daily": [{"temp": {"min": 18.0, "max": 25.0}, "uvi": 3.0}],
    },
    "과거_비는_무시": {
        "alerts": [],
        "minutely": [{"dt": ts(2026, 7, 24, 10, 0), "precipitation": 5.0}],
        "hourly": [hour(-2, temp=22.0, pop=0.9, weather=[{"id": 500}])],
        "daily": [{"temp": {"min": 18.0, "max": 23.0}, "uvi": 3.0}],
    },
    "parasol_uvi": {
        "alerts": [],
        "minutely": [],
        "daily": [{"temp": {"min": 18.0, "max": 26.0}, "uvi": 7.8}],
        "current": {"uvi": 7.8, "temp": 26.0},
    },
    "parasol_uvi_매우높음": {
        "alerts": [],
        "hourly": [hour(1, temp=26.0, uvi=9.5, weather=[{"id": 800}])],
        "daily": [{"temp": {"min": 20.0, "max": 26.0}}],
    },
    "parasol_기온만": {
        "alerts": [],
        "hourly": [hour(1, temp=29.0, uvi=1.0, weather=[{"id": 800}])],
        "daily": [{"temp": {"min": 24.0, "max": 29.0}}],
    },
    "jacket_일교차": {
        "alerts": [],
        "minutely": [],
        "daily": [{"temp": {"min": 12.0, "max": 23.5}, "uvi": 4.0}],
    },
    "none_쾌적": {
        "alerts": [],
        "minutely": [],
        "daily": [{"temp": {"min": 18.0, "max": 23.0}, "uvi": 3.5}],
    },
    "onecall_4.0_data배열": {
        # 4.0 /current 는 current 대신 data 배열로 준다
        "data": [{"temp": 27.5, "feels_like": 29.0, "uvi": 5.0}],
        "alerts": [],
        "daily": [{"temp": {"min": 20.0, "max": 28.5}, "uvi": 5.0}],
    },
    "hourly_없음_current로_대체": {
        "alerts": [],
        "hourly": [],
        "current": {"temp": 30.0, "feels_like": 33.0, "uvi": 7.0},
        "daily": [{"temp": {"min": 24.0, "max": 30.0}, "uvi": 7.0}],
    },
    "hourly_없음_daily로_대체": {
        "alerts": [],
        "current": {},
        "daily": [{"temp": {"min": 15.0, "max": 27.0}, "feels_like": {"day": 28.0}, "uvi": 6.5}],
    },
    "전부_비어있음": {},
    "daily_없음": {
        "alerts": [],
        "hourly": [hour(1, temp=21.0, feels_like=20.0, uvi=2.0, weather=[{"id": 800}])],
    },
    "hourly_값_일부_누락": {
        # temp/feels_like/uvi 가 없는 항목의 대체 규칙 검증
        "alerts": [],
        "current": {"temp": 24.0, "feels_like": 25.0},
        "hourly": [
            hour(1, weather=[{"id": 800}]),
            hour(2, temp=26.0, weather=[{"id": 800}]),
        ],
        "daily": [{"temp": {"min": 20.0, "max": 26.0}}],
    },
    "daily_min만_없음": {
        "alerts": [],
        "hourly": [hour(1, temp=22.0, weather=[{"id": 800}])],
        "daily": [{"temp": {"max": 22.0}}],
    },
    "내일_예보는_제외": {
        # 오늘 자정 이후 항목은 max 계산에서 빠진다
        "alerts": [],
        "current": {"temp": 20.0, "feels_like": 20.0},
        "hourly": [
            hour(1, temp=21.0, uvi=1.0, weather=[{"id": 800}]),
            hour(30, temp=35.0, uvi=11.0, weather=[{"id": 800}]),
        ],
        "daily": [{"temp": {"min": 18.0, "max": 21.0}}],
    },
}


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_evaluate_matches_golden(name):
    """기존 공개 필드는 유지하고, 새 준비물 필드는 별도 계약으로 더한다."""
    actual = evaluate(bundle_from_onecall(FIXTURES[name]), now_ts=NOW)
    assert {key: actual[key] for key in EXPECTED[name]} == EXPECTED[name], f"[{name}] 판정 불일치"


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_key_order_preserved(name):
    """새 preparations 는 기존 공개 필드 뒤에만 추가한다."""
    actual = evaluate(bundle_from_onecall(FIXTURES[name]), now_ts=NOW)
    assert list(actual)[:len(EXPECTED[name])] == list(EXPECTED[name])


def test_golden_covers_every_fixture():
    """픽스처를 추가했으면 골든도 다시 만들어야 한다"""
    assert set(EXPECTED) == set(FIXTURES)


def test_fixtures_cover_all_states():
    """픽스처가 5개 상태를 모두 훑는지 확인 (커버리지 누락 방지)"""
    assert {v["state_code"] for v in EXPECTED.values()} == {"ALERT", "UMBRELLA", "PARASOL", "JACKET", "NONE"}
