"""
weather_all.json 을 생성한다. 예보 수집 워크플로의 진입점.

    cd backend && python -m scripts.generate_weather

OPENWEATHER_API_KEY 로 기준 수집을 하고, KMA_SERVICE_KEY 가 함께 있으면
기상청도 조회해 판정을 비교한다(출력에는 영향 없음).
"""
import io
import os
import sys

from paths import WEATHER_JSON, load_env_file
from weather.pipeline import generate_weather_json


def main() -> None:
    # 워크플로 로그에서 한글이 깨지지 않게 stdout 을 UTF-8 로 다시 연다.
    if hasattr(sys.stdout, "detach"):
        sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding="utf-8")

    load_env_file()
    generate_weather_json(
        api_key=os.environ.get("OPENWEATHER_API_KEY"),
        output_path=WEATHER_JSON,
    )


if __name__ == "__main__":
    main()
