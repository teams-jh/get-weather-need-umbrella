# 50개 권역별 거점 도시 좌표 명세 (기상청 API 기준)
#
# 기상청은 API마다 요구하는 지역 키가 다르므로 거점별로 3종을 함께 보관한다.
#   - nx / ny   : 기상청 격자 좌표. 단기예보 조회서비스(VilageFcstInfoService_2.0)의
#                 getUltraSrtNcst / getUltraSrtFcst / getVilageFcst 에 사용.
#   - stn_id    : 특보 발표관서 번호. 기상특보 조회서비스(WthrWrnInfoService)의
#                 getWthrWrnList / getWthrWrnMsg 에 사용.
#   - area_no   : 행정구역코드(법정동코드 10자리). 생활기상지수 조회서비스
#                 (LivingWthrIdxServiceV5)의 getUVIdxV5 에 사용.
#
# 검증 상태 (verify_kma_codes.py, 실서비스키 기준): nx/ny·stn_id·area_no 모두 50/50 통과.

# 기상특보 발표관서 코드 → 관할 구역
# stn_id 는 관서 단위이므로 한 번 조회하면 관할 내 모든 거점이 결과를 공유한다.
# 50개 거점 전체를 순회하지 말고 STN_IDS 만 조회한 뒤 거점에 매핑할 것.
# 아래 표는 활용가이드 '첨부. 지점코드'와 대조해 10개 관서 모두 일치를 확인했다.
#
# 주의: getWthrWrnList / getWthrWrnMsg 의 기간 파라미터는 fromTm/toTm 이 아니라
# fromTmFc / toTmFc 다. 이름을 틀리면 오류 대신 NO_DATA(03) 가 조용히 돌아온다.
WARN_STATIONS = {
    105: "강원지방기상청 (강원)",
    108: "기상청 본청 (전국)",
    109: "수도권기상청 (서울/인천/경기)",
    131: "청주기상지청 (충북)",
    133: "대전지방기상청 (대전/세종/충남)",
    143: "대구지방기상청 (대구/경북)",
    146: "전주기상지청 (전북)",
    156: "광주지방기상청 (광주/전남)",
    159: "부산지방기상청 (부산/울산/경남)",
    184: "제주지방기상청 (제주)",
}

