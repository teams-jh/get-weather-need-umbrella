"""provider 계층 단위 테스트 (네트워크 없이 도는 부분만)."""
from datetime import datetime, timedelta, timezone

import pytest

from weather.evaluate import evaluate
from weather.providers import get_provider, kma, openweather
from weather.providers import base
from weather.providers.base import HourlyPoint, WeatherBundle
from weather.providers.feels_like import feels_like, summer_feels_like, winter_feels_like

KST = timezone(timedelta(hours=9))


def at(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=KST)


# --- provider 등록 ---------------------------------------------------------

def test_get_provider():
    assert get_provider("openweather") is openweather
    assert get_provider("kma") is kma
    with pytest.raises(ValueError):
        get_provider("없는provider")


def test_providers_expose_required_interface():
    """두 provider 가 같은 계약을 노출해야 한다"""
    for provider in (openweather, kma):
        assert hasattr(provider, "fetch")
        assert isinstance(provider.NAME, str)
        assert isinstance(provider.SOURCE, str)


# --- 체감온도 --------------------------------------------------------------

def test_summer_feels_like_raises_with_humidity():
    """고온다습에서는 체감온도가 기온보다 높아야 한다"""
    assert summer_feels_like(28.0, 82.0) > 28.0
    # 같은 기온이면 습할수록 더 덥게 느껴진다
    assert summer_feels_like(30.0, 90.0) > summer_feels_like(30.0, 40.0)


def test_winter_feels_like_drops_with_wind():
    """저온에서는 바람이 셀수록 체감온도가 떨어져야 한다"""
    assert winter_feels_like(-5.0, 5.0) < -5.0
    assert winter_feels_like(0.0, 10.0) < winter_feels_like(0.0, 2.0)


def test_feels_like_picks_formula_by_season():
    # 여름: 습도 기반
    assert feels_like(30.0, 80.0, 2.0) == pytest.approx(summer_feels_like(30.0, 80.0))
    # 겨울: 풍속 기반
    assert feels_like(-5.0, 60.0, 5.0) == pytest.approx(winter_feels_like(-5.0, 5.0))


def test_feels_like_falls_back_to_temp_outside_ranges():
    """적용 범위 밖(봄·가을, 무풍 저온)에서는 기온을 그대로 쓴다"""
    assert feels_like(15.0, 60.0, 1.0) == 15.0        # 중간대
    assert feels_like(8.0, 60.0, 0.5) == 8.0          # 저온이지만 바람이 약함
    assert feels_like(None, 60.0, 3.0) is None        # 기온이 없으면 계산 불가


def test_feels_like_without_optional_inputs():
    """습도나 풍속이 없으면 기온으로 되돌아간다"""
    assert feels_like(30.0) == 30.0
    assert feels_like(-5.0, wind_ms=None) == -5.0


# --- 기상청 특보 제목 파싱 --------------------------------------------------

def test_parse_warning_title_single():
    assert kma._parse_warning_title(
        "[특보] 제07-145호 : 2026.07.28.10:00 / 폭염주의보 발표 (*)"
    ) == [("폭염주의보", True)]


def test_parse_warning_title_compound():
    """한 건에 발표와 해제가 섞여 올 수 있다"""
    assert kma._parse_warning_title(
        "[특보] 제07-144호 : 2026.07.27.16:00 / 폭염경보 변경·열대야주의보 해제·호우주의보 발표"
    ) == [("폭염경보", True), ("열대야주의보", False), ("호우주의보", True)]


def test_parse_warning_title_ignores_non_warning():
    """기상정보 등 특보가 아닌 제목은 무시한다"""
    assert kma._parse_warning_title("[정보] 제07-13호 : 2026.07.28.04:10") == []
    assert kma._parse_warning_title("") == []


# --- 특보 유형 정규화 -------------------------------------------------------

@pytest.mark.parametrize(
    ("event", "alert_type"),
    [
        ("폭염경보", "폭염"),
        ("열대야주의보", "열대야"),
        ("태풍경보", "태풍"),
        ("Heavy rain warning", "호우"),
        ("Tsunami Watch", "지진해일"),
    ],
)
def test_alert_type_is_normalized_for_both_providers(event, alert_type):
    assert evaluate(WeatherBundle(source="test", alerts=[event]))["alert_type"] == alert_type


