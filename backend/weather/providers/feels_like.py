"""
체감온도 계산.

기상청 생활기상지수 API(LivingWthrIdxServiceV5)에는 체감온도 오퍼레이션이 없다
(자외선지수·대기정체지수 둘뿐). 그래서 단기예보의 기온·습도·풍속으로 직접 계산한다.

기상청 공식은 계절에 따라 둘로 나뉘고, 각각 적용 범위가 정해져 있다.
범위 밖에서는 값을 지어내지 않고 기온을 그대로 돌려준다.
"""
import math
from typing import Optional

# 겨울철 체감온도(풍속냉각) 적용 조건
WIND_CHILL_MAX_TEMP = 10.0      # 이 기온 이하에서만
WIND_CHILL_MIN_WIND_KMH = 4.8   # 이 풍속 이상에서만 (약 1.34 m/s)

# 여름철 체감온도 적용 하한. 이보다 낮으면 보정이 사실상 무의미하다.
HEAT_MIN_TEMP = 20.0


def wet_bulb_temperature(temp_c: float, humidity_pct: float) -> float:
    """습구온도 (Stull 2011 근사)."""
    rh = humidity_pct
    return (
        temp_c * math.atan(0.151977 * (rh + 8.313659) ** 0.5)
        + math.atan(temp_c + rh)
        - math.atan(rh - 1.67633)
        + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh)
        - 4.686035
    )


def summer_feels_like(temp_c: float, humidity_pct: float) -> float:
    """기상청 여름철 체감온도 (2020 개정). 기온과 습도 기반."""
    tw = wet_bulb_temperature(temp_c, humidity_pct)
    return (
        -0.2442
        + 0.55399 * tw
        + 0.45535 * temp_c
        - 0.0022 * tw ** 2
        + 0.00278 * tw * temp_c
        + 3.0
    )


def winter_feels_like(temp_c: float, wind_ms: float) -> float:
    """기상청 겨울철 체감온도 (풍속냉각). 풍속은 m/s 로 받아 km/h 로 환산한다."""
    wind_kmh = wind_ms * 3.6
    return (
        13.12
        + 0.6215 * temp_c
        - 11.37 * wind_kmh ** 0.16
        + 0.3965 * wind_kmh ** 0.16 * temp_c
    )


def feels_like(
    temp_c: Optional[float],
    humidity_pct: Optional[float] = None,
    wind_ms: Optional[float] = None,
) -> Optional[float]:
    """
    계절 조건에 맞는 공식을 골라 체감온도를 계산한다.

    어느 공식의 적용 범위에도 들지 않으면(봄·가을 등) 기온을 그대로 돌려준다.
    두 공식 모두 그 구간에서는 기온과 거의 같은 값을 내므로 억지로 끼워 맞출 이유가 없다.
    """
    if temp_c is None:
        return None

    if temp_c <= WIND_CHILL_MAX_TEMP and wind_ms is not None:
        if wind_ms * 3.6 >= WIND_CHILL_MIN_WIND_KMH:
            return winter_feels_like(temp_c, wind_ms)
        return temp_c

    if temp_c >= HEAT_MIN_TEMP and humidity_pct is not None:
        return summer_feels_like(temp_c, humidity_pct)

    return temp_c
