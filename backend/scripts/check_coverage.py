"""
수집 커버리지를 확인한다. 데이터 게시 이후에 도는 경고용 스텝.

    cd backend && python -m scripts.check_coverage

의도적으로 게시를 막지 않는다. 일부 거점이 실패했다고 커밋을 거르면 성공한
거점까지 갱신이 멈추고, 앱은 과거 날씨를 현재인 것처럼 보여주게 된다. 그래서
weather_all.json 은 항상 먼저 커밋하고, 이 스크립트는 그 뒤에 돌면서 실패율이
임계를 넘었을 때 워크플로를 실패로 표시해 사람이 알아차리게만 한다.

WEATHER_MIN_SUCCESS_RATIO (기본 0.9) 미만이면 종료 코드 1.
"""
import json
import os
import sys

from paths import WEATHER_JSON

DEFAULT_MIN_SUCCESS_RATIO = 0.9


def main() -> int:
    path = os.environ.get("WEATHER_JSON_PATH") or WEATHER_JSON
    try:
        with open(path, "r", encoding="utf-8") as f:
            meta = json.load(f).get("meta", {})
    except (OSError, json.JSONDecodeError) as error:
        print(f"[COVERAGE] {path} 를 읽지 못했습니다: {error}")
        return 1

    total = meta.get("total_locations") or 0
    if not total:
        print("[COVERAGE] total_locations 가 비어 있어 커버리지를 계산할 수 없습니다.")
        return 1

    success = meta.get("success_count", 0)
    preset = meta.get("preset_count", 0)
    failed = meta.get("failed_count", 0)
    ratio = success / total
    threshold = float(os.environ.get("WEATHER_MIN_SUCCESS_RATIO", DEFAULT_MIN_SUCCESS_RATIO))

    print(f"[COVERAGE] success={success} preset={preset} failed={failed} total={total} ratio={ratio:.2%}")

    if preset:
        # 상용 워크플로는 WEATHER_ALLOW_PRESET 을 설정하지 않는다. 프리셋이 섞였다면
        # 설정이 잘못된 것이므로 커버리지와 무관하게 실패로 본다.
        print(f"[COVERAGE] 프리셋 데이터가 {preset}개 섞여 있습니다. WEATHER_ALLOW_PRESET 설정을 확인하세요.")
        return 1

    if ratio < threshold:
        print(f"[COVERAGE] 성공률이 임계({threshold:.0%}) 미만입니다. 실패 거점: {meta.get('failed_locations')}")
        print("[COVERAGE] 데이터는 정상적으로 게시되었습니다. 수집 실패 원인을 확인하세요.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
