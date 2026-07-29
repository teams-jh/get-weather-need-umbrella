"""
prd2.md 판별 알고리즘. 출처와 무관한 단 하나의 판정 경로.

이전에는 OpenWeather 4.0 응답용(evaluate_weather_v2)과 2.5 응답용(evaluate_weather)이
따로 있었다. 출처가 늘 때마다 판정까지 복제되면 이중화 비교에서 불일치가 나왔을 때
데이터 차이인지 로직 차이인지 구분할 수 없다. 그래서 정규화는 provider 가 맡고,
판정은 여기 한 곳만 둔다.

우선순위: ALERT > UMBRELLA > PARASOL > JACKET > NONE
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from weather.providers.base import WeatherBundle

KST = timezone(timedelta(hours=9))

UVI_PARASOL_THRESHOLD = 6.0
TEMP_PARASOL_THRESHOLD = 28.0
TEMP_DIFF_JACKET_THRESHOLD = 10.0

# 강수 판정 시 허용하는 과거 방향 오차. 분 단위는 5분, 시간 단위는 30분.
MINUTELY_GRACE_SEC = 300
HOURLY_GRACE_SEC = 1800


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


def _or(value: Optional[float], fallback: float) -> float:
    """값이 없으면 대체값. 0.0 을 falsy 로 잘못 삼키지 않도록 None 만 본다."""
    return fallback if value is None else value


def _end_of_today_ts(now_ts: float) -> float:
    now_kst = datetime.fromtimestamp(now_ts, tz=KST)
    return datetime(now_kst.year, now_kst.month, now_kst.day, 23, 59, 59, tzinfo=KST).timestamp()


def _find_rain_start(bundle: WeatherBundle, now_ts: float) -> Optional[str]:
    """
    현재 시각 이후의 첫 강수 시각을 "HH:MM" 으로 찾는다.
    분 단위 자료를 먼저 보고, 없으면 시간 단위로 넘어간다.
    """
    for point in bundle.minutely:
        if point.dt >= now_ts - MINUTELY_GRACE_SEC and point.precipitation > 0:
            return datetime.fromtimestamp(point.dt, tz=KST).strftime("%H:%M")

    for point in bundle.hourly:
        if point.dt >= now_ts - HOURLY_GRACE_SEC and point.is_precip:
            return datetime.fromtimestamp(point.dt, tz=KST).strftime("%H:%M")

    return None


def evaluate(bundle: WeatherBundle, now_ts: Optional[float] = None) -> Dict[str, Any]:
    """정규화된 날씨 묶음에서 5대 준비물 상태를 판별한다."""
    if now_ts is None:
        now_ts = datetime.now(timezone.utc).timestamp()

    # 현재 시각부터 KST 오늘 자정까지 남은 예보만 대상으로 한다.
    end_of_today = _end_of_today_ts(now_ts)
    remaining = [
        h for h in bundle.hourly
        if now_ts - MINUTELY_GRACE_SEC <= h.dt <= end_of_today
    ]

    if remaining:
        # 개별 예보 항목에 값이 비면 현재값으로 메운다.
        temp_default = _or(bundle.current_temp, 25.0)
        max_temp = max(_or(h.temp, temp_default) for h in remaining)
        # feels_like 의 대체값은 방금 구한 max_temp 다. 순서에 의존하므로 바꾸지 말 것.
        feels_default = _or(bundle.current_feels_like, max_temp)
        feels_like_max = max(_or(h.feels_like, feels_default) for h in remaining)
        max_uvi = max(_or(h.uvi, 0.0) for h in remaining)
    else:
        # 오늘 남은 예보가 없으면(늦은 밤 등) 현재값과 일 통계로 대신한다.
        max_temp = _or(bundle.current_temp, _or(bundle.daily_max, 25.0))
        feels_like_max = _or(bundle.current_feels_like, _or(bundle.daily_feels_like_day, max_temp))
        max_uvi = _or(bundle.current_uvi, _or(bundle.daily_uvi, 3.0))

    daily_max = _or(bundle.daily_max, max_temp)
    daily_min = _or(bundle.daily_min, daily_max - 5.0)
    temp_diff = max(0.0, daily_max - daily_min)

    current_temp = _or(bundle.current_temp, max_temp)
    current_feels_like = _or(bundle.current_feels_like, feels_like_max)

    measurements = {
        "current_temp": round(current_temp, 1),
        "current_feels_like": round(current_feels_like, 1),
        "max_temp": round(max_temp, 1),
        "feels_like_max": round(feels_like_max, 1),
        "max_uvi": round(max_uvi, 1),
        "temp_diff": round(temp_diff, 1),
    }

    # 1. ALERT — 기상 특보가 있으면 다른 조건을 보지 않는다.
    if bundle.alerts:
        event_name = bundle.alerts[0]
        return {
            "state_code": "ALERT",
            "title": f"{event_name} 발령 중",
            "message": "안전에 유의하시고 준비물을 꼭 점검하세요!",
            "rain_start_time": None,
            **measurements,
            "alert_event": event_name,
        }

    # 2. UMBRELLA — 현재 시각 이후의 강수
    rain_start = _find_rain_start(bundle, now_ts)
    if rain_start:
        return {
            "state_code": "UMBRELLA",
            "title": format_rain_title(rain_start),
            "message": "외출 시 우산을 꼭 챙겨서 나가세요!",
            "rain_start_time": rain_start,
            **measurements,
            "alert_event": None,
        }

    # 3. PARASOL — 자외선이 높거나 기온이 높을 때
    if max_uvi >= UVI_PARASOL_THRESHOLD or max_temp >= TEMP_PARASOL_THRESHOLD:
        uv_level = "매우 높음" if max_uvi >= 8.0 else ("높음" if max_uvi >= UVI_PARASOL_THRESHOLD else "보통")
        title = (
            f"자외선이 '{uv_level}' 단계예요"
            if max_uvi >= UVI_PARASOL_THRESHOLD
            else "볕이 뜨거워요. 양산 챙길까요?"
        )
        return {
            "state_code": "PARASOL",
            "title": title,
            "message": "볕이 뜨거워요. 양산이나 모자를 챙기세요!",
            "rain_start_time": None,
            **measurements,
            "alert_event": None,
        }

    # 4. JACKET — 일교차가 클 때
    if temp_diff >= TEMP_DIFF_JACKET_THRESHOLD:
        return {
            "state_code": "JACKET",
            "title": f"낮과 밤의 기온 차가 {round(temp_diff)}°C나 돼요",
            "message": "저녁에 쌀쌀할 수 있으니 가벼운 외투를 챙기세요!",
            "rain_start_time": None,
            **measurements,
            "alert_event": None,
        }

    # 5. NONE
    return {
        "state_code": "NONE",
        "title": "가볍게 빈손으로 나가도 좋아요",
        "message": "날씨가 쾌적하여 기분 좋은 외출이 될 거예요.",
        "rain_start_time": None,
        **measurements,
        "alert_event": None,
    }
