"""날씨 출처(provider) 모음."""
from weather.providers import kma, openweather
from weather.providers.base import HourlyPoint, MinutelyPoint, ProviderError, WeatherBundle

PROVIDERS = {
    openweather.NAME: openweather,
    kma.NAME: kma,
}


def get_provider(name: str):
    """이름으로 provider 모듈을 얻는다."""
    try:
        return PROVIDERS[name]
    except KeyError:
        raise ValueError(f"알 수 없는 provider: {name} (사용 가능: {', '.join(sorted(PROVIDERS))})") from None


__all__ = [
    "PROVIDERS",
    "get_provider",
    "WeatherBundle",
    "HourlyPoint",
    "MinutelyPoint",
    "ProviderError",
    "kma",
    "openweather",
]
