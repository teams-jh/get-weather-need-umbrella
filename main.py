import json
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from locations import HUB_LOCATIONS

# KST (Korea Standard Time, UTC+9)
KST = timezone(timedelta(hours=9))

def is_daytime_kst(dt_timestamp: int) -> bool:
    """
    주어진 UNIX 타임스탬프가 KST 기준 오늘/해당 일자의 낮 시간대(09:00 ~ 18:00)에 속하는지 여부
    """
    dt_kst = datetime.fromtimestamp(dt_timestamp, tz=KST)
    return 9 <= dt_kst.hour <= 18

def evaluate_weather(forecast_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    PRD 알고리즘 명세에 따른 날씨 판별 함수:
    1. KST 기준 낮 시간대 (09:00 ~ 18:00) 데이터 필터링
    2. 낮 시간 데이터 중 weather_id < 700 (강수) 최우선 -> UMBRELLA
    3. 강수 없고 최고기온 >= 28.0도 -> PARASOL
    4. 강수 없고 최고기온 < 28.0도 -> NONE
    """
    # 낮 시간대 (09:00 ~ 18:00) 데이터 필터링
    daytime_forecasts = [f for f in forecast_list if is_daytime_kst(f.get("dt", 0))]
    
    # 만약 낮 시간대 데이터가 없으면 전체 forecast 중 가장 가까운 데이터 활용
    target_forecasts = daytime_forecasts if daytime_forecasts else forecast_list[:4]

    has_precipitation = False
    max_temp = -999.0

    for item in target_forecasts:
        # 기온 추출
        temp = item.get("main", {}).get("temp_max", item.get("main", {}).get("temp", 0.0))
        if temp > max_temp:
            max_temp = temp

        # 날씨 ID 검사 (700 미만은 비, 눈, 소나기 등 강수)
        weather_entries = item.get("weather", [])
        for w in weather_entries:
            w_id = w.get("id", 800)
            if w_id < 700:
                has_precipitation = True

    # 1. UMBRELLA 판별 (강수 최우선)
    if has_precipitation:
        return {
            "state_code": "UMBRELLA",
            "message": "비가 꽤 많이 와요. 우산을 꼭 챙기세요!",
            "max_temp": round(max_temp, 1)
        }
    
    # 2. PARASOL 판별 (최고기온 >= 28.0도)
    if max_temp >= 28.0:
        return {
            "state_code": "PARASOL",
            "message": "볕이 뜨거워요. 양산 챙길까요?",
            "max_temp": round(max_temp, 1)
        }

    # 3. NONE 판별 (기온 < 28.0도 및 강수 없음)
    return {
        "state_code": "NONE",
        "message": "가볍게 빈손으로 나가도 좋아요.",
        "max_temp": round(max_temp, 1)
    }

def generate_weather_json(api_key: str = None, output_path: str = "weather_all.json") -> Dict[str, Any]:
    """
    15개 거점 도시 날씨 수집 및 weather_all.json 생성
    """
    import requests

    result_data = {}
    
    for loc in HUB_LOCATIONS:
        loc_id = loc["id"]
        lat = loc["lat"]
        lon = loc["lon"]

        if api_key:
            url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={api_key}&units=metric"
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            api_data = resp.json()
            forecast_list = api_data.get("list", [])
            recommendation = evaluate_weather(forecast_list)
        else:
            # API 키가 제공되지 않을 경우 테스트용 기본 데이터 매핑
            default_states = {
                "seoul": ("UMBRELLA", "비가 꽤 많이 와요. 우산 챙길까요?", 24.5),
                "busan": ("PARASOL", "볕이 뜨거워요. 양산 챙길까요?", 28.4),
                "suwon": ("NONE", "가볍게 빈손으로 나가도 좋아요.", 26.2),
            }
            code, msg, temp = default_states.get(loc_id, ("NONE", "가볍게 빈손으로 나가도 좋아요.", 25.0))
            recommendation = {
                "state_code": code,
                "message": msg,
                "max_temp": temp
            }

        result_data[loc_id] = {
            "id": loc_id,
            "name": loc["name"],
            "lat": lat,
            "lon": lon,
            "recommendation": recommendation
        }

    output = {
        "meta": {
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "OpenWeatherMap",
            "total_locations": len(HUB_LOCATIONS)
        },
        "data": result_data
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Successfully generated {output_path} with {len(result_data)} locations.")
    return output

if __name__ == "__main__":
    api_key_env = os.environ.get("OPENWEATHER_API_KEY")
    generate_weather_json(api_key=api_key_env)
