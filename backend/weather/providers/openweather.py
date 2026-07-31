"""
OpenWeatherMap provider.

One Call 3.0 → 2.5 Forecast → One Call 4.0 /current 순으로 시도하고, 먼저 성공한
응답을 WeatherBundle 로 정규화한다.

3.0 이 1순위인 이유는 한 번의 요청으로 current·minutely·hourly·daily·alerts 를
모두 주기 때문이다. 판정에 필요한 값이 전부 여기서 나온다.

4.0 은 모듈형으로 재설계되어 /onecall/current 가 현재 스냅샷만 돌려준다.
강수 시작 시각(timeline/15min), 일교차(timeline/1day), 특보명(alert/{id}) 이
모두 빠지고, alerts 는 이름이 아니라 ID 배열이라 한 번 더 불러야 한다. 이 경로로만
채워진 묶음은 UMBRELLA·ALERT·JACKET 어디에도 도달하지 못해 알림이 하나도 나가지
않는다. 그래서 무료인 2.5 보다 뒤에 두고, 마지막 표시용 수단으로만 남긴다.
4.0 의 예보를 쓰려면 timeline 엔드포인트들을 따로 불러 합쳐야 한다.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from weather.providers.base import (
    FORECAST_DAYS,
    KST,
    DailyPoint,
    HourlyPoint,
    MinutelyPoint,
    ProviderError,
    WeatherBundle,
    daily_forecast_from_hourly,
)

NAME = "openweather"
TIMEOUT = 10

ONECALL_30_URL = (
    "https://api.openweathermap.org/data/3.0/onecall?lat={lat}&lon={lon}&appid={key}&units=metric"
)
FORECAST_25_URL = (
    "https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={key}&units=metric"
)
ONECALL_40_CURRENT_URL = (
    "https://api.openweathermap.org/data/4.0/onecall/current?lat={lat}&lon={lon}&appid={key}&units=metric"
)

SOURCE_ONECALL30 = "OpenWeatherMap One Call API 3.0"
SOURCE_FORECAST25 = "OpenWeatherMap 2.5 Forecast Free API"
SOURCE_ONECALL40_CURRENT = "OpenWeatherMap One Call API 4.0 /current (예보 없음)"
# provider 의 대표 이름. 실제로 어느 경로가 쓰였는지는 bundle.source 에 담긴다.
SOURCE = SOURCE_ONECALL30


def _is_precip(weather: List[Dict[str, Any]], pop: float) -> bool:
    """
    OpenWeather 의 강수 판정. weather[].id 700 미만이 비/눈/뇌우 계열이다.
    weather 가 비어 있으면 pop 도 보지 않는데, 이는 기존 구현의 동작을 그대로 옮긴 것이다.
    """
    if not weather:
        return False
    return pop >= 0.5 or any(w.get("id", 800) < 700 for w in weather)


def _hourly_point(item: Dict[str, Any]) -> HourlyPoint:
    pop = item.get("pop", 0) or 0
    return HourlyPoint(
        dt=item.get("dt", 0),
        temp=item.get("temp"),
        feels_like=item.get("feels_like"),
        uvi=item.get("uvi"),
        pop=pop,
        is_precip=_is_precip(item.get("weather") or [], pop),
    )


def _daily_forecast_from_onecall(
    daily_list: List[Dict[str, Any]], hourly: List[HourlyPoint]
) -> List[DailyPoint]:
    """
    One Call 의 daily 배열을 일자별 강수 요약으로 접는다.
    hourly(48시간)로 접는 것보다 멀리 보므로 이 출처에서는 이쪽을 쓴다.
    """
    hourly_forecast = {day.date: day for day in daily_forecast_from_hourly(hourly)}
    forecast: List[DailyPoint] = []
    for item in daily_list:
        dt = item.get("dt")
        if not dt:
            continue
        pop = item.get("pop", 0) or 0
        date = datetime.fromtimestamp(dt, tz=KST).strftime("%Y-%m-%d")
        hourly_day = hourly_forecast.get(date)
        forecast.append(
            DailyPoint(
                date=date,
                pop=pop,
                has_rain=_is_precip(item.get("weather") or [], pop),
                rain_start_time=hourly_day.rain_start_time if hourly_day else None,
            )
        )
    return forecast[:FORECAST_DAYS]


def bundle_from_onecall(raw: Dict[str, Any], source: str = SOURCE_ONECALL30) -> WeatherBundle:
    """One Call 3.0/4.0 응답을 정규화한다."""
    # 4.0 /current 는 current 대신 data 배열로 준다.
    data_list = raw.get("data")
    if isinstance(data_list, list) and data_list:
        current = data_list[0]
    else:
        current = raw.get("current") or {}

    daily_list = raw.get("daily") or []
    daily = daily_list[0] if daily_list else {}
    daily_temp = daily.get("temp") or {}
    daily_feels = daily.get("feels_like") or {}

    hourly = [_hourly_point(h) for h in (raw.get("hourly") or [])]

    return WeatherBundle(
        source=source,
        alerts=[a.get("event", "기상 특보") for a in (raw.get("alerts") or [])],
        current_temp=current.get("temp"),
        current_feels_like=current.get("feels_like"),
        current_uvi=current.get("uvi"),
        daily_max=daily_temp.get("max"),
        daily_min=daily_temp.get("min"),
        daily_feels_like_day=daily_feels.get("day"),
        daily_uvi=daily.get("uvi"),
        hourly=hourly,
        minutely=[
            MinutelyPoint(dt=m.get("dt", 0), precipitation=m.get("precipitation", 0) or 0)
            for m in (raw.get("minutely") or [])
        ],
        # 4.0 /current 에는 daily 가 없어 빈 목록이 된다. 주말 알림은 그때 발송을 건너뛴다.
        daily_forecast=_daily_forecast_from_onecall(daily_list, hourly),
    )


def bundle_from_forecast25(forecast_list: List[Dict[str, Any]]) -> WeatherBundle:
    """
    2.5 Forecast 응답(3시간 간격 list)을 정규화한다.

    2.5 는 자외선을 주지 않으므로 uvi 는 비워 둔다. 이전 구현은 판정이 끝난 뒤
    상태별로 3.0/7.5/4.0 같은 값을 지어내 채웠는데, 실제로 관측된 값이 아니라
    표시용 상수였다. 없는 값을 지어내는 대신 비워 두고 판정 쪽 기본값(0.0)을 따른다.
    """
    hourly: List[HourlyPoint] = []
    highs: List[float] = []
    lows: List[float] = []

    for item in forecast_list:
        main = item.get("main") or {}
        temp = main.get("temp")
        pop = item.get("pop", 0) or 0
        hourly.append(
            HourlyPoint(
                dt=item.get("dt", 0),
                temp=temp,
                feels_like=main.get("feels_like"),
                uvi=None,
                pop=pop,
                is_precip=_is_precip(item.get("weather") or [], pop),
            )
        )
        if main.get("temp_max", temp) is not None:
            highs.append(main.get("temp_max", temp))
        if main.get("temp_min", temp) is not None:
            lows.append(main.get("temp_min", temp))

    first_main = (forecast_list[0].get("main") or {}) if forecast_list else {}

    return WeatherBundle(
        source=SOURCE_FORECAST25,
        alerts=[],
        current_temp=first_main.get("temp"),
        current_feels_like=first_main.get("feels_like"),
        current_uvi=None,
        daily_max=max(highs) if highs else None,
        daily_min=min(lows) if lows else None,
        daily_feels_like_day=None,
        daily_uvi=None,
        hourly=hourly,
        minutely=[],
        # 2.5 는 일 단위 예보를 주지 않으므로 3시간 예보를 날짜별로 접는다.
        daily_forecast=daily_forecast_from_hourly(hourly),
    )


def fetch(loc: Dict[str, Any], api_key: Optional[str] = None) -> WeatherBundle:
    """거점 하나의 날씨를 가져와 정규화한다. 모든 경로가 실패하면 ProviderError."""
    if not api_key:
        raise ProviderError("OPENWEATHER_API_KEY 가 없습니다")

    lat, lon = loc["lat"], loc["lon"]
    errors: Dict[str, Exception] = {}

    try:
        resp = requests.get(ONECALL_30_URL.format(lat=lat, lon=lon, key=api_key), timeout=TIMEOUT)
        resp.raise_for_status()
        return bundle_from_onecall(resp.json(), source=SOURCE_ONECALL30)
    except Exception as error:
        errors["3.0"] = error

    try:
        resp = requests.get(FORECAST_25_URL.format(lat=lat, lon=lon, key=api_key), timeout=TIMEOUT)
        resp.raise_for_status()
        return bundle_from_forecast25(resp.json().get("list") or [])
    except Exception as error:
        errors["2.5"] = error

    # 마지막 수단. 여기까지 오면 예보가 없어 알림은 나가지 않는다는 뜻이라 눈에 띄게 남긴다.
    try:
        resp = requests.get(
            ONECALL_40_CURRENT_URL.format(lat=lat, lon=lon, key=api_key), timeout=TIMEOUT
        )
        resp.raise_for_status()
        print(
            f"[WARNING] {loc.get('id', '?')}: One Call 4.0 /current 로만 조회됐습니다. "
            "강수·특보·예보가 없어 이 거점은 알림이 발송되지 않습니다."
        )
        return bundle_from_onecall(resp.json(), source=SOURCE_ONECALL40_CURRENT)
    except Exception as error:
        errors["4.0"] = error

    detail = " / ".join(f"{name}: {err}" for name, err in errors.items())
    raise ProviderError(f"OpenWeather 조회 실패 ({detail})") from errors["4.0"]
