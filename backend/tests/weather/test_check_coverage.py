"""커버리지 경고 스텝 검증. 게시를 막지 않고 실패율만 판정한다."""
import json

import scripts.check_coverage as check_coverage


def _write(tmp_path, meta):
    path = tmp_path / "weather_all.json"
    path.write_text(json.dumps({"meta": meta, "data": {}}), encoding="utf-8")
    return str(path)


def test_passes_when_coverage_is_high(tmp_path, monkeypatch):
    monkeypatch.setenv("WEATHER_JSON_PATH", _write(tmp_path, {
        "total_locations": 50, "success_count": 50, "preset_count": 0, "failed_count": 0,
    }))
    assert check_coverage.main() == 0


def test_fails_when_coverage_below_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("WEATHER_JSON_PATH", _write(tmp_path, {
        "total_locations": 50, "success_count": 40, "preset_count": 0, "failed_count": 10,
        "failed_locations": ["seoul_south"],
    }))
    assert check_coverage.main() == 1


def test_fails_when_preset_data_leaked(tmp_path, monkeypatch):
    """성공률이 임계를 넘더라도 프리셋이 섞였으면 설정 오류이므로 실패로 본다"""
    monkeypatch.setenv("WEATHER_JSON_PATH", _write(tmp_path, {
        "total_locations": 50, "success_count": 48, "preset_count": 2, "failed_count": 0,
    }))
    assert check_coverage.main() == 1


def test_fails_when_output_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("WEATHER_JSON_PATH", str(tmp_path / "nope.json"))
    assert check_coverage.main() == 1
