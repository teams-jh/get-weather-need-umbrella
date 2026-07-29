"""
locations_xy.py 의 기상청 지역 키(nx/ny, stn_id, area_no)를 실제 API 응답으로 검증한다.

공공데이터포털에서 발급받은 서비스키를 KMA_SERVICE_KEY 환경변수(또는 .env)에 넣고 실행:

    cd backend && KMA_SERVICE_KEY=... python -m scripts.verify_kma_codes
    cd backend && KMA_SERVICE_KEY=... python -m scripts.verify_kma_codes --only area

검증 항목
  grid : getUltraSrtNcst  — nx/ny 격자 좌표가 실황을 반환하는지
  area : getUVIdxV5       — area_no(행정구역코드)가 자외선지수를 반환하는지.
                            현행 코드가 비면 LEGACY_AREA_NO 구 코드로 재시도하고,
                            어느 쪽이 응답했는지에 따라 폴백 유지 여부를 판정한다.
  stn  : getPwnStatus     — 특보 파이프라인이 동작하는지 (stnId 불필요, 전국 1회)
         getWthrWrnList   — stn_id(발표관서)별 특보 목록

판정 상태
  OK       정상 응답
  LEGACY   구 코드로만 응답 (폴백 유지 필요)
  UNKNOWN  응답은 정상이나 데이터가 없어 코드 유효성을 판정할 수 없음.
           getWthrWrnList는 특보가 없을 때와 관서 코드가 틀렸을 때가
           모두 NO_DATA(03)라 구분되지 않는다.
  BLOCKED  403 — 해당 API 활용신청 미승인. 코드 문제가 아니다.
  FAIL     응답이 왔으나 코드가 유효하지 않음
"""
import argparse
import os
import re
import sys
import time as time_mod
from datetime import datetime, timedelta, timezone

import requests

from paths import load_env_file
from locations.kma_reference import HUB_LOCATIONS, LEGACY_AREA_NO, STN_IDS, WARN_STATIONS, area_no_candidates

KST = timezone(timedelta(hours=9))
BASE = "https://apis.data.go.kr/1360000"
TIMEOUT = 15
PAUSE = 0.4  # 포털 호출 간격 (초). 너무 짧으면 간헐적으로 연결이 끊긴다.


def ncst_base(now):
    """초단기실황 발표 기준시각. 매시 정시 자료가 40분 이후 제공된다."""
    ref = now - timedelta(hours=1) if now.minute < 40 else now
    return ref.strftime("%Y%m%d"), ref.strftime("%H00")


def uv_base_time(now):
    """자외선지수 발표 기준시각. 매일 06시/18시 발표."""
    if now.hour >= 18:
        ref = now.replace(hour=18)
    elif now.hour >= 6:
        ref = now.replace(hour=6)
    else:
        ref = (now - timedelta(days=1)).replace(hour=18)
    return ref.strftime("%Y%m%d%H")


def call(path, params, service_key, retries=2):
    """
    기상청 API를 호출하고 (resultCode, items, note)를 반환한다.
    오류 시 dataType=JSON 이어도 XML로 응답하는 경우가 있어 방어적으로 파싱한다.
    포털이 연속 호출을 간헐적으로 끊으므로 일시적 실패는 재시도한다.
    """
    query = {"serviceKey": service_key, "dataType": "JSON", "pageNo": 1, "numOfRows": 100}
    query.update(params)

    resp = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(f"{BASE}/{path}", params=query, timeout=TIMEOUT)
            break
        except Exception as exc:
            if attempt == retries:
                return None, [], f"요청 실패: {exc}"
            time_mod.sleep(1.0 * (attempt + 1))

    text = resp.text.strip()
    if resp.status_code == 401 or text == "Unauthorized":
        return None, [], "서비스키 인증 실패 (401 Unauthorized)"
    if resp.status_code == 403 or text == "Forbidden":
        return "FORBIDDEN", [], "403 Forbidden — 해당 API 활용신청이 승인되지 않음"

    if text.startswith("<"):
        code = re.search(r"<returnReasonCode>(.*?)</returnReasonCode>", text)
        msg = re.search(r"<returnAuthMsg>(.*?)</returnAuthMsg>", text)
        detail = msg.group(1) if msg else text[:120].replace("\n", " ")
        return (code.group(1) if code else None), [], f"XML 오류 응답: {detail}"

    try:
        body = resp.json().get("response", {})
    except ValueError:
        return None, [], f"JSON 파싱 실패: {text[:120]}"

    result_code = body.get("header", {}).get("resultCode")
    result_msg = body.get("header", {}).get("resultMsg", "")
    items = body.get("body", {}).get("items") or {}
    if isinstance(items, dict):
        items = items.get("item") or []
    if isinstance(items, dict):
        items = [items]
    return result_code, items, result_msg


