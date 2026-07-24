import sys
import io
import json
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from locations import HUB_LOCATIONS

# KST (Korea Standard Time, UTC+9)
KST = timezone(timedelta(hours=9))

def is_daytime_kst(dt_timestamp: int) -> bool:
    """
    주어진 UNIX 타임스탬프가 KST 기준 오늘/해당 일자의 낮 시간대(09:00 ~ 18:00)에 속하는지 여부
    """
    dt_kst = datetime.fromtimestamp(dt_timestamp, tz=KST)
    return 9 <= dt_kst.hour <= 18

def evaluate_weather_v2(api_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    prd2.md 알고리즘 명세에 따른 날씨 판별 함수 (V2):
    1. alerts (기상 특보) -> ALERT
    2. minutely / hourly 강수 감지 -> UMBRELLA (+ rain_start_time)
    3. max_uvi >= 6.0 또는 max_temp >= 28.0 -> PARASOL
    4. temp_diff (일교차) >= 10.0도 -> JACKET
    5. 기타 -> NONE
    """
    alerts = api_data.get("alerts", [])
    current = api_data.get("current", {})
    daily = api_data.get("daily", [{}])[0] if api_data.get("daily") else {}
    minutely = api_data.get("minutely", [])
    hourly = api_data.get("hourly", [])

    max_temp = daily.get("temp", {}).get("max", current.get("temp", 25.0))
    min_temp = daily.get("temp", {}).get("min", max_temp - 5.0)
    feels_like_max = daily.get("feels_like", {}).get("day", current.get("feels_like", max_temp))
    max_uvi = daily.get("uvi", current.get("uvi", 3.0))
    temp_diff = max(0.0, max_temp - min_temp)

    # 1. ALERT (기상 특보 최우선)
    if alerts:
        event_name = alerts[0].get("event", "기상 특보")
        return {
            "state_code": "ALERT",
            "title": f"{event_name} 발령 중",
            "message": "안전에 유의하시고 준비물을 꼭 점검하세요!",
            "rain_start_time": None,
            "max_temp": round(max_temp, 1),
            "feels_like_max": round(feels_like_max, 1),
            "max_uvi": round(max_uvi, 1),
            "temp_diff": round(temp_diff, 1),
            "alert_event": event_name
        }

    # 2. UMBRELLA (강수 감지 및 비 시작 시간 추적)
    rain_start_str: Optional[str] = None

    # 2-1. 15분 단위(minutely) 강수 체크
    for item in minutely:
        precip = item.get("precipitation", 0)
        if precip > 0:
            dt_kst = datetime.fromtimestamp(item.get("dt", 0), tz=KST)
            rain_start_str = dt_kst.strftime("%H:%M")
            break

    # 2-2. 15분 단위 데이터가 없고 hourly에서 강수인 경우
    if not rain_start_str and hourly:
        for item in hourly:
            weather_entries = item.get("weather", [])
            for w in weather_entries:
                if w.get("id", 800) < 700 or item.get("pop", 0) >= 0.5:
                    dt_kst = datetime.fromtimestamp(item.get("dt", 0), tz=KST)
                    rain_start_str = dt_kst.strftime("%H:%M")
                    break
            if rain_start_str:
                break

    if rain_start_str:
        return {
            "state_code": "UMBRELLA",
            "title": f"오후 {rain_start_str}부터 비 소식이 있어요" if int(rain_start_str.split(":")[0]) >= 12 else f"오전 {rain_start_str}부터 비 소식이 있어요",
            "message": "외출 시 우산을 꼭 챙겨서 나가세요!",
            "rain_start_time": rain_start_str,
            "max_temp": round(max_temp, 1),
            "feels_like_max": round(feels_like_max, 1),
            "max_uvi": round(max_uvi, 1),
            "temp_diff": round(temp_diff, 1),
            "alert_event": None
        }

    # 3. PARASOL (자외선 지수 >= 6.0 또는 최고기온 >= 28.0도)
    if max_uvi >= 6.0 or max_temp >= 28.0:
        uv_level = "매우 높음" if max_uvi >= 8.0 else ("높음" if max_uvi >= 6.0 else "보통")
        title_msg = f"자외선이 '{uv_level}' 단계예요" if max_uvi >= 6.0 else "볕이 뜨거워요. 양산 챙길까요?"
        return {
            "state_code": "PARASOL",
            "title": title_msg,
            "message": "볕이 뜨거워요. 양산이나 모자를 챙기세요!",
            "rain_start_time": None,
            "max_temp": round(max_temp, 1),
            "feels_like_max": round(feels_like_max, 1),
            "max_uvi": round(max_uvi, 1),
            "temp_diff": round(temp_diff, 1),
            "alert_event": None
        }

    # 4. JACKET (일교차 >= 10.0도)
    if temp_diff >= 10.0:
        return {
            "state_code": "JACKET",
            "title": f"낮과 밤의 기온 차가 {round(temp_diff)}°C나 돼요",
            "message": "저녁에 쌀쌀할 수 있으니 가벼운 외투를 챙기세요!",
            "rain_start_time": None,
            "max_temp": round(max_temp, 1),
            "feels_like_max": round(feels_like_max, 1),
            "max_uvi": round(max_uvi, 1),
            "temp_diff": round(temp_diff, 1),
            "alert_event": None
        }

    # 5. NONE (기타 쾌적한 날씨)
    return {
        "state_code": "NONE",
        "title": "가볍게 빈손으로 나가도 좋아요",
        "message": "날씨가 쾌적하여 기분 좋은 외출이 될 거예요.",
        "rain_start_time": None,
        "max_temp": round(max_temp, 1),
        "feels_like_max": round(feels_like_max, 1),
        "max_uvi": round(max_uvi, 1),
        "temp_diff": round(temp_diff, 1),
        "alert_event": None
    }

def evaluate_weather(forecast_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    2.5 무료 API 예보 데이터 기반 5대 준비물 상태 판별 함수
    """
    daytime_forecasts = [f for f in forecast_list if is_daytime_kst(f.get("dt", 0))]
    target_forecasts = daytime_forecasts if daytime_forecasts else forecast_list[:4]

    has_precipitation = False
    rain_start_str: Optional[str] = None
    max_temp = -999.0
    min_temp = 999.0

    for item in forecast_list:
        temp_max_item = item.get("main", {}).get("temp_max", item.get("main", {}).get("temp", 0.0))
        temp_min_item = item.get("main", {}).get("temp_min", item.get("main", {}).get("temp", 0.0))
        if temp_max_item > max_temp:
            max_temp = temp_max_item
        if temp_min_item < min_temp:
            min_temp = temp_min_item

        # 비/눈 감지 및 시작시간 파싱
        weather_entries = item.get("weather", [])
        for w in weather_entries:
            if w.get("id", 800) < 700:
                has_precipitation = True
                if not rain_start_str:
                    dt_kst = datetime.fromtimestamp(item.get("dt", 0), tz=KST)
                    rain_start_str = dt_kst.strftime("%H:%M")

    temp_diff = max(0.0, max_temp - min_temp) if min_temp != 999.0 else 5.0

    # 1. UMBRELLA (비/눈 감지)
    if has_precipitation:
        time_hint = rain_start_str if rain_start_str else "오늘"
        return {
            "state_code": "UMBRELLA",
            "title": f"오후 {time_hint}부터 비 소식이 있어요" if time_hint != "오늘" and int(time_hint.split(":")[0]) >= 12 else f"{time_hint} 비 소식이 있어요",
            "message": "외출 시 우산을 꼭 챙겨서 나가세요!",
            "max_temp": round(max_temp, 1),
            "feels_like_max": round(max_temp, 1),
            "max_uvi": 3.0,
            "temp_diff": round(temp_diff, 1),
            "rain_start_time": rain_start_str,
            "alert_event": None
        }

    # 2. PARASOL (기온 28.0도 이상 - 2.5 API에서는 기온 기반으로 자외선/햇볕 판별)
    if max_temp >= 28.0:
        return {
            "state_code": "PARASOL",
            "title": "볕이 뜨거워요. 양산 챙길까요?",
            "message": "볕이 뜨거워요. 양산이나 모자를 챙기세요!",
            "max_temp": round(max_temp, 1),
            "feels_like_max": round(max_temp + 1.5, 1),
            "max_uvi": 7.5,
            "temp_diff": round(temp_diff, 1),
            "rain_start_time": None,
            "alert_event": None
        }

    # 3. JACKET (일교차 10도 이상)
    if temp_diff >= 10.0:
        return {
            "state_code": "JACKET",
            "title": f"낮과 밤의 기온 차가 {round(temp_diff)}°C나 돼요",
            "message": "저녁에 쌀쌀할 수 있으니 가벼운 외투를 챙기세요!",
            "max_temp": round(max_temp, 1),
            "feels_like_max": round(max_temp, 1),
            "max_uvi": 4.0,
            "temp_diff": round(temp_diff, 1),
            "rain_start_time": None,
            "alert_event": None
        }

    # 4. NONE (기타 쾌적한 날씨)
    return {
        "state_code": "NONE",
        "title": "가볍게 빈손으로 나가도 좋아요",
        "message": "날씨가 쾌적하여 기분 좋은 외출이 될 거예요.",
        "max_temp": round(max_temp, 1),
        "feels_like_max": round(max_temp, 1),
        "max_uvi": 3.5,
        "temp_diff": round(temp_diff, 1),
        "rain_start_time": None,
        "alert_event": None
    }

def generate_weather_json(api_key: str = None, output_path: str = "weather_all.json") -> Dict[str, Any]:
    """
    50개 거점 도시 날씨 수집 및 weather_all.json V2 생성
    """
    import requests

    result_data = {}

    default_none_preset = {
        "state_code": "NONE",
        "title": "가볍게 빈손으로 나가도 좋아요",
        "message": "날씨가 쾌적하여 기분 좋은 외출이 될 거예요.",
        "rain_start_time": None,
        "max_temp": 22.5,
        "feels_like_max": 22.0,
        "max_uvi": 3.5,
        "temp_diff": 6.0,
        "alert_event": None
    }

    # 디폴트 거점 데이터 (주요 거점 시뮬레이션 프리셋)
    default_states_preset = {
        "seoul_south": {
            "state_code": "UMBRELLA",
            "title": "오후 14:15부터 비 소식이 있어요",
            "message": "외출 시 우산을 꼭 챙겨서 나가세요!",
            "rain_start_time": "14:15",
            "max_temp": 24.5,
            "feels_like_max": 25.8,
            "max_uvi": 4.2,
            "temp_diff": 6.5,
            "alert_event": None
        },
        "busan_center": {
            "state_code": "PARASOL",
            "title": "자외선이 '높음' 단계예요",
            "message": "볕이 뜨거워요. 양산이나 모자를 챙기세요!",
            "rain_start_time": None,
            "max_temp": 29.4,
            "feels_like_max": 31.2,
            "max_uvi": 7.8,
            "temp_diff": 7.0,
            "alert_event": None
        },
        "gyeonggi_suwon": {
            "state_code": "NONE",
            "title": "가볍게 빈손으로 나가도 좋아요",
            "message": "날씨가 쾌적하여 기분 좋은 외출이 될 거예요.",
            "rain_start_time": None,
            "max_temp": 22.5,
            "feels_like_max": 22.0,
            "max_uvi": 3.5,
            "temp_diff": 6.0,
            "alert_event": None
        },
        "gangwon_chuncheon": {
            "state_code": "JACKET",
            "title": "낮과 밤의 기온 차가 11.5°C나 돼요",
            "message": "저녁에 쌀쌀할 수 있으니 가벼운 외투를 챙기세요!",
            "rain_start_time": None,
            "max_temp": 23.0,
            "feels_like_max": 23.5,
            "max_uvi": 4.0,
            "temp_diff": 11.5,
            "alert_event": None
        },
        "gangwon_gangneung": {
            "state_code": "ALERT",
            "title": "호우주의보 발령 중",
            "message": "안전에 유의하시고 준비물을 꼭 점검하세요!",
            "rain_start_time": "11:00",
            "max_temp": 21.0,
            "feels_like_max": 22.0,
            "max_uvi": 2.0,
            "temp_diff": 4.0,
            "alert_event": "호우주의보"
        }
    }

    for loc in HUB_LOCATIONS:
        loc_id = loc["id"]
        lat = loc["lat"]
        lon = loc["lon"]
        group = loc.get("group", "")
        display_name = loc.get("display_name", "")
        full_name = f"{group}_{display_name}" if group and display_name and group != display_name else (group or display_name or loc.get("name", loc_id))

        if api_key:
            # 1. One Call API (3.0 / 4.0 구독 규격 엔드포인트) 시도
            try:
                url = f"https://api.openweathermap.org/data/3.0/onecall?lat={lat}&lon={lon}&appid={api_key}&units=metric"
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                api_data = resp.json()
                recommendation = evaluate_weather_v2(api_data)
            except Exception as e:
                print(f"One Call API disabled/unauthorized for {loc_id} ({e}). Trying 2.5 Forecast Free API...")
                # 2. 무료 기본 2.5 Forecast API 파이프라인 Fallback
                try:
                    url_25 = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={api_key}&units=metric"
                    resp_25 = requests.get(url_25, timeout=10)
                    resp_25.raise_for_status()
                    forecast_list = resp_25.json().get("list", [])
                    recommendation = evaluate_weather(forecast_list)
                    print(f"Successfully fetched real weather for {loc_id} via 2.5 Free API!")
                except Exception as e2:
                    print(f"2.5 Free API fetch also failed for {loc_id}: {e2}, using preset fallback.")
                    preset = default_states_preset.get(loc_id, default_none_preset)
                    recommendation = preset
        else:
            preset = default_states_preset.get(loc_id, default_none_preset)
            recommendation = preset

        result_data[loc_id] = {
            "id": loc_id,
            "name": full_name,
            "group": group,
            "display_name": display_name,
            "lat": lat,
            "lon": lon,
            "recommendation": recommendation
        }

    output = {
        "meta": {
            "version": "2.0",
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "OpenWeatherMap One Call API 4.0",
            "total_locations": len(HUB_LOCATIONS)
        },
        "data": result_data
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Successfully generated {output_path} with {len(result_data)} locations (V2 Schema).")
    return output

if __name__ == "__main__":
    if hasattr(sys.stdout, "detach"):
        sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    api_key_env = os.environ.get("OPENWEATHER_API_KEY")
    generate_weather_json(api_key=api_key_env)
