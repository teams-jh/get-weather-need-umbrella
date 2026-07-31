"""
provider 공통 계약.

날씨 출처(OpenWeather / 기상청)가 서로 다른 응답 형태를 가지므로,
각 provider 는 자신의 응답을 WeatherBundle 로 정규화해서 돌려준다.
판정(evaluate)은 오직 이 형태만 알면 되고 출처를 구분하지 않는다.

값이 없을 때는 임의의 기본값을 채우지 말고 None 으로 둔다.
누락 시의 대체값 규칙은 판정 쪽에 한 곳으로 모아 두었기 때문이다.
provider 가 미리 채우면 그 규칙이 출처마다 갈라진다.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

KST = timezone(timedelta(hours=9))

# 주말 알림은 금요일 저녁에 토(D+1)·일(D+2)을 본다. 오늘 포함 3일이면 충분하다.
# weather_all.json 은 하루에 여러 번 커밋되므로 쓰이지 않는 날짜는 담지 않는다.
FORECAST_DAYS = 3


@dataclass
class HourlyPoint:
    """시간 단위 예보 한 점."""

    dt: int
    temp: Optional[float] = None
    feels_like: Optional[float] = None
    uvi: Optional[float] = None
    pop: float = 0.0
    # 강수 여부. OpenWeather 는 weather[].id < 700, 기상청은 PTY != 0 로 판정한다.
    # 출처별 코드 체계를 판정 쪽으로 흘리지 않으려고 provider 에서 미리 접어 둔다.
    is_precip: bool = False


@dataclass
class MinutelyPoint:
    """분 단위 강수 한 점. 기상청은 1시간 단위라 해상도가 더 거칠다."""

    dt: int
    precipitation: float = 0.0


@dataclass
class DailyPoint:
    """
    일자별 강수 요약.

    recommendation 은 오늘 자정까지만 다루기 때문에, 금요일 저녁에 주말 비 예보를
    보려면 미래 날짜가 따로 필요하다. 알림이 보는 건 날짜와 강수 여부뿐이고
    pop 은 그 판단 근거로 남긴다.
    """

    date: str  # KST 기준 YYYY-MM-DD
    pop: float = 0.0
    has_rain: bool = False
    # 해당 날짜의 시간별 예보 중 첫 강수 시각(KST HH:MM). 일 단위 예보만
    # 제공돼 시각을 특정할 수 없는 경우에는 None으로 둔다.
    rain_start_time: Optional[str] = None


def daily_forecast_from_hourly(hourly: List["HourlyPoint"]) -> List[DailyPoint]:
    """
    시간 단위 예보를 KST 날짜별로 접는다.

    일 단위 예보를 따로 주는 출처(OpenWeather One Call)는 그쪽을 쓰는 편이 더 멀리
    보지만, 시간 예보만 있는 출처(기상청 단기예보, 2.5 Forecast)는 이 함수로 접는다.
    하루 중 한 번이라도 비가 오면 그 날은 비로 본다.
    """
    buckets: Dict[str, DailyPoint] = {}
    for point in hourly:
        if not point.dt:
            continue
        date_key = datetime.fromtimestamp(point.dt, tz=KST).strftime("%Y-%m-%d")
        bucket = buckets.setdefault(date_key, DailyPoint(date=date_key))
        bucket.pop = max(bucket.pop, point.pop)
        if point.is_precip:
            bucket.has_rain = True
            if bucket.rain_start_time is None:
                bucket.rain_start_time = datetime.fromtimestamp(point.dt, tz=KST).strftime("%H:%M")

    return [buckets[key] for key in sorted(buckets)][:FORECAST_DAYS]


@dataclass
class WeatherBundle:
    """한 거점의 정규화된 날씨 묶음."""

    source: str
    alerts: List[str] = field(default_factory=list)

    current_temp: Optional[float] = None
    current_feels_like: Optional[float] = None
    current_uvi: Optional[float] = None

    daily_max: Optional[float] = None
    daily_min: Optional[float] = None
    daily_feels_like_day: Optional[float] = None
    daily_uvi: Optional[float] = None

    hourly: List[HourlyPoint] = field(default_factory=list)
    minutely: List[MinutelyPoint] = field(default_factory=list)
    # 오늘 포함 며칠치 강수 요약. 주말 알림이 이 값을 본다.
    daily_forecast: List[DailyPoint] = field(default_factory=list)


class ProviderError(Exception):
    """provider 가 해당 거점의 날씨를 만들어내지 못했을 때."""
