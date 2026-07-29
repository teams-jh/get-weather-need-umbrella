"""
기상청 provider.

OpenWeather 가 한 번에 주던 것을 기상청은 네 서비스로 나눠 준다.

  getUltraSrtNcst  초단기실황   현재 기온·습도·풍속        (매시 정시, +40분)
  getUltraSrtFcst  초단기예보   향후 6시간 강수            (매시 30분, +45분)
  getVilageFcst    단기예보     시간별 기온·강수확률·일교차 (3시간 간격, +10분)
  getUVIdxV5       자외선지수   3시간 간격 예측값          (06시/18시)
  getWthrWrnList   기상특보     발표관서 단위              (수시)

특보는 관서(stn_id) 단위라 거점마다 부를 필요가 없다. main 쪽에서 관서별로 한 번씩
받아 fetch() 에 넘기면 50회가 9회로 준다.
"""
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from locations.kma_reference import HUB_LOCATIONS as KMA_HUBS
from weather.providers.base import (
    HourlyPoint,
    MinutelyPoint,
    ProviderError,
    WeatherBundle,
    daily_forecast_from_hourly,
)
from weather.providers.feels_like import feels_like
from weather.providers.grid import grid_of

NAME = "kma"
SOURCE = "기상청 단기예보 조회서비스"
BASE = "https://apis.data.go.kr/1360000"
TIMEOUT = 15
# 병렬 조회 시 포털이 429 로 끊는 일이 있어 재시도한다.
MAX_RETRIES = 3
RETRY_BACKOFF_SEC = 1.0

KST = timezone(timedelta(hours=9))

# 단기예보 발표 시각 (KST). 발표 후 10분쯤 지나야 조회된다.
VILAGE_BASE_HOURS = [2, 5, 8, 11, 14, 17, 20, 23]

# 강수형태(PTY): 0 없음 / 1 비 / 2 비눈 / 3 눈 / 4 소나기 / 5~7 빗방울·눈날림
PTY_NONE = "0"
# 강수확률(POP)이 이 값 이상이면 강수로 본다. OpenWeather 의 pop >= 0.5 와 맞춘 것이다.
POP_PRECIP_THRESHOLD = 50


def _get(path: str, params: Dict[str, Any], service_key: str) -> List[Dict[str, Any]]:
    """
    기상청 API 를 호출해 item 목록을 돌려준다. 정상 응답이 아니면 빈 목록.

    거점을 병렬로 조회하면 포털이 429 로 끊는 경우가 있어 지수 백오프로 재시도한다.
    한 거점이 4회를 부르므로, 재시도가 없으면 몇 곳이 통째로 더미로 떨어진다.
    """
    query = {"serviceKey": service_key, "dataType": "JSON", "pageNo": 1, "numOfRows": 1000}
    query.update(params)

    last_error: Optional[Exception] = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(f"{BASE}/{path}", params=query, timeout=TIMEOUT)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"{resp.status_code} {resp.reason}", response=resp)
            resp.raise_for_status()
            body = resp.json().get("response", {})
            break
        except Exception as error:
            last_error = error
            if attempt == MAX_RETRIES:
                raise ProviderError(f"{path} 호출 실패: {error}") from error
            time.sleep(RETRY_BACKOFF_SEC * (2 ** attempt))

    if body.get("header", {}).get("resultCode") != "00":
        return []
    items = (body.get("body") or {}).get("items") or {}
    if isinstance(items, dict):
        items = items.get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items


def _ncst_base(now: datetime) -> Tuple[str, str]:
    """초단기실황 발표 기준시각. 매시 정시 자료가 40분 이후 제공된다."""
    ref = now - timedelta(hours=1) if now.minute < 40 else now
    return ref.strftime("%Y%m%d"), ref.strftime("%H00")


def _srt_fcst_base(now: datetime) -> Tuple[str, str]:
    """초단기예보 발표 기준시각. 매시 30분 자료가 45분 이후 제공된다."""
    ref = now - timedelta(hours=1) if now.minute < 45 else now
    return ref.strftime("%Y%m%d"), ref.strftime("%H30")


def _vilage_base(now: datetime) -> Tuple[str, str]:
    """단기예보 발표 기준시각. 3시간 간격 발표분 중 이미 나온 가장 최근 것."""
    ref = now - timedelta(minutes=10)
    for hour in reversed(VILAGE_BASE_HOURS):
        if ref.hour >= hour:
            return ref.strftime("%Y%m%d"), f"{hour:02d}00"
    # 02시 발표 전이면 전날 23시 발표분을 쓴다.
    return (ref - timedelta(days=1)).strftime("%Y%m%d"), "2300"


def _uv_base(now: datetime) -> str:
    """자외선지수 발표 기준시각. 매일 06시/18시 발표."""
    if now.hour >= 18:
        ref = now.replace(hour=18)
    elif now.hour >= 6:
        ref = now.replace(hour=6)
    else:
        ref = (now - timedelta(days=1)).replace(hour=18)
    return ref.strftime("%Y%m%d%H")


