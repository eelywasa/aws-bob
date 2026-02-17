"""OpenAI Responses API client with Secrets Manager, retries, and timeouts."""

from __future__ import annotations

import json
import os
import time
from typing import Any

import boto3
import httpx

from .util import get_env, logger

OPENAI_BASE = "https://api.openai.com/v1"
RESPONSES_ENDPOINT = f"{OPENAI_BASE}/responses"
DEFAULT_TIMEOUT = 10
DEFAULT_MAX_TOKENS = 280

def _create_client() -> httpx.Client:
    """Create shared HTTP client with HTTP/2 when available."""
    try:
        return httpx.Client(
            http2=True,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            timeout=DEFAULT_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )
    except Exception:
        logger.warning(
            "HTTP/2 unavailable, falling back to HTTP/1.1",
            extra={"structured": {"http2_fallback": True}},
        )
        return httpx.Client(
            http2=False,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            timeout=DEFAULT_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )


# Module-level shared resources (cold start only, reused across warm invocations)
_CACHED_API_KEY: str | None = None
_CACHED_SECRET_ARN: str | None = None
_SM_CLIENT = boto3.client("secretsmanager")
_CLIENT = _create_client()


def _set_auth_header(key: str) -> None:
    """Update Authorization header only if different."""
    auth = f"Bearer {key}"
    if _CLIENT.headers.get("Authorization") != auth:
        _CLIENT.headers["Authorization"] = auth


def _get_api_key_cached(secret_arn: str) -> str:
    """Fetch OpenAI API key from AWS Secrets Manager, cached per Lambda container."""
    global _CACHED_API_KEY, _CACHED_SECRET_ARN

    if _CACHED_API_KEY is not None and _CACHED_SECRET_ARN == secret_arn:
        _set_auth_header(_CACHED_API_KEY)
        return _CACHED_API_KEY

    resp = _SM_CLIENT.get_secret_value(SecretId=secret_arn)
    secret = resp.get("SecretString")
    if not secret:
        raise ValueError("Secret has no SecretString")
    data = json.loads(secret)
    key = data.get("OPENAI_API_KEY")
    if not key or key == "replace-me-after-first-deploy":
        raise ValueError("OPENAI_API_KEY not configured in Secrets Manager")

    _CACHED_API_KEY = key
    _CACHED_SECRET_ARN = secret_arn
    _set_auth_header(key)
    return key


def _extract_output_text(response_data: dict[str, Any]) -> str:
    """Extract concatenated text from Responses API output array."""
    output = response_data.get("output") or []
    if not isinstance(output, list):
        return ""
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "output_text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
    return " ".join(parts).strip() if parts else ""


def get_completion(
    *,
    instructions: str,
    user_input: str | list[dict[str, Any]],
    api_key: str | None = None,
    secret_arn: str | None = None,
    model: str | None = None,
    max_output_tokens: int | None = None,
    timeout: float | None = None,
    store: bool = False,
) -> str:
    """
    Call OpenAI Responses API and return extracted output text.
    Retries once on 429 or 5xx with 100ms backoff.
    """
    key = api_key
    if not key:
        arn = secret_arn or get_env("OPENAI_SECRET_ARN")
        key = _get_api_key_cached(arn)
    else:
        _set_auth_header(key)

    model_name = model or get_env("OPENAI_MODEL")
    max_tokens = max_output_tokens or int(
        os.environ.get("MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_TOKENS))
    )
    request_timeout = timeout or float(
        os.environ.get("OPENAI_REQUEST_TIMEOUT", str(DEFAULT_TIMEOUT))
    )

    payload: dict[str, Any] = {
        "model": model_name,
        "instructions": instructions,
        "input": user_input,
        "max_output_tokens": max_tokens,
        "store": store,
    }

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            r = _CLIENT.post(
                RESPONSES_ENDPOINT,
                json=payload,
                timeout=request_timeout,
            )
            try:
                if r.status_code == 200:
                    data = r.json()
                    text = _extract_output_text(data)
                    if not text:
                        logger.warning(
                            "OpenAI response had no output_text",
                            extra={"structured": {"status": 200}},
                        )
                        return ""
                    return text

                if r.status_code == 429 or r.status_code >= 500:
                    if attempt == 0:
                        logger.warning(
                            "OpenAI retryable error, retrying",
                            extra={
                                "structured": {
                                    "status": r.status_code,
                                    "attempt": attempt + 1,
                                }
                            },
                        )
                        last_error = httpx.HTTPStatusError(
                            f"OpenAI {r.status_code}", request=r.request, response=r
                        )
                        time.sleep(0.1)
                        continue
                    raise last_error or httpx.HTTPStatusError(
                        f"OpenAI {r.status_code}", request=r.request, response=r
                    )

                # Non-retryable error
                try:
                    err_body = r.json()
                except Exception:
                    err_body = r.text
                logger.error(
                    "OpenAI API error",
                    extra={
                        "structured": {
                            "status": r.status_code,
                            "body_preview": str(err_body)[:200],
                        }
                    },
                )
                raise httpx.HTTPStatusError(
                    f"OpenAI {r.status_code}: {err_body}",
                    request=r.request,
                    response=r,
                )
            finally:
                r.close()

        except httpx.TimeoutException as e:
            logger.error(
                "OpenAI request timed out",
                extra={"structured": {"timeout": request_timeout}},
            )
            raise
        except httpx.HTTPStatusError:
            raise
        except Exception as e:
            last_error = e
            if attempt == 0 and isinstance(
                e, (httpx.NetworkError, httpx.RemoteProtocolError)
            ):
                logger.warning(
                    "OpenAI network error, retrying",
                    extra={"structured": {"attempt": 1}},
                )
                time.sleep(0.1)
                continue
            raise

    raise last_error or RuntimeError("Unexpected completion path")
