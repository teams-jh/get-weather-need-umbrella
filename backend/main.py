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

def format_rain_title(rain_start_str: Optional[str]) -> str:
    """
    "14:15" -> "오후 2:15부터 비 소식이 있어요"
    "09:30" -> "오전 9:30부터 비 소식이 있어요"
    """
    if not rain_start_str or ":" not in rain_start_str:
        return "비 소식이 있어요"
    try:
        parts = rain_start_str.split(":")
        hour = int(parts[0])
        minute = parts[1]
        ampm = "오후" if hour >= 12 else "오전"
        hour_12 = hour if hour <= 12 else hour - 12
        if hour_12 == 0:
            hour_12 = 12
        return f"{ampm} {hour_12}:{minute}부터 비 소식이 있어요"
    except Exception:
        return "비 소식이 있어요"

def evaluate_weather_v2(api_data: Dict[str, Any], now_ts: Optional[float] = None) -> Dict[str, Any]:
    """
    prd2.md 알고리즘 명세에 따른 날씨 판별 함수 (V2):
    1. alerts (기상 특보) -> ALERT
    2. minutely / hourly 강수 감지 -> UMBRELLA (+ rain_start_time)
    3. max_uvi >= 6.0 또는 max_temp >= 28.0 -> PARASOL
    4. temp_diff (일교차) >= 10.0도 -> JACKET
    5. 기타 -> NONE
    """
    if now_ts is None:
        now_ts = datetime.now(timezone.utc).timestamp()

    alerts = api_data.get("alerts", [])
    
    # OpenWeather 4.0 /current 엔드포인트 규격 ("data" 배열 구조) 호환 처리
    if "data" in api_data and isinstance(api_data["data"], list) and len(api_data["data"]) > 0:
        current = api_data["data"][0]
    else:
        current = api_data.get("current", {})

    daily = api_data.get("daily", [{}])[0] if api_data.get("daily") else {}
    minutely = api_data.get("minutely", [])
    hourly = api_data.get("hourly", [])

    # KST 기준 오늘 23:59:59 타임스탬프 계산 (현재 시각 이후~오늘 남아있는 시간 대상)
    dt_kst_now = datetime.fromtimestamp(now_ts, tz=KST)
    end_of_today_ts = datetime(dt_kst_now.year, dt_kst_now.month, dt_kst_now.day, 23, 59, 59, tzinfo=KST).timestamp()

    # 현재 시각(-300초 오차)부터 KST 오늘 23:59:59까지의 hourly 예보 필터링
    remaining_hourly = [
        item for item in hourly
        if now_ts - 300 <= item.get("dt", 0) <= end_of_today_ts
    ]

    if remaining_hourly:
        max_temp = max(item.get("temp", current.get("temp", 25.0)) for item in remaining_hourly)
        feels_like_max = max(item.get("feels_like", current.get("feels_like", max_temp)) for item in remaining_hourly)
        max_uvi = max(item.get("uvi", 0.0) for item in remaining_hourly)
    else:
        max_temp = current.get("temp", daily.get("temp", {}).get("max", 25.0))
        feels_like_max = current.get("feels_like", daily.get("feels_like", {}).get("day", max_temp))
        max_uvi = current.get("uvi", daily.get("uvi", 3.0))

    daily_max = daily.get("temp", {}).get("max", max_temp)
    daily_min = daily.get("temp", {}).get("min", daily_max - 5.0)
    temp_diff = max(0.0, daily_max - daily_min)

    current_temp = current.get("temp", max_temp)
    current_feels_like = current.get("feels_like", feels_like_max)

    # 1. ALERT (기상 특보 최우선)
    if alerts:
        event_name = alerts[0].get("event", "기상 특보")
        return {
            "state_code": "ALERT",
            "title": f"{event_name} 발령 중",
            "message": "안전에 유의하시고 준비물을 꼭 점검하세요!",
            "rain_start_time": None,
            "current_temp": round(current_temp, 1),
            "current_feels_like": round(current_feels_like, 1),
            "max_temp": round(max_temp, 1),
            "feels_like_max": round(feels_like_max, 1),
            "max_uvi": round(max_uvi, 1),
            "temp_diff": round(temp_diff, 1),
            "alert_event": event_name
        }

    # 2. UMBRELLA (현재 시각 이후의 강수 감지 및 비 시작 시간 추적)
    rain_start_str: Optional[str] = None

    # 2-1. 15분 단위(minutely) 강수 체크 (현재 시각 이후만)
    for item in minutely:
        dt = item.get("dt", 0)
        if dt >= now_ts - 300:  # 5분 전 오차 범위 허용
            precip = item.get("precipitation", 0)
            if precip > 0:
                dt_kst = datetime.fromtimestamp(dt, tz=KST)
                rain_start_str = dt_kst.strftime("%H:%M")
                break

    # 2-2. 15분 단위 데이터가 없고 hourly에서 강수인 경우 (현재 시각 이후만)
    if not rain_start_str and hourly:
        for item in hourly:
            dt = item.get("dt", 0)
            if dt >= now_ts - 1800:  # 30분 전 오차 범위 허용
                weather_entries = item.get("weather", [])
                for w in weather_entries:
                    if w.get("id", 800) < 700 or item.get("pop", 0) >= 0.5:
                        dt_kst = datetime.fromtimestamp(dt, tz=KST)
                        rain_start_str = dt_kst.strftime("%H:%M")
                        break
                if rain_start_str:
                    break

    if rain_start_str:
        return {
            "state_code": "UMBRELLA",
            "title": format_rain_title(rain_start_str),
            "message": "외출 시 우산을 꼭 챙겨서 나가세요!",
            "rain_start_time": rain_start_str,
            "current_temp": round(current_temp, 1),
            "current_feels_like": round(current_feels_like, 1),
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
            "current_temp": round(current_temp, 1),
            "current_feels_like": round(current_feels_like, 1),
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
            "current_temp": round(current_temp, 1),
            "current_feels_like": round(current_feels_like, 1),
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
        "current_temp": round(current_temp, 1),
        "current_feels_like": round(current_feels_like, 1),
        "max_temp": round(max_temp, 1),
        "feels_like_max": round(feels_like_max, 1),
        "max_uvi": round(max_uvi, 1),
        "temp_diff": round(temp_diff, 1),
        "alert_event": None
    }