@pytest.mark.parametrize(
    ("event", "display_name"),
    [
        ("폭염경보", "폭염경보"),
        ("Heat Warning Change", "폭염경보"),
        ("Heat Advisory", "폭염주의보"),
        ("Heavy Rain Warning", "호우경보"),
        ("Tsunami Watch", "지진해일 예비특보"),
        ("Air Quality Alert", "기상 특보"),
    ],
)
def test_alert_display_name_is_korean_and_preserves_kma_names(event, display_name):
    assert evaluate(WeatherBundle(source="test", alerts=[event]))["alert_event"] == display_name


def test_alert_keeps_all_active_events_and_types():
    verdict = evaluate(WeatherBundle(source="test", alerts=["폭염경보", "열대야주의보", "폭염경보"]))

    assert verdict["alert_event"] == "폭염경보"
    assert verdict["alert_events"] == ["폭염경보", "열대야주의보"]
    assert verdict["alert_type"] == "폭염"
    assert verdict["alert_types"] == ["폭염", "열대야"]
    assert verdict["title"] == "폭염경보 발령 중"


def test_alert_display_events_deduplicate_after_normalization():
    verdict = evaluate(WeatherBundle(source="test", alerts=["Heat Warning", "Heat Warning Change"]))
    assert verdict["alert_events"] == ["폭염경보"]
    assert verdict["preparations"][0]["title"] == "폭염경보 발령 중"


def test_rain_alert_and_forecast_return_independent_preparations():
    now = int(at(2026, 7, 28, 12, 0).timestamp())
    verdict = evaluate(
        WeatherBundle(
            source="test",
            alerts=["호우경보"],
            hourly=[HourlyPoint(dt=now + 3600, is_precip=True)],
        ),
        now_ts=now,
    )

    assert verdict["state_code"] == "ALERT"
    assert verdict["rain_start_time"] == "13:00"
    assert [item["type"] for item in verdict["preparations"]] == ["ALERT", "UMBRELLA"]


def test_all_matching_preparations_are_returned_without_alert_inference():
    now = int(at(2026, 7, 28, 12, 0).timestamp())
    verdict = evaluate(
        WeatherBundle(
            source="test",
            alerts=["폭염주의보"],
            hourly=[HourlyPoint(dt=now + 3600, is_precip=True, temp=31.0, uvi=7.0)],
            daily_max=31.0,
            daily_min=19.0,
        ),
        now_ts=now,
    )

    assert verdict["state_code"] == "ALERT"
    assert [item["type"] for item in verdict["preparations"]] == [
        "ALERT", "UMBRELLA", "PARASOL", "JACKET",
    ]


def test_alert_without_other_measurements_only_returns_alert_preparation():
    verdict = evaluate(WeatherBundle(source="test", alerts=["폭염주의보"]))
    assert [item["type"] for item in verdict["preparations"]] == ["ALERT"]


def test_is_night_uses_kst_hour():
    assert evaluate(WeatherBundle(source="test"), now_ts=int(at(2026, 7, 28, 5).timestamp()))["is_night"] is True
    assert evaluate(WeatherBundle(source="test"), now_ts=int(at(2026, 7, 28, 6).timestamp()))["is_night"] is False
    assert evaluate(WeatherBundle(source="test"), now_ts=int(at(2026, 7, 28, 19).timestamp()))["is_night"] is True


# --- 기상청 발표 기준시각 ---------------------------------------------------

def test_ncst_base_waits_for_publication():
    """초단기실황은 정시 자료가 40분 이후에 나온다"""
    assert kma._ncst_base(at(2026, 7, 28, 14, 39)) == ("20260728", "1300")
    assert kma._ncst_base(at(2026, 7, 28, 14, 40)) == ("20260728", "1400")


def test_vilage_base_uses_latest_published_slot():
    """단기예보는 02·05·08·11·14·17·20·23시 발표분 중 이미 나온 최신 것"""
    assert kma._vilage_base(at(2026, 7, 28, 14, 30)) == ("20260728", "1400")
    assert kma._vilage_base(at(2026, 7, 28, 14, 5)) == ("20260728", "1100")
    # 02시 발표 전에는 전날 23시 발표분
    assert kma._vilage_base(at(2026, 7, 28, 1, 0)) == ("20260727", "2300")


def test_uv_base_is_06_or_18():
    assert kma._uv_base(at(2026, 7, 28, 12, 0)) == "2026072806"
    assert kma._uv_base(at(2026, 7, 28, 19, 0)) == "2026072818"
    # 06시 이전이면 전날 18시 발표분
    assert kma._uv_base(at(2026, 7, 28, 3, 0)) == "2026072718"


