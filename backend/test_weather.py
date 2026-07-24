import pytest
import os
from datetime import datetime, timezone, timedelta
from locations import HUB_LOCATIONS
from main import generate_weather_json, evaluate_weather, evaluate_weather_v2, is_daytime_kst

KST = timezone(timedelta(hours=9))

def test_hub_locations_structure():
    """HUB_LOCATIONS 50개 거점 정보 스키마 및 무결성 검증"""
    assert len(HUB_LOCATIONS) == 50

    ids = set()
    for loc in HUB_LOCATIONS:
        assert "id" in loc and isinstance(loc["id"], str)
        assert loc["id"] not in ids, f"중복된 location id: {loc['id']}"
        ids.add(loc["id"])

        assert "group" in loc and len(loc["group"]) > 0
        assert "display_name" in loc and len(loc["display_name"]) > 0
        assert "lat" in loc and 33.0 <= loc["lat"] <= 39.0
        assert "lon" in loc and 124.0 <= loc["lon"] <= 132.0

def test_generate_weather_json_schema():
    """50개 권역별 생성 JSON 스키마 (name: 서울_강남 형태 및 group/display_name) 검증"""
    test_out = "_test_weather_all.json"
    try:
        result = generate_weather_json(api_key=None, output_path=test_out)

        assert result["meta"]["total_locations"] == 50
        assert len(result["data"]) == 50

        # 예시: seoul_south (서울_강남) 검증
        seoul_south = result["data"].get("seoul_south")
        assert seoul_south is not None
        assert seoul_south["group"] == "서울"
        assert seoul_south["display_name"] == "강남"
        assert seoul_south["name"] == "서울_강남"
        assert "recommendation" in seoul_south
    finally:
        if os.path.exists(test_out):
            os.remove(test_out)

def test_daytime_kst_filtering():
    """KST 낮 시간대(09:00 ~ 18:00) 필터링 유틸리티 테스트"""
    dt_12 = int(datetime(2026, 7, 24, 12, 0, tzinfo=KST).timestamp())
    assert is_daytime_kst(dt_12) is True

    dt_22 = int(datetime(2026, 7, 24, 22, 0, tzinfo=KST).timestamp())
    assert is_daytime_kst(dt_22) is False

def test_v2_alert_state():
    """V2 엣지케이스 1: alerts 배열이 존재할 경우 최우선 ALERT 반환"""
    mock_data = {
        "alerts": [{"event": "호우경보", "description": "많은 비가 예상됩니다"}],
        "current": {"temp": 22.0, "uvi": 2.0},
        "daily": [{"temp": {"min": 18.0, "max": 24.0}, "uvi": 2.0}]
    }
    result = evaluate_weather_v2(mock_data)
    assert result["state_code"] == "ALERT"
    assert result["alert_event"] == "호우경보"

def test_v2_umbrella_state():
    """V2 엣지케이스 2: 15분 예보 중 강수 감지 시 UMBRELLA 및 rain_start_time 반환"""
    dt_rain = int(datetime(2026, 7, 24, 14, 15, tzinfo=KST).timestamp())
    mock_data = {
        "alerts": [],
        "minutely": [{"dt": dt_rain, "precipitation": 1.5}],
        "daily": [{"temp": {"min": 18.0, "max": 25.0}, "uvi": 3.0}]
    }
    result = evaluate_weather_v2(mock_data)
    assert result["state_code"] == "UMBRELLA"
    assert result["rain_start_time"] == "14:15"

def test_v2_parasol_state_uvi():
    """V2 엣지케이스 3: UVI >= 6.0 (높음) 감지 시 PARASOL 반환"""
    mock_data = {
        "alerts": [],
        "minutely": [],
        "daily": [{"temp": {"min": 18.0, "max": 26.0}, "uvi": 7.8}]
    }
    result = evaluate_weather_v2(mock_data)
    assert result["state_code"] == "PARASOL"
    assert result["max_uvi"] == 7.8

def test_v2_jacket_state_temp_diff():
    """V2 엣지케이스 4: 일교차 >= 10도 조건 시 JACKET 반환"""
    mock_data = {
        "alerts": [],
        "minutely": [],
        "daily": [{"temp": {"min": 12.0, "max": 23.5}, "uvi": 4.0}]
    }
    result = evaluate_weather_v2(mock_data)
    assert result["state_code"] == "JACKET"
    assert result["temp_diff"] == 11.5

def test_v2_none_state():
    """V2 엣지케이스 5: 모든 위험/기상 조건 미해당 시 NONE 반환"""
    mock_data = {
        "alerts": [],
        "minutely": [],
        "daily": [{"temp": {"min": 18.0, "max": 23.0}, "uvi": 3.5}]
    }
    result = evaluate_weather_v2(mock_data)
    assert result["state_code"] == "NONE"