HUB_LOCATIONS = [
    # --- 수도권 (수도권기상청 109) ---
    {"id": "seoul", "group": "수도권", "display_name": "서울", "nx": 60, "ny": 127, "stn_id": 109, "area_no": "1100000000"},
    {"id": "incheon", "group": "수도권", "display_name": "인천", "nx": 55, "ny": 124, "stn_id": 109, "area_no": "2800000000"},
    {"id": "suwon", "group": "수도권", "display_name": "수원", "nx": 60, "ny": 120, "stn_id": 109, "area_no": "4111000000"},
    {"id": "seongnam", "group": "수도권", "display_name": "성남", "nx": 63, "ny": 124, "stn_id": 109, "area_no": "4113000000"},
    {"id": "goyang", "group": "수도권", "display_name": "고양", "nx": 57, "ny": 128, "stn_id": 109, "area_no": "4128000000"},
    {"id": "yongin", "group": "수도권", "display_name": "용인", "nx": 62, "ny": 120, "stn_id": 109, "area_no": "4146000000"},
    {"id": "bucheon", "group": "수도권", "display_name": "부천", "nx": 56, "ny": 125, "stn_id": 109, "area_no": "4119000000"},
    {"id": "ansan", "group": "수도권", "display_name": "안산", "nx": 58, "ny": 121, "stn_id": 109, "area_no": "4127000000"},
    {"id": "gwacheon", "group": "수도권", "display_name": "과천", "nx": 60, "ny": 124, "stn_id": 109, "area_no": "4129000000"},
    {"id": "hwaseong", "group": "수도권", "display_name": "화성", "nx": 57, "ny": 119, "stn_id": 109, "area_no": "4159000000"},
    {"id": "pyeongtaek", "group": "수도권", "display_name": "평택", "nx": 62, "ny": 114, "stn_id": 109, "area_no": "4122000000"},
    {"id": "paju", "group": "수도권", "display_name": "파주", "nx": 56, "ny": 131, "stn_id": 109, "area_no": "4148000000"},

    # --- 강원권 (강원지방기상청 105) ---
    {"id": "chuncheon", "group": "강원권", "display_name": "춘천", "nx": 73, "ny": 134, "stn_id": 105, "area_no": "5111000000"},
    {"id": "wonju", "group": "강원권", "display_name": "원주", "nx": 76, "ny": 122, "stn_id": 105, "area_no": "5113000000"},
    {"id": "gangneung", "group": "강원권", "display_name": "강릉", "nx": 92, "ny": 131, "stn_id": 105, "area_no": "5115000000"},
    {"id": "sokcho", "group": "강원권", "display_name": "속초", "nx": 82, "ny": 143, "stn_id": 105, "area_no": "5121000000"},
    {"id": "pyeongchang", "group": "강원권", "display_name": "평창", "nx": 77, "ny": 125, "stn_id": 105, "area_no": "5176000000"},

    # --- 충청권 (대전지방기상청 133 / 청주기상지청 131) ---
    {"id": "daejeon", "group": "충청권", "display_name": "대전", "nx": 67, "ny": 100, "stn_id": 133, "area_no": "3000000000"},
    {"id": "sejong", "group": "충청권", "display_name": "세종", "nx": 66, "ny": 103, "stn_id": 133, "area_no": "3611000000"},
    {"id": "cheongju", "group": "충청권", "display_name": "청주", "nx": 69, "ny": 106, "stn_id": 131, "area_no": "4311000000"},
    {"id": "chungju", "group": "충청권", "display_name": "충주", "nx": 76, "ny": 114, "stn_id": 131, "area_no": "4313000000"},
    {"id": "jecheon", "group": "충청권", "display_name": "제천", "nx": 81, "ny": 118, "stn_id": 131, "area_no": "4315000000"},
    {"id": "cheonan", "group": "충청권", "display_name": "천안", "nx": 63, "ny": 110, "stn_id": 133, "area_no": "4413000000"},
    {"id": "gongju", "group": "충청권", "display_name": "공주", "nx": 63, "ny": 102, "stn_id": 133, "area_no": "4415000000"},
    {"id": "seosan", "group": "충청권", "display_name": "서산", "nx": 51, "ny": 110, "stn_id": 133, "area_no": "4421000000"},

    # --- 전라권 (광주지방기상청 156 / 전주기상지청 146) ---
    {"id": "gwangju", "group": "전라권", "display_name": "광주", "nx": 58, "ny": 74, "stn_id": 156, "area_no": "1224000000"},
    {"id": "jeonju", "group": "전라권", "display_name": "전주", "nx": 63, "ny": 89, "stn_id": 146, "area_no": "5211000000"},
    {"id": "gunsan", "group": "전라권", "display_name": "군산", "nx": 56, "ny": 92, "stn_id": 146, "area_no": "5213000000"},
    {"id": "iksan", "group": "전라권", "display_name": "익산", "nx": 60, "ny": 91, "stn_id": 146, "area_no": "5214000000"},
    {"id": "jeongeup", "group": "전라권", "display_name": "정읍", "nx": 58, "ny": 83, "stn_id": 146, "area_no": "5218000000"},
    {"id": "mokpo", "group": "전라권", "display_name": "목포", "nx": 50, "ny": 67, "stn_id": 156, "area_no": "1211000000"},
    {"id": "yeosu", "group": "전라권", "display_name": "여수", "nx": 73, "ny": 66, "stn_id": 156, "area_no": "1213000000"},
    {"id": "suncheon", "group": "전라권", "display_name": "순천", "nx": 69, "ny": 70, "stn_id": 156, "area_no": "1215000000"},
    {"id": "gwangyang", "group": "전라권", "display_name": "광양", "nx": 73, "ny": 70, "stn_id": 156, "area_no": "1219000000"},
    {"id": "naju", "group": "전라권", "display_name": "나주", "nx": 56, "ny": 71, "stn_id": 156, "area_no": "1217000000"},

    # --- 경상권 (부산지방기상청 159 / 대구지방기상청 143) ---
    {"id": "busan", "group": "경상권", "display_name": "부산", "nx": 98, "ny": 76, "stn_id": 159, "area_no": "2600000000"},
    {"id": "ulsan", "group": "경상권", "display_name": "울산", "nx": 102, "ny": 84, "stn_id": 159, "area_no": "3100000000"},
    {"id": "daegu", "group": "경상권", "display_name": "대구", "nx": 89, "ny": 90, "stn_id": 143, "area_no": "2700000000"},
    {"id": "pohang", "group": "경상권", "display_name": "포항", "nx": 102, "ny": 94, "stn_id": 143, "area_no": "4711000000"},
    {"id": "gyeongju", "group": "경상권", "display_name": "경주", "nx": 100, "ny": 91, "stn_id": 143, "area_no": "4713000000"},
    {"id": "gumi", "group": "경상권", "display_name": "구미", "nx": 84, "ny": 96, "stn_id": 143, "area_no": "4719000000"},
    {"id": "andong", "group": "경상권", "display_name": "안동", "nx": 91, "ny": 106, "stn_id": 143, "area_no": "4717000000"},
    {"id": "changwon", "group": "경상권", "display_name": "창원", "nx": 90, "ny": 77, "stn_id": 159, "area_no": "4812000000"},
    {"id": "jinju", "group": "경상권", "display_name": "진주", "nx": 81, "ny": 75, "stn_id": 159, "area_no": "4817000000"},
    {"id": "tongyeong", "group": "경상권", "display_name": "통영", "nx": 87, "ny": 68, "stn_id": 159, "area_no": "4822000000"},
    {"id": "sacheon", "group": "경상권", "display_name": "사천", "nx": 80, "ny": 71, "stn_id": 159, "area_no": "4824000000"},
    {"id": "gimhae", "group": "경상권", "display_name": "김해", "nx": 95, "ny": 77, "stn_id": 159, "area_no": "4825000000"},
    {"id": "geoje", "group": "경상권", "display_name": "거제", "nx": 90, "ny": 69, "stn_id": 159, "area_no": "4831000000"},

    # --- 제주권 (제주지방기상청 184) ---
    {"id": "jeju", "group": "제주권", "display_name": "제주시", "nx": 52, "ny": 38, "stn_id": 184, "area_no": "5011000000"},
    {"id": "seogwipo", "group": "제주권", "display_name": "서귀포시", "nx": 52, "ny": 33, "stn_id": 184, "area_no": "5013000000"}
]