def evaluate_weather(forecast_list: List[Dict[str, Any]], now_ts: Optional[float] = None) -> Dict[str, Any]:
    """
    2.5 무료 API 예보 데이터 기반 5대 준비물 상태 판별 함수
    """
    if now_ts is None:
        now_ts = datetime.now(timezone.utc).timestamp()

    # KST 기준 오늘 23:59:59 타임스탬프 계산 (현재 시각 이후~오늘 남아있는 시간 대상)
    dt_kst_now = datetime.fromtimestamp(now_ts, tz=KST)
    end_of_today_ts = datetime(dt_kst_now.year, dt_kst_now.month, dt_kst_now.day, 23, 59, 59, tzinfo=KST).timestamp()

    # 현재 시각(-1800초 오차 허용)부터 오늘 23:59:59까지 남아있는 예보만 선택
    today_remaining_forecasts = [
        f for f in forecast_list
        if now_ts - 1800 <= f.get("dt", 0) <= end_of_today_ts
    ]

    # 만약 오늘 남은 예보가 없다면(밤 11시 이후 등), 향후 가장 가까운 예보 사용
    if not today_remaining_forecasts:
        future_forecasts = [f for f in forecast_list if f.get("dt", 0) >= now_ts - 1800]
        target_forecasts = future_forecasts[:2] if future_forecasts else forecast_list[:1]
    else:
        target_forecasts = today_remaining_forecasts

    has_precipitation = False
    rain_start_str: Optional[str] = None
    max_temp = -999.0
    min_temp = 999.0

    for item in target_forecasts:
        temp_item = item.get("main", {}).get("temp", 0.0)
        temp_max_item = item.get("main", {}).get("temp_max", temp_item)
        temp_min_item = item.get("main", {}).get("temp_min", temp_item)
        if temp_max_item > max_temp:
            max_temp = temp_max_item
        if temp_min_item < min_temp:
            min_temp = temp_min_item

        # 비/눈 감지 및 시작시간 파싱
        weather_entries = item.get("weather", [])
        for w in weather_entries:
            if w.get("id", 800) < 700 or item.get("pop", 0) >= 0.5:
                has_precipitation = True
                if not rain_start_str:
                    dt_kst = datetime.fromtimestamp(item.get("dt", 0), tz=KST)
                    rain_start_str = dt_kst.strftime("%H:%M")

    if max_temp == -999.0:
        max_temp = 20.0
    if min_temp == 999.0:
        min_temp = max_temp - 5.0

    temp_diff = max(0.0, max_temp - min_temp)

    first_item = target_forecasts[0] if target_forecasts else {}
    current_temp = first_item.get("main", {}).get("temp", max_temp)
    current_feels_like = first_item.get("main", {}).get("feels_like", current_temp)

    # 1. UMBRELLA (비/눈 감지)
    if has_precipitation:
        return {
            "state_code": "UMBRELLA",
            "title": format_rain_title(rain_start_str),
            "message": "외출 시 우산을 꼭 챙겨서 나가세요!",
            "current_temp": round(current_temp, 1),
            "current_feels_like": round(current_feels_like, 1),
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
            "current_temp": round(current_temp, 1),
            "current_feels_like": round(current_feels_like, 1),
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
            "current_temp": round(current_temp, 1),
            "current_feels_like": round(current_feels_like, 1),
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
        "current_temp": round(current_temp, 1),
        "current_feels_like": round(current_feels_like, 1),
        "max_temp": round(max_temp, 1),
        "feels_like_max": round(max_temp, 1),
        "max_uvi": 3.5,
        "temp_diff": round(temp_diff, 1),
        "rain_start_time": None,
        "alert_event": None
    }