def test_nearest_uvi_rejects_distant_samples():
    """3시간 간격이라 2시간을 넘게 벌어지면 값을 쓰지 않는다"""
    base = int(at(2026, 7, 28, 12, 0).timestamp())
    series = {base: 7.0}
    assert kma._nearest_uvi(series, base) == 7.0
    assert kma._nearest_uvi(series, base + 3600) == 7.0
    assert kma._nearest_uvi(series, base + 3 * 3600) is None
    assert kma._nearest_uvi({}, base) is None


# --- OpenWeather 정규화 -----------------------------------------------------

def test_openweather_precip_needs_weather_entry():
    """weather 배열이 비면 pop 이 높아도 강수로 보지 않는다 (기존 동작 보존)"""
    assert openweather._is_precip([], 0.9) is False
    assert openweather._is_precip([{"id": 800}], 0.5) is True
    assert openweather._is_precip([{"id": 500}], 0.0) is True
    assert openweather._is_precip([{"id": 800}], 0.1) is False


def test_forecast25_bundle_leaves_uvi_unknown():
    """2.5 는 자외선을 주지 않으므로 값을 지어내지 않는다"""
    bundle = openweather.bundle_from_forecast25([
        {"dt": 1, "main": {"temp": 20.0, "temp_max": 22.0, "temp_min": 15.0}, "weather": [{"id": 800}]},
    ])
    assert bundle.current_uvi is None
    assert bundle.daily_max == 22.0
    assert bundle.daily_min == 15.0
    assert all(h.uvi is None for h in bundle.hourly)


# --- 판정이 출처를 구분하지 않는지 ------------------------------------------

def test_evaluate_is_source_agnostic():
    """같은 내용의 묶음이면 출처 이름이 달라도 판정이 같아야 한다"""
    now = int(at(2026, 7, 28, 12, 0).timestamp())
    points = [HourlyPoint(dt=now + 3600, temp=29.0, feels_like=31.0, uvi=7.0)]
    a = WeatherBundle(source="openweather", hourly=points, daily_max=29.0, daily_min=24.0)
    b = WeatherBundle(source="기상청", hourly=points, daily_max=29.0, daily_min=24.0)
    assert evaluate(a, now_ts=now) == evaluate(b, now_ts=now)


# --- 엔드포인트 우선순위 ---

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _record_calls(monkeypatch, responder):
    """openweather.fetch 가 부른 URL 순서를 기록한다."""
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        return responder(url)

    monkeypatch.setattr(openweather.requests, "get", fake_get)
    return calls


SEOUL = {"id": "seoul_south", "lat": 37.4979, "lon": 127.0276}


def test_one_call_30_is_tried_first(monkeypatch):
    """3.0 이 성공하면 다른 엔드포인트는 부르지 않는다."""
    calls = _record_calls(
        monkeypatch, lambda url: _FakeResponse({"current": {"temp": 20.0}, "daily": [], "hourly": []})
    )

    bundle = openweather.fetch(SEOUL, api_key="k")

    assert len(calls) == 1
    assert "data/3.0/onecall" in calls[0]
    assert bundle.source == openweather.SOURCE_ONECALL30


def test_falls_back_to_25_before_40_current(monkeypatch):
    """3.0 이 실패하면 2.5 를 먼저 쓰고, 되면 4.0 /current 는 부르지 않는다."""

    def responder(url):
        if "data/3.0/onecall" in url:
            raise RuntimeError("401 Unauthorized")
        if "data/2.5/forecast" in url:
            return _FakeResponse({"list": [{"dt": 1, "main": {"temp": 20.0}, "weather": [{"id": 800}]}]})
        raise AssertionError(f"2.5 가 성공했는데 추가 호출이 일어났다: {url}")

    calls = _record_calls(monkeypatch, responder)

    bundle = openweather.fetch(SEOUL, api_key="k")

    assert "data/3.0/onecall" in calls[0]
    assert "data/2.5/forecast" in calls[1]
    assert not any("4.0/onecall/current" in url for url in calls)
    assert bundle.source == openweather.SOURCE_FORECAST25


