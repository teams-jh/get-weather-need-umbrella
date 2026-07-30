"""Authenticated API for Toss login and notification preferences.

Run with: cd backend && uvicorn api.app:app --host 0.0.0.0 --port 8000
All Toss partner API calls are server-to-server and use the configured mTLS client
certificate. Tokens are used only to obtain the app-scoped userKey, then discarded.
"""
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from itsdangerous import BadSignature, URLSafeTimedSerializer

TOSS_API_BASE = os.getenv('TOSS_API_BASE_URL', 'https://apps-in-toss-api.toss.im')
SESSION_COOKIE = 'need_umbrella_session'
SESSION_MAX_AGE = 60 * 60 * 24 * 14
# 신규 유저에게 제공하는 임시 이용권 기간. 프론트엔드 getDefaultUserData와 반드시 일치해야 합니다.
# 광고를 활성화하면 3일로 되돌립니다.
INITIAL_AD_PASS_DAYS = 365
serializer = URLSafeTimedSerializer(os.environ['SESSION_SECRET_KEY'])

app = FastAPI(title='Need Umbrella API')
allowed_origins = [origin for origin in os.getenv('CORS_ALLOWED_ORIGINS', '').split(',') if origin]
if allowed_origins:
    app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_credentials=True, allow_methods=['GET', 'POST', 'PUT'], allow_headers=['Content-Type'])


def toss_certificate() -> tuple[str, str]:
    cert, key = os.getenv('TOSS_MTLS_CERT_PATH'), os.getenv('TOSS_MTLS_KEY_PATH')
    if not cert or not key:
        raise HTTPException(500, 'Toss mTLS credentials are not configured')
    return cert, key


def toss_request(method: str, path: str, **kwargs: Any) -> requests.Response:
    return requests.request(method, f'{TOSS_API_BASE}{path}', cert=toss_certificate(), timeout=10, **kwargs)


def get_user_key(authorization_code: str, referrer: str) -> str:
    token_response = toss_request('POST', '/api-partner/v1/apps-in-toss/user/oauth2/generate-token', json={'authorizationCode': authorization_code, 'referrer': referrer})
    if not token_response.ok:
        raise HTTPException(401, 'Toss authorization code exchange failed')
    access_token = token_response.json().get('success', {}).get('accessToken')
    if not access_token:
        raise HTTPException(502, 'Toss token response did not contain an access token')
    profile_response = toss_request('GET', '/api-partner/v1/apps-in-toss/user/oauth2/login-me', headers={'Authorization': f'Bearer {access_token}'})
    if not profile_response.ok:
        raise HTTPException(401, 'Toss user lookup failed')
    user_key = profile_response.json().get('success', {}).get('userKey')
    if user_key is None:
        raise HTTPException(502, 'Toss user response did not contain userKey')
    return str(user_key)


def authenticated_user(session: str | None) -> str:
    if not session:
        raise HTTPException(401, 'Authentication required')
    try:
        return str(serializer.loads(session, max_age=SESSION_MAX_AGE)['userKey'])
    except (BadSignature, KeyError):
        raise HTTPException(401, 'Invalid session') from None


def firestore_client():
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
        if not firebase_admin._apps:
            credential_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY')
            if not credential_json:
                raise RuntimeError('FIREBASE_SERVICE_ACCOUNT_KEY is not configured')
            import json
            firebase_admin.initialize_app(credentials.Certificate(json.loads(credential_json)))
        return firestore.client()
    except Exception as error:
        raise HTTPException(503, f'Preference storage is unavailable: {error}') from error


def default_preferences(user_key: str) -> dict[str, Any]:
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    expires_at = (now_dt + timedelta(days=INITIAL_AD_PASS_DAYS)).isoformat()
    return {'userKey': user_key, 'isNotificationEnabled': False, 'notificationTypes': {'morning': True, 'preRain': True, 'evening': True, 'alert': True, 'weekend': True}, 'morningTime': '07:30', 'adPass': {'active': True, 'expiresAt': expires_at, 'lastAdWatchedAt': now, 'totalWatchCount': 0}, 'lastNotified': {}, 'createdAt': now, 'updatedAt': now}


@app.post('/v1/auth/toss/exchange')
async def exchange_login(payload: dict[str, str], response: Response):
    code, referrer = payload.get('authorizationCode'), payload.get('referrer')
    if not code or referrer not in {'DEFAULT', 'SANDBOX'}:
        raise HTTPException(400, 'authorizationCode and a valid referrer are required')
    user_key = get_user_key(code, referrer)
    response.set_cookie(SESSION_COOKIE, serializer.dumps({'userKey': user_key}), max_age=SESSION_MAX_AGE, httponly=True, secure=True, samesite='lax')
    return {'userKey': user_key}


@app.get('/v1/session')
async def session(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    return {'userKey': authenticated_user(session)}


@app.get('/v1/preferences')
async def get_preferences(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user_key = authenticated_user(session)
    snapshot = firestore_client().collection('users').document(user_key).get()
    return snapshot.to_dict() if snapshot.exists else default_preferences(user_key)


@app.put('/v1/preferences')
async def put_preferences(payload: dict[str, Any], session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user_key = authenticated_user(session)
    document = {**default_preferences(user_key), **payload, 'userKey': user_key, 'updatedAt': datetime.now(timezone.utc).isoformat()}
    firestore_client().collection('users').document(user_key).set(document, merge=True)
    return document


@app.post('/v1/toss/unlink')
async def toss_unlink(request: Request):
    expected_secret = os.getenv('TOSS_UNLINK_CALLBACK_SECRET')
    if expected_secret and not secrets.compare_digest(request.headers.get('X-Callback-Secret', ''), expected_secret):
        raise HTTPException(401, 'Invalid callback secret')
    payload = await request.json()
    user_key = str(payload.get('userKey', ''))
    if not user_key:
        raise HTTPException(400, 'userKey is required')
    firestore_client().collection('users').document(user_key).set({'isNotificationEnabled': False, 'updatedAt': datetime.now(timezone.utc).isoformat()}, merge=True)
    return {'ok': True}