def generate_weather_json(api_key: str = None, output_path: Optional[str] = None) -> Dict[str, Any]:
    """
    50개 거점 도시 날씨 수집 및 weather_all.json V2 생성
    """
    import requests

    if not output_path:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_path = os.path.join(base_dir, "weather_all.json")

    result_data = {}

    default_none_preset = {
        "state_code": "NONE",
        "title": "가볍게 빈손으로 나가도 좋아요",
        "message": "날씨가 쾌적하여 기분 좋은 외출이 될 거예요.",
        "rain_start_time": None,
        "current_temp": 22.0,
        "current_feels_like": 21.5,
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
            "current_temp": 23.0,
            "current_feels_like": 24.0,
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

    onecall_count = 0
    forecast25_count = 0
    dummy_count = 0

    if not api_key:
        print("[WARNING] OPENWEATHER_API_KEY가 감지되지 않았습니다. preset 더미 데이터로 생성합니다.")
    else:
        print("[INFO] OPENWEATHER_API_KEY가 감지되었습니다. 실시간 날씨 데이터 조회를 시작합니다...")

    for loc in HUB_LOCATIONS:
        loc_id = loc["id"]
        lat = loc["lat"]
        lon = loc["lon"]
        group = loc.get("group", "")
        display_name = loc.get("display_name", "")
        full_name = f"{group}_{display_name}" if group and display_name and group != display_name else (group or display_name or loc.get("name", loc_id))

        if api_key:
            # 1. One Call API 4.0 엔드포인트 시도 (공식 규격: /data/4.0/onecall/current 및 /data/3.0/onecall)
            api_data = None
            onecall_err = None
            for url_template in [
                f"https://api.openweathermap.org/data/4.0/onecall/current?lat={lat}&lon={lon}&appid={api_key}&units=metric",
                f"https://api.openweathermap.org/data/3.0/onecall?lat={lat}&lon={lon}&appid={api_key}&units=metric"
            ]:
                try:
                    resp = requests.get(url_template, timeout=10)
                    resp.raise_for_status()
                    api_data = resp.json()
                    break
                except Exception as ex:
                    onecall_err = ex

            if api_data:
                recommendation = evaluate_weather_v2(api_data)
                onecall_count += 1
            else:
                if onecall_count == 0 and forecast25_count == 0 and dummy_count == 0:
                    print(f"[NOTE] One Call API 4.0 호출 실패 ({loc_id}): {onecall_err}. 2.5 Forecast API로 시도합니다...")
                # 2. 무료 기본 2.5 Forecast API 파이프라인 Fallback
                try:
                    url_25 = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={api_key}&units=metric"
                    resp_25 = requests.get(url_25, timeout=10)
                    resp_25.raise_for_status()
                    forecast_list = resp_25.json().get("list", [])
                    recommendation = evaluate_weather(forecast_list)
                    forecast25_count += 1
                except Exception as e2:
                    print(f"[FALLBACK] API fetch failed for {loc_id}: {e2}. Using preset dummy data.")
                    preset = default_states_preset.get(loc_id, default_none_preset)
                    recommendation = preset
                    dummy_count += 1
        else:
            preset = default_states_preset.get(loc_id, default_none_preset)
            recommendation = preset
            dummy_count += 1

        result_data[loc_id] = {
            "id": loc_id,
            "name": full_name,
            "group": group,
            "display_name": display_name,
            "lat": lat,
            "lon": lon,
            "recommendation": recommendation
        }

    # 데이터 출처 메타정보 문자열 세팅
    if onecall_count > 0:
        data_source_str = f"OpenWeatherMap One Call API 4.0 (Real Data - {onecall_count}/{len(HUB_LOCATIONS)})"
    elif forecast25_count > 0:
        data_source_str = f"OpenWeatherMap 2.5 Forecast Free API (Real Data - {forecast25_count}/{len(HUB_LOCATIONS)})"
    else:
        data_source_str = "Preset Dummy Data (No API Key)"

    if dummy_count > 0 and (onecall_count > 0 or forecast25_count > 0):
        data_source_str += f" (Partial Dummy: {dummy_count})"

    output = {
        "meta": {
            "version": "2.0",
            "updated_at": datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00"),
            "source": data_source_str,
            "total_locations": len(HUB_LOCATIONS)
        },
        "data": result_data
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("==================================================")
    print(f"[SUMMARY] Weather Data Generation Completed!")
    print(f" - Output File   : {output_path}")
    print(f" - Data Source   : {data_source_str}")
    print(f" - Total Cities  : {len(result_data)}")
    print(f" - Real 4.0 API  : {onecall_count}")
    print(f" - Real 2.5 API  : {forecast25_count}")
    print(f" - Dummy Presets : {dummy_count}")
    print("==================================================")
    return output

def load_env_file():
    """ .env 파일에서 OPENWEATHER_API_KEY 자동 로드 """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_paths = [
        os.path.join(base_dir, ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    ]
    for env_path in env_paths:
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")
            break

if __name__ == "__main__":
    if hasattr(sys.stdout, "detach"):
        sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    load_env_file()
    api_key_env = os.environ.get("OPENWEATHER_API_KEY")
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_json_path = os.path.join(project_root, "weather_all.json")
    generate_weather_json(api_key=api_key_env, output_path=target_json_path)