def test_40_current_is_last_resort_and_has_no_forecast(monkeypatch):
    """
    3.0·2.5 가 모두 실패했을 때만 4.0 /current 를 쓴다.
    이 경로는 현재 스냅샷만 주므로 예보도 특보도 비어 있고, 그래서 알림이 나가지 않는다.
    """

    def responder(url):
        if "4.0/onecall/current" in url:
            return _FakeResponse({"data": [{"dt": 1, "temp": 23.4, "feels_like": 24.1, "uvi": 4.2}]})
        raise RuntimeError("unavailable")

    calls = _record_calls(monkeypatch, responder)

    bundle = openweather.fetch(SEOUL, api_key="k")

    assert ["3.0" in calls[0], "2.5" in calls[1], "4.0" in calls[2]] == [True, True, True]
    assert bundle.source == openweather.SOURCE_ONECALL40_CURRENT
    assert bundle.daily_forecast == []
    assert bundle.alerts == []
    assert bundle.current_temp == 23.4


def test_provider_error_when_every_endpoint_fails(monkeypatch):
    _record_calls(monkeypatch, lambda url: (_ for _ in ()).throw(RuntimeError("down")))

    with pytest.raises(base.ProviderError):
        openweather.fetch(SEOUL, api_key="k")


# --- 일자별 예보 ---

def test_onecall_daily_forecast_marks_rainy_days():
    """One Call 의 daily 배열은 그대로 접는다 (hourly 48시간보다 멀리 본다)."""
    sat = int(datetime(2026, 8, 1, 12, 0, tzinfo=KST).timestamp())
    sun = int(datetime(2026, 8, 2, 12, 0, tzinfo=KST).timestamp())

    bundle = openweather.bundle_from_onecall(
        {
            "current": {"temp": 20.0},
            "daily": [
                {"dt": sat, "pop": 0.8, "weather": [{"id": 500}], "temp": {"min": 21.0, "max": 27.0}},
                {"dt": sun, "pop": 0.1, "weather": [{"id": 800}], "temp": {"min": 22.0, "max": 29.0}},
            ],
        }
    )

    assert [d.date for d in bundle.daily_forecast] == ["2026-08-01", "2026-08-02"]
    assert bundle.daily_forecast[0].has_rain is True
    assert bundle.daily_forecast[1].has_rain is False


def test_daily_forecast_from_hourly_folds_by_kst_date():
    """시간 예보만 있는 출처는 KST 날짜로 접는다. 하루 중 한 번이라도 비면 그 날은 비."""
    morning = int(datetime(2026, 8, 1, 9, 0, tzinfo=KST).timestamp())
    evening = int(datetime(2026, 8, 1, 21, 0, tzinfo=KST).timestamp())
    next_day = int(datetime(2026, 8, 2, 9, 0, tzinfo=KST).timestamp())

    forecast = base.daily_forecast_from_hourly(
        [
            HourlyPoint(dt=morning, pop=0.1, is_precip=False),
            HourlyPoint(dt=evening, pop=0.7, is_precip=True),
            HourlyPoint(dt=next_day, pop=0.0, is_precip=False),
        ]
    )

    assert [d.date for d in forecast] == ["2026-08-01", "2026-08-02"]
    assert (forecast[0].has_rain, forecast[0].pop) == (True, 0.7)
    assert forecast[1].has_rain is False


def test_daily_forecast_is_capped_to_forecast_days():
    """쓰이지 않는 날짜까지 담지 않는다 (weather_all.json 은 자주 커밋된다)."""
    hourly = [
        HourlyPoint(dt=int(datetime(2026, 8, day, 12, 0, tzinfo=KST).timestamp()))
        for day in range(1, 9)
    ]
    assert len(base.daily_forecast_from_hourly(hourly)) == base.FORECAST_DAYS


def test_forecast25_derives_daily_forecast_from_three_hour_slots():
    slot_a = int(datetime(2026, 8, 1, 9, 0, tzinfo=KST).timestamp())
    slot_b = int(datetime(2026, 8, 1, 21, 0, tzinfo=KST).timestamp())

    bundle = openweather.bundle_from_forecast25(
        [
            {"dt": slot_a, "pop": 0.1, "weather": [{"id": 800}], "main": {"temp": 24.0}},
            {"dt": slot_b, "pop": 0.7, "weather": [{"id": 500}], "main": {"temp": 21.0}},
        ]
    )

    assert len(bundle.daily_forecast) == 1
    assert bundle.daily_forecast[0].date == "2026-08-01"
    assert bundle.daily_forecast[0].has_rain is True
