"""위경도 ↔ 기상청 격자 변환 검증."""
import pytest

from locations.hubs import HUB_LOCATIONS as OW_LOCATIONS
from locations.kma_reference import HUB_LOCATIONS as KMA_LOCATIONS
from weather.providers.grid import grid_of, grid_to_latlon, latlon_to_grid


def test_canonical_seoul():
    """기상청 배포 예제의 기준 사례: 서울 → (60, 127)"""
    assert latlon_to_grid(37.5665, 126.9780) == (60, 127)


def test_round_trip_is_stable():
    """격자 → 위경도 → 격자 가 원래 격자로 돌아와야 한다"""
    for nx, ny in [(60, 127), (98, 76), (89, 90), (52, 38), (92, 131), (55, 124)]:
        lat, lon = grid_to_latlon(nx, ny)
        assert latlon_to_grid(lat, lon) == (nx, ny), f"({nx},{ny}) 왕복 실패"


def test_all_kma_hub_grids_round_trip():
    """locations_xy.py 의 검증된 격자 50개가 모두 왕복해야 한다"""
    for loc in KMA_LOCATIONS:
        nx, ny = loc["nx"], loc["ny"]
        lat, lon = grid_to_latlon(nx, ny)
        assert latlon_to_grid(lat, lon) == (nx, ny), f"{loc['id']} 왕복 실패"


def test_openweather_hubs_convert_into_domain():
    """
    기존 OpenWeather 거점 50개가 모두 기상청 격자 유효 범위로 변환되어야 한다.
    이중화 기간에 두 출처가 같은 지점을 조회하기 위한 전제다.
    """
    for loc in OW_LOCATIONS:
        nx, ny = latlon_to_grid(loc["lat"], loc["lon"])
        assert 1 <= nx <= 149, f"{loc['id']} nx 범위 이탈: {nx}"
        assert 1 <= ny <= 253, f"{loc['id']} ny 범위 이탈: {ny}"


def test_grid_of_prefers_existing_nx_ny():
    """nx/ny 를 이미 가진 거점은 변환하지 않고 그대로 쓴다"""
    assert grid_of({"nx": 60, "ny": 127}) == (60, 127)
    assert grid_of({"lat": 37.5665, "lon": 126.9780}) == (60, 127)
    # 둘 다 있으면 명시된 격자가 이긴다
    assert grid_of({"nx": 1, "ny": 2, "lat": 37.5665, "lon": 126.9780}) == (1, 2)


def test_nearby_points_map_close():
    """가까운 두 지점은 격자에서도 가까워야 한다 (투영 방향 뒤집힘 방지)"""
    a = latlon_to_grid(37.5665, 126.9780)
    b = latlon_to_grid(37.6665, 126.9780)  # 북쪽으로 약 11km
    assert b[1] > a[1], "위도가 오르면 ny 도 올라야 한다"

    c = latlon_to_grid(37.5665, 127.0780)  # 동쪽으로 약 9km
    assert c[0] > a[0], "경도가 오르면 nx 도 올라야 한다"
