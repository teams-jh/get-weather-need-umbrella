"""
프로젝트 경로 한 곳 정의.

각 모듈이 __file__ 기준으로 상위 디렉터리를 세면, 파일을 옮길 때마다
계산이 조용히 어긋난다(출력이 엉뚱한 곳에 쓰이거나 .env 를 못 찾는다).
기준점을 여기 하나로 두고 나머지는 이 값을 가져다 쓴다.
"""
import os

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)

# 프론트엔드가 읽는 산출물. 경로가 바뀌면 배포된 앱이 깨진다.
WEATHER_JSON = os.path.join(PROJECT_ROOT, "weather_all.json")

# 이중화 비교 산출물 (실행 시 생성, 커밋하지 않음)
COMPARE_JSON = os.path.join(PROJECT_ROOT, "weather_compare.json")

# .env 탐색 순서: 저장소 루트 → backend
ENV_FILES = (
    os.path.join(PROJECT_ROOT, ".env"),
    os.path.join(BACKEND_DIR, ".env"),
)


def load_env_file() -> None:
    """.env 에서 환경변수를 읽어 온다. 먼저 찾은 파일 하나만 읽는다."""
    for env_path in ENV_FILES:
        if not os.path.exists(env_path):
            continue
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")
        return
