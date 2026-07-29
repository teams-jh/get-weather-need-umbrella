"""
거점별 날씨를 모아 weather_all.json 을 만든다.

수집(provider) · 판정(evaluate) · 조립(여기)이 분리되어 있다.
이 파일은 거점을 돌면서 provider 를 부르고 결과를 파일로 내보내는 일만 한다.

이중화: KMA_SERVICE_KEY 가 있으면 기상청도 함께 조회해 판정 결과를 비교하고
차이를 로그로 남긴다. 사용자에게 나가는 값은 기준 provider(기본 openweather)의
것이며, 비교용 조회는 출력에 영향을 주지 않는다.

실패 처리 원칙: 조회에 실패한 거점의 값을 지어내지 않는다. 실패는 거점 단위로
status="failed" 와 error 로 기록하고 recommendation 키 자체를 내보내지 않는다.
그럴듯한 더미를 채우면 소비자(앱·알림)가 정상 동작으로 오판하기 때문이다.
런 자체는 실패시키지 않는다. 일부가 실패했다고 성공한 거점의 갱신까지 막으면
앱이 과거 날씨를 현재인 것처럼 보여주게 되어 같은 종류의 거짓말이 된다.
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from paths import COMPARE_JSON, WEATHER_JSON
from weather.evaluate import KST, evaluate, format_rain_title  # noqa: F401  (format_rain_title 재수출)
from locations.hubs import HUB_LOCATIONS
from weather.providers import get_provider, kma, openweather
from weather.providers.base import FORECAST_DAYS, ProviderError

DEFAULT_PROVIDER = os.environ.get("WEATHER_PROVIDER", openweather.NAME)

# 거점 조회는 전부 네트워크 대기라 병렬로 돌린다. 기상청은 거점당 4회를 부르므로
# 순차로 하면 50거점에 수십 분이 걸린다. 포털 한도(30 tps)에는 한참 못 미치는 수준으로 잡는다.
FETCH_WORKERS = int(os.environ.get("WEATHER_FETCH_WORKERS", "4"))

# 거점 단위 수집 결과.
#   ok      실제 응답으로 채워짐. 알림·화면에 쓸 수 있는 유일한 상태다.
#   failed  조회 실패. recommendation 을 내보내지 않는다.
#   preset  아래 프리셋으로 채워짐. 내부 개발/시연에서만 나온다.
STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_PRESET = "preset"

# 프리셋(더미)은 기본적으로 꺼져 있다. 상용 워크플로는 이 값을 설정하지 않으므로
# 실패가 프리셋으로 둔갑할 경로 자체가 없다. 로컬 개발이나 UI 시연에서만 켠다.
# 켜더라도 거점 status 가 preset 으로 남아 알림 발송 대상에서는 제외된다.
PRESET_ENABLED = os.environ.get("WEATHER_ALLOW_PRESET", "").strip().lower() in ("1", "true", "yes")




DEFAULT_NONE_PRESET = {
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
    "alert_event": None,
}

# 시연용 프리셋 (주요 거점만). 5가지 상태를 한 화면씩 보여주려고 만든 데모 세트라
# 폴백으로 쓰면 안 된다. WEATHER_ALLOW_PRESET 이 켜졌을 때만 쓰인다.
DEFAULT_STATES_PRESET = {
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
        "alert_event": None,
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
        "alert_event": None,
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
        "alert_event": None,
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
        "alert_event": None,
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
        "alert_event": "호우주의보",
    },
}


def _prefetch_kma_alerts(locations, service_key: str) -> Dict[int, List[str]]:
    """
    특보는 발표관서 단위라 거점마다 부를 필요가 없다.
    관할 관서만 한 번씩 조회해 거점 50회를 관서 9회로 줄인다.
    """
    alerts_by_station: Dict[int, List[str]] = {}
    for station in sorted({kma.station_for(loc) for loc in locations}):
        try:
            alerts_by_station[station] = kma.fetch_alerts(station, service_key)
        except ProviderError as error:
            print(f"[WARN] 특보 조회 실패 (관서 {station}): {error}")
            alerts_by_station[station] = []
    return alerts_by_station


def _compare(loc_id: str, primary: Dict[str, Any], secondary: Dict[str, Any]) -> Dict[str, Any]:
    """두 출처의 판정을 비교해 차이를 정리한다."""
    return {
        "id": loc_id,
        "match": primary["state_code"] == secondary["state_code"],
        "primary": primary["state_code"],
        "secondary": secondary["state_code"],
        "max_temp_diff": round(secondary["max_temp"] - primary["max_temp"], 1),
        "max_uvi_diff": round(secondary["max_uvi"] - primary["max_uvi"], 1),
    }


def preset_forecast(recommendation: Dict[str, Any], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    프리셋 거점의 forecast 자리를 채우는 더미 (WEATHER_ALLOW_PRESET 전용).
    스키마를 비우지 않되 미래 날짜에 비가 온다고 지어내지는 않는다.
    """
    today = (now or datetime.now(KST)).astimezone(KST)
    rains_today = recommendation.get("state_code") in ("UMBRELLA", "ALERT")
    return [
        {
            "date": (today + timedelta(days=offset)).strftime("%Y-%m-%d"),
            "pop": 0.8 if (rains_today and offset == 0) else 0.1,
            "has_rain": rains_today and offset == 0,
        }
        for offset in range(FORECAST_DAYS)
    ]


