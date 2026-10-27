"""Requests to Kleinanzeigen's app API: the client credential, retries, the
error messages the model sees, and unwrapping its JAXB-shaped JSON."""

import asyncio
import functools
import logging
import time
import uuid
from typing import Literal, Optional

import httpx
from mcp.server.mcpserver.exceptions import ToolError


logger = logging.getLogger(__name__)


BASE_URL = "https://api.kleinanzeigen.de/api"
GATEWAY_URL = "https://gateway.kleinanzeigen.de"

KA_CLIENT = "Kleinanzeigen/2026.37.1 (Android 14; google sdk_gphone64_x86_64)"
KA_ECG_USER_AGENT = "ebayk-android-app-2026.37.1"
KA_ECG_USER_VERSION = "2026.37.1"

# --- Request authentication ------------------------------------------------
# Every request carries a static HTTP Basic credential baked into the app
# (reverse-engineered from the APK, not user-specific). Decodes to
# "android:TaR60pEttY".
KA_BASIC_AUTH = "Basic YW5kcm9pZDpUYVI2MHBFdHRZ"

# `x-ebayk-app` identifies the app installation: a UUIDv4 immediately followed
# by the epoch-millis timestamp of when it was generated, no separator (e.g.
# "7243bedb-2427-4f72-bf89-567ecb1c74661789285561410"). Captured traffic shows
# a fresh, never-before-seen value accepted immediately with no separate
# registration call, so it looks like a free-form client-generated id the
# server does not validate -- generated once per process and reused here.
_installation_id = f"{uuid.uuid4()}{int(time.time() * 1000)}"


MAX_RETRIES = 2
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


client = httpx.AsyncClient(http2=True)


# Confirmed against the server's own ads-search-options schema
# (api/ads/search-metadata/{categoryId}.json) rather than guessed.
Sort = Literal["RECOMMENDED", "DATE_DESCENDING", "PRICE_ASCENDING", "PRICE_DESCENDING", "DISTANCE_ASCENDING"]
AdType = Literal["OFFERED", "WANTED"]
PosterType = Literal["PRIVATE", "COMMERCIAL"]


def upstream_message(status: int, what: str, body: str = "") -> str:
    """Phrase an HTTP failure in terms the caller can act on, without the
    internal url and MDN link httpx puts in its own message."""
    if status == 404:
        return f"no {what} found -- wrong id, or the ad has been taken down"
    if status == 400:
        return f"Kleinanzeigen rejected the {what} request (400); check the arguments you passed"
    if status in (401, 403):
        # a blocked IP range and a stale credential both come back as 403, but
        # only the block says so in the body -- they need opposite fixes
        if "gesperrt" in body or "blocked" in body.lower():
            return (f"Kleinanzeigen blocked this IP range on the {what} request ({status}). Their "
                    f"anti-fraud rejects whole ranges (VPN and datacenter IPs in particular), so "
                    f"this usually needs a different connection, not a retry. Search and ad "
                    f"lookups are unaffected -- only the seller profile enforces it.")
        return (f"Kleinanzeigen refused the {what} request ({status}) -- the client credential "
                f"in kleinanzeigen/api.py (KA_BASIC_AUTH) may be outdated")
    if status == 429:
        return f"Kleinanzeigen rate-limited the {what} request (429) -- slow down and retry later"
    return f"Kleinanzeigen failed on the {what} request (HTTP {status})"


def tool_errors(what: str):
    """Turn upstream failures into a ``ToolError`` the model can read, rather
    than a raw httpx error; any exception that is not a ``ToolError`` would only
    reach it as "Error executing tool". ``what`` names the thing being fetched,
    for the message."""
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except httpx.HTTPStatusError as exc:
                raise ToolError(upstream_message(exc.response.status_code, what, exc.response.text)) from exc
            except httpx.HTTPError as exc:
                raise ToolError(f"could not reach Kleinanzeigen for the {what} request "
                                f"({type(exc).__name__})") from exc
        return wrapper
    return decorator


def _auth_headers(*, user_token: str = "") -> dict:
    """Headers the app sends on every api.kleinanzeigen.de / gateway.kleinanzeigen.de
    call. `user_token` is left empty when not logged in."""
    return {
        "authorization": KA_BASIC_AUTH,
        "x-ebayk-app": _installation_id,
        "x-ebayk-userid-token": user_token,
        "user-agent": KA_CLIENT,
        "x-ecg-user-agent": KA_ECG_USER_AGENT,
        "x-ecg-user-version": KA_ECG_USER_VERSION,
        "accept-encoding": "gzip",
    }


async def get(endpoint: str, params: Optional[dict] = None) -> dict:
    """GET an api.kleinanzeigen.de endpoint. See `_request`."""
    return await _request(f"{BASE_URL}/{endpoint}", params)


async def get_gateway(endpoint: str, params: Optional[dict] = None) -> dict:
    """GET a gateway.kleinanzeigen.de endpoint (newer services: seller
    reputation, homepage feed, ...). See `_request`."""
    return await _request(f"{GATEWAY_URL}/{endpoint}", params)


async def _request(url: str, params: Optional[dict] = None) -> dict:
    """GET a kleinanzeigen.de URL, retrying transient failures (timeouts,
    429, 5xx) with exponential backoff. Other 4xx errors fail immediately."""
    headers = _auth_headers()
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await client.get(url, params=params, headers=headers)
        except httpx.TransportError:
            if attempt == MAX_RETRIES:
                raise
        else:
            if response.status_code not in RETRYABLE_STATUS or attempt == MAX_RETRIES:
                response.raise_for_status()
                return response.json()
        delay = 0.5 * (2 ** attempt)
        logger.warning("Request to '%s' failed (attempt %d/%d), retrying in %.1fs",
                       url, attempt + 1, MAX_RETRIES + 1, delay)
        await asyncio.sleep(delay)


# Kleinanzeigen's JSON is JAXB-serialized XML (com.ebay.ecg.api.spec...), so
# scalar fields don't come as plain values -- they're wrapped as {"value": ...},
# and top-level collections are keyed by their XML namespace URI. `unwrap` unwraps
# the former; `collection` picks out the latter regardless of the exact namespace string.
def unwrap(node, default=None):
    return node.get("value", default) if isinstance(node, dict) else default


def collection(container: dict, local_name: str) -> dict:
    for key, val in container.items():
        if key.endswith(f"}}{local_name}") or key == local_name:
            return unwrap(val, {})
    return {}