def _to_ts(fcst_date: str, fcst_time: str) -> int:
    """'20260728' + '1400' -> UNIX timestamp (KST 해석)"""
    dt = datetime.strptime(fcst_date + fcst_time, "%Y%m%d%H%M").replace(tzinfo=KST)
    return int(dt.timestamp())


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nearest_hub(loc: Dict[str, Any]) -> Dict[str, Any]:
    """
    격자상 가장 가까운 기상청 거점.

    locations.py 거점은 위경도만 갖고 있어 stn_id 와 area_no 가 없다.
    두 값 모두 지점이 아니라 구역 단위(관서 / 시군구)라 인접 거점의 값을 빌려도
    무방하다. 검증된 50개 거점이 전 권역을 덮고 있어 배정에는 충분하다.
    """
    nx, ny = grid_of(loc)
    return min(KMA_HUBS, key=lambda h: (h["nx"] - nx) ** 2 + (h["ny"] - ny) ** 2)


def station_for(loc: Dict[str, Any]) -> int:
    """거점에 해당하는 특보 발표관서."""
    if "stn_id" in loc:
        return loc["stn_id"]
    return _nearest_hub(loc)["stn_id"]


def area_no_for(loc: Dict[str, Any]) -> str:
    """거점에 해당하는 자외선지수 행정구역코드."""
    if "area_no" in loc:
        return loc["area_no"]
    return _nearest_hub(loc)["area_no"]


# 특보 제목의 동작 어미. 발표·변경은 발효, 해제·대치는 해소로 본다.
WARN_ACTIVATING = ("발표", "변경")
WARN_CLEARING = ("해제", "대치")


def _parse_warning_title(title: str) -> List[Tuple[str, bool]]:
    """
    특보 제목에서 (특보명, 발효여부) 목록을 뽑는다.

    제목 예: "[특보] 제07-145호 : 2026.07.28.10:00 / 폭염경보 변경·열대야주의보 해제 (*)"
    한 건에 여러 특보가 가운뎃점으로 묶여 오고, 발표와 해제가 섞이기도 한다.
    """
    if "/" not in title:
        return []
    body = title.split("/", 1)[1]
    body = body.split("(")[0].strip()  # 말미의 (*) 같은 표식 제거

    parsed: List[Tuple[str, bool]] = []
    for segment in body.split("·"):
        segment = segment.strip()
        for action in WARN_ACTIVATING + WARN_CLEARING:
            if segment.endswith(action):
                name = segment[: -len(action)].strip()
                if name:
                    parsed.append((name, action in WARN_ACTIVATING))
                break
    return parsed


def fetch_alerts(stn_id: int, service_key: str, now: Optional[datetime] = None) -> List[str]:
    """
    관서 단위로 현재 발효 중인 특보명 목록.

    발표 이력을 시간순으로 훑으면서 발표된 것은 넣고 해제된 것은 뺀다.
    제목만 보고 "발표"가 들어 있으면 통과시키면, 이미 해제된 특보까지 남는다.

    기간 파라미터는 fromTm/toTm 이 아니라 fromTmFc/toTmFc 다. 이름이 틀리면
    오류가 아니라 NO_DATA 가 조용히 돌아오므로 주의.
    """
    now = now or datetime.now(KST)
    items = _get(
        "WthrWrnInfoService/getWthrWrnList",
        {
            "stnId": stn_id,
            "fromTmFc": (now - timedelta(days=1)).strftime("%Y%m%d"),
            "toTmFc": now.strftime("%Y%m%d"),
            "numOfRows": 100,
        },
        service_key,
    )

    active: List[str] = []
    for item in sorted(items, key=lambda i: str(i.get("tmFc", ""))):
        for name, is_active in _parse_warning_title(item.get("title") or ""):
            if is_active:
                if name not in active:
                    active.append(name)
            elif name in active:
                active.remove(name)
    return active


def _uvi_series(area_no: str, service_key: str, now: datetime) -> Dict[int, float]:
    """자외선지수를 {timestamp: uvi} 로 편다. 발표시각 기준 3시간 간격."""
    items = _get(
        "LivingWthrIdxServiceV5/getUVIdxV5",
        {"areaNo": area_no, "time": _uv_base(now)},
        service_key,
    )
    if not items:
        return {}

    base = datetime.strptime(_uv_base(now), "%Y%m%d%H").replace(tzinfo=KST)
    series: Dict[int, float] = {}
    for key, value in items[0].items():
        if not key.startswith("h") or not key[1:].isdigit():
            continue
        uvi = _num(value)
        if uvi is None:
            continue
        series[int((base + timedelta(hours=int(key[1:]))).timestamp())] = uvi
    return series