def check_grid(loc, service_key, now):
    base_date, base_time = ncst_base(now)
    code, items, note = call(
        "VilageFcstInfoService_2.0/getUltraSrtNcst",
        {"base_date": base_date, "base_time": base_time, "nx": loc["nx"], "ny": loc["ny"]},
        service_key,
    )
    if code != "00":
        return "FAIL", f"resultCode={code} {note}"
    if not items:
        return "FAIL", "실황 항목 없음 (격자 좌표 확인 필요)"
    temps = [i.get("obsrValue") for i in items if i.get("category") == "T1H"]
    return "OK", (f"T1H={temps[0]}°C" if temps else "실황 수신")


def check_area(loc, service_key, now):
    """
    현행 area_no를 먼저 시도하고, 비면 구 코드로 폴백한다.
    반환 상태는 OK / LEGACY(구 코드로만 응답) / BLOCKED(활용신청 미승인) / FAIL.
    """
    base_time = uv_base_time(now)
    attempts = []
    for area_no in area_no_candidates(loc):
        code, items, note = call(
            "LivingWthrIdxServiceV5/getUVIdxV5",
            {"areaNo": area_no, "time": base_time},
            service_key,
        )
        if code == "FORBIDDEN":
            # 코드 문제가 아니라 권한 문제이므로 폴백을 시도할 의미가 없다.
            return "BLOCKED", note
        is_legacy = area_no == LEGACY_AREA_NO.get(loc["id"])
        label = f"{area_no}{' (구 코드)' if is_legacy else ''}"
        if code == "00" and items and items[0].get("h0") not in (None, ""):
            return ("LEGACY" if is_legacy else "OK"), f"{label} → UVI h0={items[0].get('h0')}"
        attempts.append(f"{label}: resultCode={code} {note or '항목 없음'}")
        time_mod.sleep(PAUSE)
    return "FAIL", " | ".join(attempts)


def check_stn(stn_id, service_key, now):
    """
    stn_id 유효성 검증.
    기간 파라미터는 fromTm/toTm 이 아니라 fromTmFc/toTmFc 다 (활용가이드 호출 예시 기준).
    이름이 틀리면 오류가 아니라 NO_DATA(03)가 조용히 돌아오므로 주의.
    특보가 실제로 없는 기간에도 NO_DATA 가 나오므로 그때는 UNKNOWN 으로 다룬다.
    """
    code, items, note = call(
        "WthrWrnInfoService/getWthrWrnList",
        {
            "stnId": stn_id,
            "fromTmFc": (now - timedelta(days=3)).strftime("%Y%m%d"),
            "toTmFc": now.strftime("%Y%m%d"),
        },
        service_key,
    )
    if code == "FORBIDDEN":
        return "BLOCKED", note
    if code == "03":
        return "UNKNOWN", "NO_DATA — 특보 없음. 코드 유효성은 판정 불가"
    if code != "00":
        return "FAIL", f"resultCode={code} {note}"
    return "OK", f"특보 {len(items)}건 조회됨"


def check_pwn_status(service_key):
    """
    특보현황(getPwnStatus)은 stnId 없이 전국 현황을 1회 호출로 반환한다.
    특보 파이프라인이 실제로 동작하는지 확인하는 용도.
    """
    code, items, note = call("WthrWrnInfoService/getPwnStatus", {"numOfRows": 5}, service_key)
    if code == "FORBIDDEN":
        return "BLOCKED", note
    if code != "00" or not items:
        return "FAIL", f"resultCode={code} {note}"
    kinds = sorted({k for item in items for k, v in item.items() if k.startswith("t") and not k.startswith("tm") and v})
    return "OK", f"발효 중 특보 필드: {', '.join(kinds) or '없음'} (tmFc={items[0].get('tmFc')})"


