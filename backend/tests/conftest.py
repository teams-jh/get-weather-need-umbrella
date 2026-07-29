"""테스트 전역 설정."""
import os

import pytest

# 이 값들이 실행 환경에 들어 있으면 테스트가 조용히 실제 API 를 호출하거나
# 실제 설정을 집어 든다. 수집 코드가 인자 없이 환경변수로 되돌아가는 경로를
# 갖고 있어서, 한 곳에서 끊어 두지 않으면 로컬과 CI 의 결과가 갈린다.
LEAKY_ENV_VARS = (
    "OPENWEATHER_API_KEY",
    "KMA_SERVICE_KEY",
    "WEATHER_PROVIDER",
    "WEATHER_FETCH_WORKERS",
)


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    """주변 환경변수를 모든 테스트에서 차단한다."""
    for name in LEAKY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def testdata_dir():
    """tests/data 절대경로."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