def _nearest_uvi(series: Dict[int, float], ts: int) -> Optional[float]:
    """가장 가까운 발표 시각의 자외선 값. 3시간 간격이라 최대 1.5시간 오차."""
    if not series:
        return None
    nearest = min(series, key=lambda t: abs(t - ts))
    if abs(nearest - ts) > 2 * 3600:
        return None
    return series[nearest]


def fetch(
    loc: Dict[str, Any],
    service_key: Optional[str] = None,
    alerts: Optional[List[str]] = None,
    now: Optional[datetime] = None,
) -> WeatherBundle:
    """거점 하나의 날씨를 기상청에서 모아 정규화한다."""
    if not service_key:
        raise ProviderError("KMA_SERVICE_KEY 가 없습니다")

    now = now or datetime.now(KST)
    nx, ny = grid_of(loc)
    grid = {"nx": nx, "ny": ny}

    # --- 초단기실황: 현재값 ---
    base_date, base_time = _ncst_base(now)
    ncst = {
        i["category"]: i.get("obsrValue")
        for i in _get(
            "VilageFcstInfoService_2.0/getUltraSrtNcst",
            {"base_date": base_date, "base_time": base_time, **grid},
            service_key,
        )
    }
    current_temp = _num(ncst.get("T1H"))
    current_humidity = _num(ncst.get("REH"))
    current_wind = _num(ncst.get("WSD"))

    # --- 단기예보: 시간별 예보와 일 최고/최저 ---
    base_date, base_time = _vilage_base(now)
    by_time: Dict[int, Dict[str, Any]] = {}
    daily_max: Optional[float] = None
    daily_min: Optional[float] = None
    for item in _get(
        "VilageFcstInfoService_2.0/getVilageFcst",
        {"base_date": base_date, "base_time": base_time, **grid},
        service_key,
    ):
        ts = _to_ts(item["fcstDate"], item["fcstTime"])
        by_time.setdefault(ts, {})[item["category"]] = item.get("fcstValue")
        # TMX 는 15시, TMN 은 06시 항목에만 실려 온다.
        if item["category"] == "TMX":
            value = _num(item.get("fcstValue"))
            daily_max = value if daily_max is None else max(daily_max, value)
        elif item["category"] == "TMN":
            value = _num(item.get("fcstValue"))
            daily_min = value if daily_min is None else min(daily_min, value)

    # --- 자외선지수 ---
    uvi_series = _uvi_series(area_no_for(loc), service_key, now)

    hourly: List[HourlyPoint] = []
    for ts in sorted(by_time):
        entry = by_time[ts]
        temp = _num(entry.get("TMP"))
        humidity = _num(entry.get("REH"))
        wind = _num(entry.get("WSD"))
        pop = _num(entry.get("POP")) or 0.0
        pty = entry.get("PTY", PTY_NONE)
        hourly.append(
            HourlyPoint(
                dt=ts,
                temp=temp,
                feels_like=feels_like(temp, humidity, wind),
                uvi=_nearest_uvi(uvi_series, ts),
                pop=pop / 100.0,
                is_precip=(pty != PTY_NONE) or pop >= POP_PRECIP_THRESHOLD,
            )
        )

    # --- 초단기예보: 향후 6시간의 세밀한 강수 (OpenWeather 의 minutely 자리) ---
    base_date, base_time = _srt_fcst_base(now)
    srt: Dict[int, Dict[str, Any]] = {}
    for item in _get(
        "VilageFcstInfoService_2.0/getUltraSrtFcst",
        {"base_date": base_date, "base_time": base_time, **grid},
        service_key,
    ):
        srt.setdefault(_to_ts(item["fcstDate"], item["fcstTime"]), {})[item["category"]] = item.get("fcstValue")

    minutely: List[MinutelyPoint] = []
    for ts in sorted(srt):
        entry = srt[ts]
        # RN1 은 "강수없음" 같은 문자열로 오기도 한다.
        rain = _num(entry.get("RN1")) or 0.0
        if entry.get("PTY", PTY_NONE) != PTY_NONE:
            rain = max(rain, 0.1)  # 강수형태가 있으면 양이 0이어도 강수로 본다
        minutely.append(MinutelyPoint(dt=ts, precipitation=rain))

    if not hourly and current_temp is None:
        raise ProviderError("기상청 응답에서 기온을 얻지 못했습니다")

    return WeatherBundle(
        source=SOURCE,
        alerts=alerts if alerts is not None else [],
        current_temp=current_temp,
        current_feels_like=feels_like(current_temp, current_humidity, current_wind),
        current_uvi=_nearest_uvi(uvi_series, int(now.timestamp())),
        daily_max=daily_max,
        daily_min=daily_min,
        daily_feels_like_day=None,
        daily_uvi=max(uvi_series.values()) if uvi_series else None,
        hourly=hourly,
        minutely=minutely,
        # 단기예보는 일 단위 묶음을 주지 않으므로 시간별 POP·PTY 를 날짜별로 접는다.
        daily_forecast=daily_forecast_from_hourly(hourly),
    )
