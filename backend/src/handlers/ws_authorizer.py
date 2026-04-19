"""WebSocket $connect Lambda authorizer.

Validates a Cognito JWT (id_token) from the query string parameter ``token``.
Returns an IAM policy allowing or denying the $connect route.

The token is verified against the Cognito JWKS endpoint using the ``pyjwt``
library with ``cryptography`` for RS256 support.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request

import jwt
from jwt import PyJWKClient

_log = logging.getLogger()
_log.setLevel(logging.INFO)

_USER_POOL_ID = os.environ["COGNITO_USER_POOL_ID"]
_REGION = os.environ.get("COGNITO_REGION", os.environ.get("AWS_REGION", "us-east-1"))
_JWKS_URL = f"https://cognito-idp.{_REGION}.amazonaws.com/{_USER_POOL_ID}/.well-known/jwks.json"
_ISSUER = f"https://cognito-idp.{_REGION}.amazonaws.com/{_USER_POOL_ID}"

# Cache the JWK client across Lambda invocations
_jwk_client: PyJWKClient | None = None


def _get_jwk_client() -> PyJWKClient:
    global _jwk_client  # noqa: PLW0603
    if _jwk_client is None:
        _jwk_client = PyJWKClient(_JWKS_URL)
    return _jwk_client


def _generate_policy(principal_id: str, effect: str, resource: str, context: dict | None = None) -> dict:
    policy = {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": resource,
                }
            ],
        },
    }
    if context:
        policy["context"] = context
    return policy


def handler(event, _context):
    _log.info("Authorizer invoked for route %s", event.get("requestContext", {}).get("routeKey"))

    qs = event.get("queryStringParameters") or {}
    token = qs.get("token", "")

    if not token:
        _log.warning("No token in query string")
        return _generate_policy("anonymous", "Deny", event["methodArn"])

    try:
        jwk_client = _get_jwk_client()
        signing_key = jwk_client.get_signing_key_from_jwt(token)

        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=_ISSUER,
            options={
                "verify_aud": False,  # id_tokens have aud=client_id; we skip strict check
                "verify_exp": True,
            },
        )

        user_id = claims.get("sub", "unknown")
        email = claims.get("email", "")
        display_name = claims.get("name", email.split("@")[0] if email else "User")

        _log.info("Authorized userId=%s email=%s", user_id, email)

        return _generate_policy(
            user_id,
            "Allow",
            event["methodArn"],
            context={
                "userId": user_id,
                "email": email,
                "displayName": display_name,
            },
        )

    except jwt.ExpiredSignatureError:
        _log.warning("Token expired")
        return _generate_policy("anonymous", "Deny", event["methodArn"])
    except jwt.InvalidTokenError as exc:
        _log.warning("Invalid token: %s", exc)
        return _generate_policy("anonymous", "Deny", event["methodArn"])
    except Exception:
        _log.exception("Authorizer error")
        return _generate_policy("anonymous", "Deny", event["methodArn"])
