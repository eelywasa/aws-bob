"""OpenAI Responses API client with Secrets Manager, retries, and timeouts."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import boto3
import httpx

from .util import get_env, logger

OPENAI_BASE = "https://api.openai.com/v1"
RESPONSES_ENDPOINT = f"{OPENAI_BASE}/responses"
DEFAULT_TIMEOUT = 10
DEFAULT_MAX_TOKENS = 280

# Module-level shared resources (cold start only)
_CACHED_API_KEY: str | None = None
_CACHED_SECRET_ARN: str | None = None
_API_KEY_LOCK = asyncio.Lock()
_SM_CLIENT = boto3.client("secretsmanager")
_CLIENT = httpx.AsyncClient(
    limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
    timeout=DEFAULT_TIMEOUT,
    headers={"Content-Type": "application/json"},
)


async def _get_api_key_cached(secret_arn: str) -> str:
    """Fetch OpenAI API key from AWS Secrets Manager, cached per Lambda container."""
    global _CACHED_API_KEY, _CACHED_SECRET_ARN

    if _CACHED_API_KEY is not None and _CACHED_SECRET_ARN == secret_arn:
        return _CACHED_API_KEY

    async with _API_KEY_LOCK:
        if _CACHED_API_KEY is not None and _CACHED_SECRET_ARN == secret_arn:
            return _CACHED_API_KEY

        resp = await asyncio.to_thread(
            _SM_CLIENT.get_secret_value, SecretId=secret_arn
        )
        secret = resp.get("SecretString")
        if not secret:
            raise ValueError("Secret has no SecretString")
        data = json.loads(secret)
        key = data.get("OPENAI_API_KEY")
        if not key or key == "replace-me-after-first-deploy":
            raise ValueError("OPENAI_API_KEY not configured in Secrets Manager")

        _CACHED_API_KEY = key
        _CACHED_SECRET_ARN = secret_arn
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


async def get_completion(
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
    Retries once on 429 or 5xx with 200ms backoff.
    """
    key = api_key
    if not key:
        arn = secret_arn or get_env("OPENAI_SECRET_ARN")
        key = await _get_api_key_cached(arn)

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
            r = await _CLIENT.post(
                RESPONSES_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=request_timeout,
            )

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
                    await asyncio.sleep(0.2)
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
                await asyncio.sleep(0.2)
                continue
            raise

    raise last_error or RuntimeError("Unexpected completion path")
