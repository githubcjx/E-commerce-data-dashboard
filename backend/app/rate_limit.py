"""In-process sliding-window rate limiter for the login endpoint.

Single-instance only: state lives in this process's memory. We run one backend
container in prod, so that's fine. If the deployment ever scales horizontally,
swap the dict for Redis.

Policy:
  - Up to LOGIN_MAX_ATTEMPTS failed logins per LOGIN_WINDOW_SEC, per client IP.
  - Hitting the cap returns 429 for LOGIN_BLOCK_SEC.
  - A successful login clears that IP's counter.
  - Client IP comes from X-Forwarded-For (Caddy sets it) or the socket.
"""
from __future__ import annotations

import time
from collections import deque
from threading import Lock

from fastapi import HTTPException, Request

LOGIN_MAX_ATTEMPTS = 5         # failures
LOGIN_WINDOW_SEC = 60          # ... per this many seconds
LOGIN_BLOCK_SEC = 5 * 60       # ... triggers this much cool-down

_failures: dict[str, deque[float]] = {}
_blocked_until: dict[str, float] = {}
_lock = Lock()


def _client_ip(request: Request) -> str:
    # Caddy → backend always sets X-Forwarded-For. Trust the *leftmost* entry
    # (original client). In setups behind another proxy you'd want stricter
    # parsing; for our single-Caddy topology this is fine.
    xff = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if xff:
        return xff
    return request.client.host if request.client else "unknown"


def check_login_allowed(request: Request) -> None:
    """Call BEFORE attempting credential verification. Raises 429 if blocked."""
    ip = _client_ip(request)
    now = time.monotonic()
    with _lock:
        until = _blocked_until.get(ip)
        if until and until > now:
            wait = int(until - now)
            raise HTTPException(
                status_code=429,
                detail=f"登录尝试过于频繁，请 {wait} 秒后再试",
                headers={"Retry-After": str(wait)},
            )
        if until and until <= now:
            _blocked_until.pop(ip, None)


def record_login_failure(request: Request) -> None:
    """Call AFTER a failed credential check. Blocks the IP if cap is reached."""
    ip = _client_ip(request)
    now = time.monotonic()
    cutoff = now - LOGIN_WINDOW_SEC
    with _lock:
        q = _failures.setdefault(ip, deque())
        q.append(now)
        # Trim expired entries from the left
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= LOGIN_MAX_ATTEMPTS:
            _blocked_until[ip] = now + LOGIN_BLOCK_SEC
            q.clear()


def record_login_success(request: Request) -> None:
    """Call AFTER a successful login. Clears throttling state for this IP."""
    ip = _client_ip(request)
    with _lock:
        _failures.pop(ip, None)
        _blocked_until.pop(ip, None)
