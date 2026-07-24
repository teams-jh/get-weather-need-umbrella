import pytest
from datetime import datetime, timezone, timedelta
from main import evaluate_weather, is_daytime_kst

KST = timezone(timedelta(hours=9))

def create_mock_forecast_item(temp: float, weather_id: int, hour_kst: int = 12) -> dict:
    """
    KST 기준 특정 시각(hour_kst) 및 온도, 날씨 ID를 갖는 OpenWeatherMap 예보 Mock 항목 생성
    """
    # 2026-07-24 12:00:00 KST
    now_kst = datetime(2026, 7, 24, hour_kst, 0, 0, tzinfo=KST)
    dt_timestamp = int(now_kst.timestamp())

    return {
        "dt": dt_timestamp,
        "main": {
            "temp": temp,
            "temp_max": temp,
            "temp_min": temp
        },
        "weather": [
            {
                "id": weather_id,
                "main": "Rain" if weather_id < 700 else "Clear",
                "description": "mock weather"
            }
        ]
    }

def test_daytime_kst_filtering():
    """KST 낮 시간대(09:00 ~ 18:00) 필터링 유틸리티 테스트"""
    # 12:00 KST -> True
    dt_12 = int(datetime(2026, 7, 24, 12, 0, tzinfo=KST).timestamp())
    assert is_daytime_kst(dt_12) is True

    # 22:00 KST -> False
    dt_22 = int(datetime(2026, 7, 24, 22, 0, tzinfo=KST).timestamp())
    assert is_daytime_kst(dt_22) is False

def test_edge_case_1_umbrella_priority():
    """
    PRD 4.1 엣지케이스 1:
    기온이 30도(고온)이지만 약한 비(weather_id = 500 < 700)가 내리는 조건
    -> UMBRELLA 반환 확인 (강수 우선순위 테스트)
    """
    forecast_list = [
        create_mock_forecast_item(temp=30.0, weather_id=500, hour_kst=14)
    ]
    result = evaluate_weather(forecast_list)
    assert result["state_code"] == "UMBRELLA"
    assert result["max_temp"] == 30.0

def test_edge_case_2_parasol_boundary():
    """
    PRD 4.1 엣지케이스 2:
    강수 없고(weather_id = 800 >= 700), 기온이 정확히 28.0도인 맑은 조건
    -> PARASOL 반환 확인 (경계값 테스트)
    """
    forecast_list = [
        create_mock_forecast_item(temp=28.0, weather_id=800, hour_kst=14)
    ]
    result = evaluate_weather(forecast_list)
    assert result["state_code"] == "PARASOL"
    assert result["max_temp"] == 28.0

def test_edge_case_3_none_boundary():
    """
    PRD 4.1 엣지케이스 3:
    강수 없고(weather_id = 804 >= 700), 기온이 27.9도인 흐린 조건
    -> NONE 반환 확인
    """
    forecast_list = [
        create_mock_forecast_item(temp=27.9, weather_id=804, hour_kst=14)
    ]
    result = evaluate_weather(forecast_list)
    assert result["state_code"] == "NONE"
    assert result["max_temp"] == 27.9
