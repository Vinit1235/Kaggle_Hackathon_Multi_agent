"""
supabase_auth.py: Supabase Auth helpers using REST endpoints.
Uses service role key on the backend only.
"""

from __future__ import annotations

import os
from typing import Any, Tuple

import httpx
from loguru import logger


class SupabaseAuthError(RuntimeError):
    pass


def _get_supabase_config() -> Tuple[str, str, str]:
    supabase_url = os.getenv("SUPABASE_URL", "") or os.getenv("SUPABASE_PROJECT_URL", "")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    anon_key = os.getenv("SUPABASE_ANON_KEY", "")

    if not supabase_url:
        raise SupabaseAuthError("SUPABASE_URL not configured")
    if not service_key:
        raise SupabaseAuthError("SUPABASE_SERVICE_ROLE_KEY not configured")

    api_key = anon_key or service_key
    return supabase_url.rstrip("/"), service_key, api_key


def _format_error(prefix: str, response: httpx.Response) -> str:
    try:
        payload = response.json()
        message = payload.get("message") or payload.get("error_description") or payload.get("error")
        if message:
            return f"{prefix}: {message}"
    except Exception:
        pass
    return f"{prefix}: HTTP {response.status_code}"


async def create_user(email: str, password: str) -> dict[str, Any]:
    supabase_url, service_key, _ = _get_supabase_config()
    endpoint = f"{supabase_url}/auth/v1/admin/users"

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "email": email,
        "password": password,
        "email_confirm": True,
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(endpoint, headers=headers, json=payload)

    if response.status_code >= 400:
        raise SupabaseAuthError(_format_error("Supabase create user failed", response))

    return response.json()


async def login_user(email: str, password: str) -> dict[str, Any]:
    supabase_url, _, api_key = _get_supabase_config()
    endpoint = f"{supabase_url}/auth/v1/token?grant_type=password"

    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "email": email,
        "password": password,
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(endpoint, headers=headers, json=payload)

    if response.status_code >= 400:
        raise SupabaseAuthError(_format_error("Supabase login failed", response))

    return response.json()
