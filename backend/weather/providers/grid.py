"""
위경도 → 기상청 격자 좌표(nx, ny) 변환.

기상청 단기예보는 위경도가 아니라 5km 격자 번호를 받는다. 기존 거점 목록
(locations.py)은 위경도로 되어 있으므로, 같은 지점을 두 출처가 함께 조회하려면
변환이 필요하다. 거점 목록을 갈아치우면 weather_all.json 의 키가 바뀌어
프론트엔드가 깨지고, 이중화 기간에 두 출처를 지점 단위로 비교할 수도 없다.

기상청 배포 예제(DFS_XY_CONV)의 Lambert Conformal Conic 투영을 그대로 옮겼다.
"""
import math

RE = 6371.00877  # 지구 반경 (km)
GRID = 5.0       # 격자 간격 (km)
SLAT1 = 30.0     # 표준 위도 1
SLAT2 = 60.0     # 표준 위도 2
OLON = 126.0     # 기준점 경도
OLAT = 38.0      # 기준점 위도
XO = 43          # 기준점 X 격자
YO = 136         # 기준점 Y 격자

DEGRAD = math.pi / 180.0


def _projection_constants():
    re = RE / GRID
    slat1 = SLAT1 * DEGRAD
    slat2 = SLAT2 * DEGRAD
    olon = OLON * DEGRAD
    olat = OLAT * DEGRAD

    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)

    sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
    sf = (sf ** sn) * math.cos(slat1) / sn

    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re * sf / (ro ** sn)

    return sn, sf, ro, olon


def latlon_to_grid(lat: float, lon: float):
    """위경도를 기상청 격자 (nx, ny) 로 변환한다."""
    sn, sf, ro, olon = _projection_constants()

    ra = math.tan(math.pi * 0.25 + lat * DEGRAD * 0.5)
    ra = (RE / GRID) * sf / (ra ** sn)

    theta = lon * DEGRAD - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn

    nx = int(math.floor(ra * math.sin(theta) + XO + 0.5))
    ny = int(math.floor(ro - ra * math.cos(theta) + YO + 0.5))
    return nx, ny


def grid_to_latlon(nx: int, ny: int):
    """격자 → 위경도 (셀 기준점). 왕복 검증과 디버깅용."""
    sn, sf, ro, olon = _projection_constants()

    xn = nx - XO
    yn = ro - ny + YO
    ra = math.sqrt(xn * xn + yn * yn)
    if sn < 0.0:
        ra = -ra
    alat = ((RE / GRID) * sf / ra) ** (1.0 / sn)
    alat = 2.0 * math.atan(alat) - math.pi * 0.5

    if abs(xn) <= 0.0:
        theta = 0.0
    elif abs(yn) <= 0.0:
        theta = math.pi * 0.5
        if xn < 0.0:
            theta = -theta
    else:
        theta = math.atan2(xn, yn)

    alon = theta / sn + olon
    return alat / DEGRAD, alon / DEGRAD


def grid_of(loc: dict):
    """
    거점에서 격자 좌표를 얻는다.
    nx/ny 를 이미 들고 있으면 그대로 쓰고, 없으면 위경도로 계산한다.
    """
    if "nx" in loc and "ny" in loc:
        return loc["nx"], loc["ny"]
    return latlon_to_grid(loc["lat"], loc["lon"])