def generate_weather_json(
    api_key: str = None,
    output_path: Optional[str] = None,
    provider_name: Optional[str] = None,
    kma_service_key: Optional[str] = None,
    compare_path: Optional[str] = None,
) -> Dict[str, Any]:
    """50개 거점 날씨를 수집해 weather_all.json 을 만든다."""
    if not output_path:
        output_path = WEATHER_JSON

    provider_name = provider_name or os.environ.get("WEATHER_PROVIDER") or DEFAULT_PROVIDER
    provider = get_provider(provider_name)
    if kma_service_key is None:
        kma_service_key = os.environ.get("KMA_SERVICE_KEY")

    # 기준 provider 가 이미 기상청이면 따로 비교하지 않는다.
    kma_is_primary = provider_name == kma.NAME
    dual_run = bool(api_key) and bool(kma_service_key) and not kma_is_primary

    # 특보는 기상청이 기준일 때도 필요하다. 비교용으로만 받으면 전환 후 ALERT 가 사라진다.
    # 기준이 기상청이면 api_key 가 곧 기상청 서비스키다.
    if kma_is_primary and api_key:
        alerts_by_station = _prefetch_kma_alerts(HUB_LOCATIONS, api_key)
    elif dual_run:
        alerts_by_station = _prefetch_kma_alerts(HUB_LOCATIONS, kma_service_key)
    else:
        alerts_by_station = {}

    def _alerts_for(loc: Dict[str, Any]) -> List[str]:
        return alerts_by_station.get(kma.station_for(loc), [])

    result_data: Dict[str, Any] = {}
    comparisons: List[Dict[str, Any]] = []
    sources_seen: Dict[str, int] = {}
    failed_locations: List[str] = []
    real_count = 0
    preset_count = 0
    kma_ok = 0
    kma_failed = 0

    if not api_key:
        if PRESET_ENABLED:
            print("[WARNING] API 키가 없습니다. WEATHER_ALLOW_PRESET 이 켜져 있어 프리셋으로 채웁니다.")
            print("[WARNING] 이 산출물은 내부 확인용입니다. 상용에 배포하지 마십시오.")
        else:
            print("[ERROR] API 키가 감지되지 않았습니다. 모든 거점을 수집 실패로 기록합니다.")
    else:
        print(f"[INFO] 기준 provider: {provider_name}. 실시간 날씨 조회를 시작합니다...")
    if dual_run:
        print(f"[INFO] 이중화: 기상청을 함께 조회해 비교합니다 (관서 {len(alerts_by_station)}곳 특보 선조회).")

    def collect(loc: Dict[str, Any]) -> Dict[str, Any]:
        """
        거점 하나를 조회한다. 호출은 전부 I/O 대기라 거점 단위로 병렬 실행한다.
        집계는 순서를 지키려고 호출자 쪽에서 순차로 한다.
        """
        outcome: Dict[str, Any] = {"loc": loc, "bundle": None, "kma": None, "error": None, "errors": []}
        if api_key:
            try:
                if kma_is_primary:
                    outcome["bundle"] = kma.fetch(loc, api_key, alerts=_alerts_for(loc))
                else:
                    outcome["bundle"] = provider.fetch(loc, api_key)
            except ProviderError as error:
                # 사유는 산출물에 그대로 남긴다. 실패한 거점을 나중에 추적하려면 필요하다.
                outcome["error"] = str(error)
                outcome["errors"].append(f"[FAILED] {loc['id']} 조회 실패: {error}")
        else:
            outcome["error"] = "API 키가 설정되지 않았습니다"
        if dual_run:
            try:
                outcome["kma"] = kma.fetch(loc, kma_service_key, alerts=_alerts_for(loc))
            except ProviderError as error:
                outcome["errors"].append(f"[COMPARE] {loc['id']} 기상청 조회 실패: {error}")
        return outcome

    if api_key or dual_run:
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            outcomes = list(pool.map(collect, HUB_LOCATIONS))
    else:
        outcomes = [
            {
                "loc": loc,
                "bundle": None,
                "kma": None,
                "error": "API 키가 설정되지 않았습니다",
                "errors": [],
            }
            for loc in HUB_LOCATIONS
        ]

    # 수집이 끝난 시각. meta.updated_at 과 거점별 fetched_at 이 같은 기준을 쓴다.
    run_at = datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00")

    for outcome in outcomes:
        loc = outcome["loc"]
        loc_id = loc["id"]
        group = loc.get("group", "")
        display_name = loc.get("display_name", "")
        if group and display_name and group != display_name:
            full_name = f"{group}_{display_name}"
        else:
            full_name = group or display_name or loc.get("name", loc_id)

        for message in outcome["errors"]:
            print(message)

        recommendation = None
        forecast: List[Dict[str, Any]] = []
        bundle = outcome["bundle"]
        if bundle is not None:
            recommendation = evaluate(bundle)
            forecast = [asdict(day) for day in bundle.daily_forecast]
            status = STATUS_OK
            # 어느 경로가 실제로 응답했는지는 묶음이 들고 있다 (3.0 vs 2.5 등).
            sources_seen[bundle.source] = sources_seen.get(bundle.source, 0) + 1
            real_count += 1
        elif PRESET_ENABLED:
            recommendation = DEFAULT_STATES_PRESET.get(loc_id, DEFAULT_NONE_PRESET)
            forecast = preset_forecast(recommendation)
            status = STATUS_PRESET
            preset_count += 1
        else:
            status = STATUS_FAILED
            failed_locations.append(loc_id)

        if dual_run:
            if outcome["kma"] is None:
                kma_failed += 1
            elif status == STATUS_OK:
                comparisons.append(_compare(loc_id, recommendation, evaluate(outcome["kma"])))
                kma_ok += 1
            # 기준 provider 가 실패한 거점은 비교할 상대가 없다. 기상청 쪽 실패가
            # 아니므로 kma_failed 로도 세지 않는다.

        entry: Dict[str, Any] = {
            "id": loc_id,
            "name": full_name,
            "group": group,
            "display_name": display_name,
            "lat": loc["lat"],
            "lon": loc["lon"],
            "status": status,
        }
        if recommendation is None:
            # 값을 지어내지 않는다. recommendation 키를 아예 넣지 않아야
            # 소비자가 빈 객체를 정상 판정으로 오인할 여지가 없다.
            # 거점 자체는 남긴다. 빼버리면 알림이 기본 거점(서울)으로 폴백해
            # 엉뚱한 지역 날씨를 보내고, 앱은 빈 화면을 띄운다.
            entry["error"] = outcome["error"] or "조회 실패"
        else:
            if status == STATUS_OK:
                entry["fetched_at"] = run_at
            entry["recommendation"] = recommendation
            # 오늘 포함 3일치 강수 요약. recommendation 이 오늘 자정까지만 다루므로
            # 금요일 저녁의 주말 알림은 이 값을 본다.
            entry["forecast"] = forecast
        result_data[loc_id] = entry

    failed_count = len(failed_locations)
    if real_count > 0:
        detail = ", ".join(f"{name} {count}" for name, count in sorted(sources_seen.items()))
        source = f"{detail} (Real Data - {real_count}/{len(HUB_LOCATIONS)})"
        if preset_count:
            source += f" (Preset: {preset_count})"
        if failed_count:
            source += f" (Failed: {failed_count})"
        run_status = STATUS_OK if not preset_count and not failed_count else "partial"
    elif preset_count > 0:
        source = "Preset Dummy Data (Internal Use Only)"
        run_status = STATUS_FAILED
    else:
        source = "Collection Failed (No Data)"
        run_status = STATUS_FAILED

    output = {
        "meta": {
            # 2.1 부터 거점마다 status 를 갖는다. 소비자는 status == "ok" 인
            # 거점만 신뢰해야 한다.
            "version": "2.1",
            # 실패했더라도 이 런이 언제 돌았는지는 사실이다. 갱신 자체를 거르면
            # 앱이 과거 값을 현재로 오해하므로 항상 기록한다.
            "updated_at": run_at,
            "status": run_status,
            "source": source,
            "total_locations": len(HUB_LOCATIONS),
            "success_count": real_count,
            "preset_count": preset_count,
            "failed_count": failed_count,
            "failed_locations": failed_locations,
        },
        "data": result_data,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("=" * 50)
    print("[SUMMARY] Weather Data Generation Completed!")
    print(f" - Output File   : {output_path}")
    print(f" - Provider      : {provider_name}")
    print(f" - Data Source   : {source}")
    print(f" - Run Status    : {run_status}")
    print(f" - Total Cities  : {len(result_data)}")
    print(f" - Real Data     : {real_count}")
    print(f" - Preset        : {preset_count}")
    print(f" - Failed        : {failed_count}")
    if failed_locations:
        print(f" - Failed IDs    : {', '.join(failed_locations)}")

    if dual_run:
        mismatches = [c for c in comparisons if not c["match"]]
        print(f" - KMA Compared  : {kma_ok} (실패 {kma_failed})")
        print(f" - State Match   : {kma_ok - len(mismatches)}/{kma_ok}")
        for c in mismatches:
            print(
                f"   [MISMATCH] {c['id']}: {c['primary']} vs 기상청 {c['secondary']}"
                f" (기온차 {c['max_temp_diff']:+}°C, 자외선차 {c['max_uvi_diff']:+})"
            )
        if compare_path is None:
            compare_path = COMPARE_JSON
        with open(compare_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "generated_at": output["meta"]["updated_at"],
                    "primary": provider_name,
                    "secondary": kma.NAME,
                    "compared": kma_ok,
                    "failed": kma_failed,
                    "mismatched": len(mismatches),
                    "results": comparisons,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(f" - Compare File  : {compare_path}")
    print("=" * 50)
    return output