# 강원특별자치도(2023-06-11, 42→51)·전북특별자치도(2024-01-18, 45→52) 개편 이후의
# 신규 코드를 기상청이 받아주지 않을 것에 대비해 구 코드 폴백을 두었으나,
# 실측 결과 해당 9개 거점이 모두 현행 코드로 정상 응답했다. 폴백은 불필요해 비워 둔다.
# (area_no_candidates() 의 폴백 경로는 향후 유사 개편에 대비해 남겨 둔다.)
LEGACY_AREA_NO = {}

# 전남광주통합특별시 출범(2026-07-01)으로 광주광역시(29)와 전라남도(46)가 폐지되고
# 시도코드 12 로 통합됐다. 아래 6개 거점의 area_no 는 그에 맞춰 갱신한 것이다.
# 신규 코드는 getUVIdxV5 의 전체지점 목록(areaNo 공백, 3847건)에 실재하며
# 모두 정상 응답하는 것을 확인했다.
#
# 코드↔지명 대응은 공식 문서로 확인했다. 순서가 갈릴 수 있었던 나주(1217)·광양(1219)도
# 대조를 마쳤다. 통합시 기초단체 코드는 전남 5시 → 광주 5구 → 전남 17군 순이고,
# 구 코드의 하위 자리가 대체로 보존된다(목포110·여수130·순천150·나주170 유지,
# 230 이던 광양만 190 으로 당겨짐).
INTEGRATED_JEONNAM_GWANGJU = {
    "gwangju": "1224000000",    # 광주 서구 (통합 전 광주광역시 대표 지점)
    "mokpo": "1211000000",
    "yeosu": "1213000000",
    "suncheon": "1215000000",
    "naju": "1217000000",
    "gwangyang": "1219000000",
}

# 기상특보 조회 시 순회할 발표관서 목록 (거점 50회 → 관서 9회로 축소)
STN_IDS = sorted({loc["stn_id"] for loc in HUB_LOCATIONS})

# id 기반 조회 인덱스
LOCATIONS_BY_ID = {loc["id"]: loc for loc in HUB_LOCATIONS}


def get_location(loc_id):
    """거점 id로 거점 정보를 조회한다. 없으면 None."""
    return LOCATIONS_BY_ID.get(loc_id)


def locations_by_stn_id(stn_id):
    """특정 발표관서가 관할하는 거점 목록을 반환한다."""
    return [loc for loc in HUB_LOCATIONS if loc["stn_id"] == stn_id]


def area_no_candidates(loc):
    """
    생활기상지수 API에 사용할 areaNo 후보를 우선순위대로 반환한다.
    현행 코드를 먼저 쓰고, 시도 개편 대상 지역은 구 코드를 폴백으로 덧붙인다.
    """
    candidates = [loc["area_no"]]
    legacy = LEGACY_AREA_NO.get(loc["id"])
    if legacy:
        candidates.append(legacy)
    return candidates
