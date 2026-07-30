# get-weather-need-umbrella

need-umbrella 앱의 백엔드 전용 저장소입니다. 전국 50개 거점의 예보를 주기적으로
수집해 `weather_all.json` 으로 게시하고, 그 데이터를 근거로 우산 알림을 발송합니다.

프론트엔드는 이 저장소에 커밋된 `weather_all.json` 을 직접 읽습니다. 원격을 못 읽으면
폴백 없이 오류 화면을 띄우므로, 수집 워크플로가 멈추면 앱의 날씨도 멈춥니다.

## 디렉터리 구조

```
backend/
  paths.py            경로 정의 한 곳. weather_all.json 위치와 .env 탐색을 여기서 결정한다.
  weather/            날씨 수집과 판정
    providers/        수집 경로 (openweather, kma, 격자 변환, 체감온도)
    pipeline.py       거점을 돌며 수집하고 weather_all.json 을 조립
    evaluate.py       수집 결과 → 상태 코드(UMBRELLA/PARASOL/JACKET/ALERT/NONE) 판정
  locations/          거점 데이터
    hubs.py           운영 거점 목록. weather_all.json 의 키를 결정하는 프론트엔드와의 계약
    kma_reference.py  기상청 발표관서·행정구역코드 참조표
  notify/             알림 발송
    scheduler.py      발송 대상 판정과 파이프라인
    toss.py           토스 스마트 메시지 전송
    manual_message.py 캠페인 템플릿 확인용 단건 발송
  api/app.py          토스 로그인·알림 설정 API (FastAPI)
  scripts/            워크플로 진입점. 로직은 두지 않고 호출만 한다.
  tests/              pytest. 소스와 섞지 않는다.
weather_all.json      수집 산출물. 워크플로가 자동 커밋한다.
```

## 실행

의존성을 설치한 뒤 `backend` 안에서 `-m` 으로 실행합니다. `-m` 이 아니면 `backend` 가
임포트 루트가 되지 않아 `weather`·`locations` 를 찾지 못합니다.

```bash
pip install -r backend/requirements.txt
cd backend

python -m scripts.generate_weather    # 예보 수집 → weather_all.json
python -m scripts.check_coverage      # 수집 성공률 확인
python -m scripts.run_notifications   # 알림 발송
python -m scripts.verify_kma_codes    # 기상청 관서·구역코드 점검
python -m pytest                      # 테스트
```

인증 API 서버는 별도로 띄웁니다.

```bash
cd backend && uvicorn api.app:app --host 0.0.0.0 --port 8000
```

환경변수는 `.env.example` 을 참고해 `.env` 로 복사해서 씁니다. `OPENWEATHER_API_KEY`
가 없으면 모든 거점이 `status="failed"` 로 기록됩니다.

## 워크플로

| 워크플로 | 스케줄 | 하는 일 |
| --- | --- | --- |
| `weather_update.yml` | 하루 14회 (알림 시간대 1시간, 그 외 2~3시간 간격) | 예보 수집 후 `weather_all.json` 커밋 |
| `notify_pipeline.yml` | 매시 정각 | 우산 알림 발송 |
| `send_test_smart_message.yml` | 수동 | 스마트 메시지 단건 테스트 발송 |

필요한 시크릿: `GH_PAT`, `OPENWEATHER_API_KEY`, `KMA_SERVICE_KEY`(선택),
`FIREBASE_SERVICE_ACCOUNT_KEY`, `TOSS_MTLS_CERT`, `TOSS_MTLS_KEY`.

## 데이터 계약 (`weather_all.json`, meta.version 2.1)

거점마다 `status` 를 가집니다. **소비자는 `status == "ok"` 인 거점만 신뢰해야 합니다.**

- `ok` — 실제 응답으로 채워짐. 화면과 알림에 쓸 수 있는 유일한 상태입니다.
- `failed` — 수집 실패. `recommendation` 키 자체가 없고 `error` 가 대신 들어갑니다.
- `preset` — 더미. 로컬 개발·시연 전용이며 알림 대상에서 제외됩니다.

수집에 실패한 거점의 값을 지어내지 않습니다. 그럴듯한 더미를 채우면 소비자가 정상
동작으로 오판하기 때문입니다. 다만 일부 거점이 실패해도 런 전체를 실패시키지 않고
성공한 거점은 그대로 게시합니다. 부분 실패로 게시를 막으면 앱이 과거 날씨를 현재인
것처럼 보여주게 되어 같은 종류의 거짓말이 됩니다.

### 수집 출처 (`meta.providers`)

예보와 특보는 출처가 다를 수 있으므로 각각 기록합니다. `KMA_SERVICE_KEY` 가 설정되면
예보는 OpenWeather 를 쓰고 **특보만 기상청 것으로 대체하는 하이브리드**로 동작합니다.
OpenWeather 특보는 영문 이벤트명이고, 국내 특보는 기상청이 발표 주체이기 때문입니다.

```jsonc
"meta": {
  "source": "OpenWeatherMap One Call API 3.0 50 + KMA Alerts (Hybrid Real Data - 50/50)",
  "providers": {
    "forecast": "OpenWeatherMap One Call API 3.0 50",
    "alerts": "기상청 특보 조회서비스"   // 키가 없으면 "OpenWeatherMap Alerts"
  }
}
```

### `recommendation` 의 준비물

`state_code` 는 대표 준비물 하나만 가리킵니다. 실제로는 특보·비·자외선·일교차가
동시에 성립할 수 있으므로, 성립한 준비물을 전부 `preparations` 배열로 함께 내보냅니다.
배열 순서는 우선순위(ALERT > UMBRELLA > PARASOL > JACKET)와 같고 `preparations[0]`
이 곧 `state_code` 입니다. 준비할 것이 없으면 `state_code` 는 `NONE`, 배열은 빈 배열입니다.

```jsonc
{
  "state_code": "ALERT",          // 대표 준비물 (기존 필드, 그대로 유지)
  "alert_event": "호우경보",       // 대표 특보 (기존 필드, 그대로 유지)
  "alert_events": ["호우경보", "강풍주의보"],  // 동시 발효된 특보 전부
  "alert_type": "호우",            // 특보명을 정규화한 유형
  "alert_types": ["호우", "강풍"],
  "is_night": true,               // KST 19시~익일 6시
  "preparations": [
    { "type": "ALERT",    "title": "...", "message": "...", "alert_type": "호우" },
    { "type": "UMBRELLA", "title": "...", "message": "...", "rain_start_time": "14:15" }
  ]
}
```

기존 필드는 이름·순서·값이 모두 그대로이고 새 필드는 뒤에 더하기만 했습니다
(`tests/weather/test_evaluate_equivalence.py` 가 이를 검증합니다). 따라서 구 버전
소비자는 그대로 동작합니다.

특보가 떴다고 우산이 필요한 것은 아닙니다. 폭염·건조·황사 특보에는 비가 없으므로
`UMBRELLA` 준비물이 붙지 않습니다. 우산 관련 판단은 `state_code` 가 아니라
`preparations` 에 `type == "UMBRELLA"` 가 있는지로 하십시오.