def main():
    parser = argparse.ArgumentParser(description="기상청 지역 키 검증")
    parser.add_argument("--only", choices=["grid", "area", "stn"], help="특정 검증만 수행")
    parser.add_argument("--limit", type=int, help="거점 수 제한 (빠른 확인용)")
    args = parser.parse_args()

    load_env_file()
    service_key = os.environ.get("KMA_SERVICE_KEY")
    if not service_key:
        print("[ERROR] KMA_SERVICE_KEY가 없습니다. 공공데이터포털 서비스키(Decoding)를 설정하세요.")
        return 2

    now = datetime.now(KST)
    locations = HUB_LOCATIONS[: args.limit] if args.limit else HUB_LOCATIONS
    failures = []

    blocked = []
    unknown = []

    def record(status, label):
        if status == "BLOCKED":
            blocked.append(label)
        elif status == "UNKNOWN":
            unknown.append(label)
        elif status != "OK" and status != "LEGACY":
            failures.append(label)

    if args.only in (None, "stn"):
        print("\n[특보현황] getPwnStatus — 전국 1회 호출")
        status, note = check_pwn_status(service_key)
        record(status, "getPwnStatus")
        print(f"  {status:<8} {note}")

        print(f"\n[특보 발표관서] getWthrWrnList — {len(STN_IDS)}개 관서")
        for stn_id in STN_IDS:
            status, note = check_stn(stn_id, service_key, now)
            record(status, f"stn_id {stn_id}")
            print(f"  {status:<8} {stn_id} {WARN_STATIONS[stn_id]:<28} {note}")
            time_mod.sleep(PAUSE)

    if args.only in (None, "grid"):
        print(f"\n[격자 좌표] getUltraSrtNcst — {len(locations)}개 거점")
        for loc in locations:
            status, note = check_grid(loc, service_key, now)
            record(status, f"nx/ny {loc['id']}")
            print(f"  {status:<8} {loc['id']:<12} ({loc['nx']},{loc['ny']}) {note}")
            time_mod.sleep(PAUSE)

    if args.only in (None, "area"):
        print(f"\n[행정구역코드] getUVIdxV5 — {len(locations)}개 거점")
        legacy_used, current_ok = [], []
        for loc in locations:
            status, note = check_area(loc, service_key, now)
            record(status, f"area_no {loc['id']}")
            if status == "LEGACY":
                legacy_used.append(loc["id"])
            elif status == "OK" and loc["id"] in LEGACY_AREA_NO:
                current_ok.append(loc["id"])
            print(f"  {status:<8} {loc['id']:<12} {note}")
            time_mod.sleep(PAUSE)

        # 폴백 판정은 강원/전북 거점이 실제로 응답했을 때만 내린다.
        # 전부 BLOCKED/FAIL이면 아무 결론도 내리지 않는다.
        affected = [loc["id"] for loc in locations if loc["id"] in LEGACY_AREA_NO]
        if legacy_used:
            print(f"\n  [판정] 구 코드로만 응답한 거점: {', '.join(legacy_used)}")
            print("         → LEGACY_AREA_NO 폴백을 유지해야 합니다.")
        elif affected and len(current_ok) == len(affected):
            print("\n  [판정] 강원/전북 거점이 모두 현행 코드로 응답했습니다.")
            print("         → LEGACY_AREA_NO 폴백을 제거해도 됩니다.")
        elif affected:
            print("\n  [판정 보류] 강원/전북 거점을 확인하지 못해 폴백 유지 여부를 결정할 수 없습니다.")

    print("\n" + "=" * 60)
    if blocked:
        print(f"[BLOCKED] {len(blocked)}건 — 활용신청 미승인(403). 포털에서 승인 후 재실행하세요.")
    if unknown:
        print(f"[UNKNOWN] {len(unknown)}건 — 응답은 정상이나 데이터가 없어 판정 불가.")
    if failures:
        print(f"[FAIL] {len(failures)}건 실패: {', '.join(failures)}")
        return 1
    if blocked:
        return 2
    print("[OK] 검증한 모든 지역 키가 유효합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
