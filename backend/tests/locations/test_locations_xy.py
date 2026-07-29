import pytest

from locations.kma_reference import (
    HUB_LOCATIONS,
    LEGACY_AREA_NO,
    LOCATIONS_BY_ID,
    STN_IDS,
    INTEGRATED_JEONNAM_GWANGJU,
    WARN_STATIONS,
    area_no_candidates,
    get_location,
    locations_by_stn_id,
)

# 시도 코드 → 해당 시도에 속한 거점 id (area_no 앞 2자리 검증용)
SIDO_PREFIX = {
    "11": "서울", "12": "전남광주통합특별시", "26": "부산", "27": "대구", "28": "인천",
        "30": "대전", "31": "울산", "36": "세종", "41": "경기", "43": "충북",
    "44": "충남", "47": "경북", "48": "경남", "50": "제주",
    "51": "강원", "52": "전북",
}


def test_hub_locations_structure():
    """50개 거점의 격자좌표 / 발표관서 / 행정구역코드 스키마 무결성 검증"""
    assert len(HUB_LOCATIONS) == 50

    ids = set()
    for loc in HUB_LOCATIONS:
        assert loc["id"] not in ids, f"중복된 location id: {loc['id']}"
        ids.add(loc["id"])

        assert loc["group"] and loc["display_name"]
        # 기상청 격자 좌표 유효 범위 (남한 영역)
        assert 1 <= loc["nx"] <= 149, f"{loc['id']} nx 범위 이탈"
        assert 1 <= loc["ny"] <= 253, f"{loc['id']} ny 범위 이탈"


def test_stn_id_is_known_station():
    """모든 거점의 stn_id가 알려진 발표관서 코드여야 한다"""
    for loc in HUB_LOCATIONS:
        assert loc["stn_id"] in WARN_STATIONS, f"{loc['id']} 미등록 발표관서: {loc['stn_id']}"
        # 108(전국)은 거점 단위 특보 조회에 쓰지 않는다
        assert loc["stn_id"] != 108, f"{loc['id']}에 전국 코드(108)가 지정됨"


def test_area_no_format():
    """area_no는 시도 코드로 시작하는 10자리 숫자 문자열이어야 한다"""
    for loc in HUB_LOCATIONS:
        area_no = loc["area_no"]
        assert isinstance(area_no, str) and area_no.isdigit(), f"{loc['id']} area_no 형식 오류"
        assert len(area_no) == 10, f"{loc['id']} area_no는 10자리여야 함: {area_no}"
        assert area_no[:2] in SIDO_PREFIX, f"{loc['id']} 미상의 시도 코드: {area_no[:2]}"
        # 시군구 단위까지만 사용하므로 읍면동 자리는 0으로 채운다
        assert area_no[5:] == "00000", f"{loc['id']} area_no 하위 자리 오류: {area_no}"


def test_area_no_unique():
    """서로 다른 거점이 같은 행정구역코드를 공유하면 안 된다"""
    seen = {}
    for loc in HUB_LOCATIONS:
        assert loc["area_no"] not in seen, f"{loc['id']}와 {seen.get(loc['area_no'])}의 area_no 중복"
        seen[loc["area_no"]] = loc["id"]


def test_station_matches_region():
    """권역(group)과 발표관서 관할이 어긋나지 않아야 한다"""
    expected = {
        "수도권": {109},
        "강원권": {105},
        "충청권": {131, 133},
        "전라권": {146, 156},
        "경상권": {143, 159},
        "제주권": {184},
    }
    for loc in HUB_LOCATIONS:
        assert loc["stn_id"] in expected[loc["group"]], (
            f"{loc['id']}({loc['group']})에 관할 밖 관서 {loc['stn_id']} 지정"
        )


def test_special_province_codes():
    """강원(51)/전북(52) 특별자치도 개편 코드가 반영되어 있어야 한다"""
    for loc in locations_by_stn_id(105):
        assert loc["area_no"].startswith("51"), f"{loc['id']} 강원 신규 코드 미반영"
    for loc in locations_by_stn_id(146):
        assert loc["area_no"].startswith("52"), f"{loc['id']} 전북 신규 코드 미반영"


def test_legacy_area_no_is_empty():
    """
    강원/전북 9개 거점이 실측에서 모두 현행 코드로 응답했으므로 폴백은 비어 있어야 한다.
    다시 채운다면 구 시도 코드(42/45) 형식을 지켜야 한다.
    """
    assert LEGACY_AREA_NO == {}, "폴백을 되살렸다면 실측 근거를 남길 것"

    for loc_id, legacy in LEGACY_AREA_NO.items():
        assert len(legacy) == 10 and legacy.isdigit()
        current = LOCATIONS_BY_ID[loc_id]["area_no"]
        assert legacy[2:] == current[2:], f"{loc_id} 구 코드의 하위 자리가 현행과 다름"
        assert legacy[:2] in {"42", "45"}, f"{loc_id} 구 시도 코드 오류: {legacy[:2]}"


def test_area_no_candidates_order():
    """폴백이 비어 있으므로 현행 코드 하나만 반환한다"""
    assert area_no_candidates(get_location("seoul")) == ["1100000000"]
    assert area_no_candidates(get_location("chuncheon")) == ["5111000000"]


def test_integrated_jeonnam_gwangju_codes():
    """전남광주통합특별시(2026-07-01) 출범에 따른 시도코드 12 반영 검증"""
    for loc_id, code in INTEGRATED_JEONNAM_GWANGJU.items():
        assert loc_id in LOCATIONS_BY_ID, f"없는 거점 id: {loc_id}"
        assert LOCATIONS_BY_ID[loc_id]["area_no"] == code
        assert code.startswith("12"), f"{loc_id} 통합 시도코드 미반영"
        # 통합 전 광주(29)/전남(46) 코드가 남아 있으면 안 된다
        assert not code.startswith(("29", "46"))
    # 모두 광주지방기상청(156) 관할이다
    assert all(LOCATIONS_BY_ID[i]["stn_id"] == 156 for i in INTEGRATED_JEONNAM_GWANGJU)


def test_stn_ids_cover_all_locations():
    """STN_IDS로 특보를 조회하면 모든 거점이 커버되어야 한다"""
    covered = [loc for stn_id in STN_IDS for loc in locations_by_stn_id(stn_id)]
    assert len(covered) == len(HUB_LOCATIONS)
    assert len(STN_IDS) == 9, "발표관서 조회 횟수는 9회여야 함"


def test_get_location():
    assert get_location("seoul")["nx"] == 60
    assert get_location("does_not_exist") is None
