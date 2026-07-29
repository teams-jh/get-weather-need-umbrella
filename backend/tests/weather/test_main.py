"""수집·조립 계층(main) 동작 검증. 네트워크는 전부 가짜로 대체한다."""
import json
import os

import pytest

import weather.pipeline as main
from weather.evaluate import evaluate
from weather.providers import kma, openweather
from weather.providers.base import HourlyPoint, ProviderError, WeatherBundle


def _bundle(source, temp=25.0, alerts=None):
    return WeatherBundle(
        source=source,
        alerts=alerts or [],
        current_temp=temp,
        daily_max=temp,
        daily_min=temp - 5.0,
        hourly=[],
    )


@pytest.fixture
def out_path(tmp_path):
    return str(tmp_path / "weather_all.json")


def test_missing_api_key_records_failures_instead_of_dummies(out_path):
    """
    키가 없으면 값을 지어내지 않고 전 거점을 실패로 남긴다.
    그럴듯한 더미가 나가면 소비자가 정상 동작으로 오판한다.
    """
    result = main.generate_weather_json(api_key=None, output_path=out_path, kma_service_key=None)

    assert result["meta"]["status"] == "failed"
    assert result["meta"]["source"] == "Collection Failed (No Data)"
    assert result["meta"]["success_count"] == 0
    assert result["meta"]["failed_count"] == 50
    assert len(result["data"]) == 50, "거점 자체는 남겨야 소비자가 기본 거점으로 잘못 폴백하지 않는다"

    entry = result["data"]["seoul_south"]
    assert entry["status"] == "failed"
    assert "recommendation" not in entry, "실패 거점에 판정이 있으면 안 된다"
    assert "forecast" not in entry
    assert entry["error"]
    assert os.path.exists(out_path), "실패해도 산출물은 갱신한다"


def test_preset_requires_explicit_opt_in(monkeypatch, out_path):
    """프리셋은 옵트인일 때만 나오고, 그때도 status 로 실데이터와 구분된다"""
    monkeypatch.setattr(main, "PRESET_ENABLED", True)

    result = main.generate_weather_json(api_key=None, output_path=out_path, kma_service_key=None)

    assert result["meta"]["preset_count"] == 50
    assert result["meta"]["failed_count"] == 0
    entry = result["data"]["seoul_south"]
    assert entry["status"] == "preset"
    assert entry["recommendation"]["state_code"] == "UMBRELLA"
    assert "fetched_at" not in entry, "실제로 수집한 적이 없으므로 수집 시각을 달지 않는다"


def test_output_shape_is_preserved(monkeypatch, out_path):
    """프론트엔드가 읽는 구조가 바뀌지 않아야 한다"""
    monkeypatch.setattr(openweather, "fetch", lambda loc, api_key=None: _bundle(openweather.SOURCE))

    result = main.generate_weather_json(api_key="ow-key", output_path=out_path, kma_service_key=None)

    entry = result["data"]["seoul_south"]
    assert set(entry) == {
        "id", "name", "group", "display_name", "lat", "lon",
        "status", "fetched_at", "recommendation", "forecast",
    }
    assert entry["status"] == "ok"
    assert entry["name"] == "서울_강남"
    assert entry["group"] == "서울"
    assert entry["display_name"] == "강남"


def test_kma_primary_receives_alerts(monkeypatch, out_path):
    """
    기상청이 기준 provider 일 때도 특보가 전달되어야 한다.
    비교 모드에서만 특보를 받으면 전환 후 ALERT 가 통째로 사라진다.
    """
    monkeypatch.setattr(kma, "fetch_alerts", lambda stn_id, key, now=None: [f"폭염경보-{stn_id}"])

    seen = {}

    def fake_fetch(loc, service_key=None, alerts=None, now=None):
        seen[loc["id"]] = alerts
        return _bundle(kma.SOURCE, alerts=alerts)

    monkeypatch.setattr(kma, "fetch", fake_fetch)

    result = main.generate_weather_json(api_key="dummy-key", output_path=out_path, provider_name="kma")

    assert len(seen) == 50, "모든 거점이 조회되어야 한다"
    assert all(a for a in seen.values()), "특보가 비어 전달된 거점이 있다"
    # 특보가 판정까지 실제로 이어졌는지
    assert result["data"]["seoul_south"]["recommendation"]["state_code"] == "ALERT"


