"""
Firebase ID-token verification using Firebase's public JWK certificates.

No service account or gcloud setup required — just FIREBASE_PROJECT_ID.
Firebase publishes its public signing keys at a well-known URL; PyJWT
fetches and caches them, then verifies the token signature + claims locally.
"""

from __future__ import annotations

import logging

from jwt import PyJWKClient, decode, PyJWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import FIREBASE_PROJECT_ID

logger = logging.getLogger(__name__)

_FIREBASE_JWK_URL = (
    "https://www.googleapis.com/service_accounts/v1/jwk/"
    "securetoken@system.gserviceaccount.com"
)

# Fetches and caches Firebase's public keys; refreshes automatically when they rotate.
_jwks_client = PyJWKClient(_FIREBASE_JWK_URL, cache_jwk_set=True, lifespan=3600)

_bearer = HTTPBearer(auto_error=True)


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """
    Verify a Firebase ID token from the Authorization: Bearer header.
    Returns the decoded claims dict (contains uid, email, etc.).
    Raises HTTP 401 on any failure.
    """
    token = creds.credentials
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        payload = decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=FIREBASE_PROJECT_ID,
            issuer=f"https://securetoken.google.com/{FIREBASE_PROJECT_ID}",
        )
        # Firebase stores the user id in the 'sub' claim
        payload.setdefault("uid", payload.get("sub"))
        return payload
    except PyJWTError as exc:
        logger.warning("Firebase token verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
        )