def test_dual_run_compares_without_changing_output(monkeypatch, out_path):
    """이중화 조회는 비교만 하고 사용자에게 나가는 값을 바꾸지 않는다"""
    monkeypatch.setattr(openweather, "fetch", lambda loc, api_key=None: _bundle(openweather.SOURCE, temp=25.0))
    monkeypatch.setattr(kma, "fetch_alerts", lambda stn_id, key, now=None: [])
    # 기상청은 기온을 더 높게 본다 → PARASOL 로 갈려서 불일치가 생긴다
    monkeypatch.setattr(kma, "fetch", lambda loc, key=None, alerts=None, now=None: _bundle(kma.SOURCE, temp=30.0))

    compare_path = out_path + ".compare"
    result = main.generate_weather_json(
        api_key="ow-key",
        output_path=out_path,
        kma_service_key="kma-key",
        compare_path=compare_path,
    )

    # 출력은 기준 provider(OpenWeather)의 판정이어야 한다
    assert result["data"]["seoul_south"]["recommendation"]["state_code"] == "NONE"
    assert openweather.SOURCE in result["meta"]["source"]

    with open(compare_path, encoding="utf-8") as f:
        comparison = json.load(f)
    assert comparison["primary"] == "openweather"
    assert comparison["secondary"] == "kma"
    assert comparison["compared"] == 50
    assert comparison["mismatched"] == 50, "기온이 다르므로 전부 불일치여야 한다"
    assert comparison["results"][0]["max_temp_diff"] == 5.0


def test_provider_failure_is_recorded_not_faked(monkeypatch, out_path):
    """
    실패한 거점은 실패로 남고, 성공한 거점은 정상 갱신된다.
    하나가 실패했다고 나머지 49개의 갱신까지 막으면 앱이 과거 날씨를 보여준다.
    """
    def flaky(loc, api_key=None):
        if loc["id"] == "seoul_south":
            raise ProviderError("일부러 실패")
        return _bundle(openweather.SOURCE)

    monkeypatch.setattr(openweather, "fetch", flaky)

    result = main.generate_weather_json(api_key="ow-key", output_path=out_path, kma_service_key=None)

    assert result["meta"]["status"] == "partial"
    assert "Failed: 1" in result["meta"]["source"]
    assert result["meta"]["failed_locations"] == ["seoul_south"]

    failed = result["data"]["seoul_south"]
    assert failed["status"] == "failed"
    assert "recommendation" not in failed
    assert "일부러 실패" in failed["error"]

    assert result["data"]["busan_center"]["status"] == "ok"
    assert len(result["data"]) == 50


def test_source_reflects_actual_path(monkeypatch, out_path):
    """묶음이 들고 온 실제 출처가 meta.source 에 드러나야 한다 (4.0 vs 2.5)"""
    def mixed(loc, api_key=None):
        source = openweather.SOURCE_FORECAST25 if loc["id"] == "seoul_south" else openweather.SOURCE_ONECALL30
        return _bundle(source)

    monkeypatch.setattr(openweather, "fetch", mixed)

    result = main.generate_weather_json(api_key="ow-key", output_path=out_path, kma_service_key=None)
    assert openweather.SOURCE_ONECALL30 in result["meta"]["source"]
    assert openweather.SOURCE_FORECAST25 in result["meta"]["source"]


def test_onecall_response_flows_through_to_a_verdict():
    """One Call 응답이 정규화를 거쳐 판정까지 이어져야 한다"""
    raw = {"alerts": [{"event": "호우경보"}], "daily": [{"temp": {"min": 18.0, "max": 24.0}}]}
    assert evaluate(openweather.bundle_from_onecall(raw))["state_code"] == "ALERT"


def test_forecast25_response_flows_through_to_a_verdict():
    """2.5 Forecast 응답도 같은 판정 경로를 탄다 (One Call 실패 시의 폴백)"""
    forecast = [{"dt": 1, "main": {"temp": 20.0}, "weather": [{"id": 800}]}]
    verdict = evaluate(openweather.bundle_from_forecast25(forecast))
    assert verdict["state_code"] in {"NONE", "PARASOL", "JACKET", "UMBRELLA"}
