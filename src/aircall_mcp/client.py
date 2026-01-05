"""Aircall API client with rate limiting."""

import os
import asyncio
import time
from collections import deque
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()


class RateLimiter:
    """Token bucket rate limiter for Aircall API (60 req/min)."""

    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.window_seconds = 60
        self.request_times: deque = deque()
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Wait until a request slot is available."""
        async with self._lock:
            now = time.time()

            # Remove timestamps older than window
            while self.request_times and self.request_times[0] < now - self.window_seconds:
                self.request_times.popleft()

            # If at limit, wait until oldest request expires
            if len(self.request_times) >= self.requests_per_minute:
                wait_time = self.request_times[0] + self.window_seconds - now + 0.1
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    return await self.acquire()

            self.request_times.append(now)


class AircallAPIError(Exception):
    """Custom exception for Aircall API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class AircallClient:
    """Async client for Aircall API with built-in rate limiting."""

    def __init__(
        self,
        api_id: Optional[str] = None,
        api_token: Optional[str] = None,
        base_url: Optional[str] = None,
        rate_limit: Optional[int] = None,
        timeout: Optional[int] = None,
    ):
        self.api_id = api_id or os.environ.get("AIRCALL_API_ID")
        self.api_token = api_token or os.environ.get("AIRCALL_API_TOKEN")
        self.base_url = base_url or os.environ.get("AIRCALL_BASE_URL", "https://api.aircall.io/v1")
        self.timeout = timeout or int(os.environ.get("AIRCALL_TIMEOUT", "30"))

        rate_limit_val = rate_limit or int(os.environ.get("AIRCALL_RATE_LIMIT", "60"))
        self.rate_limiter = RateLimiter(rate_limit_val)

        if not self.api_id or not self.api_token:
            raise AircallAPIError(
                "Missing Aircall credentials. Set AIRCALL_API_ID and AIRCALL_API_TOKEN "
                "environment variables or pass them to the client."
            )

        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                auth=(self.api_id, self.api_token),
                timeout=self.timeout,
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request(self, method: str, endpoint: str, **kwargs) -> dict[str, Any]:
        """Make a rate-limited request to the Aircall API."""
        await self.rate_limiter.acquire()

        client = await self._get_client()
        try:
            response = await client.request(method, endpoint, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 401:
                raise AircallAPIError("Invalid Aircall API credentials", status)
            elif status == 403:
                raise AircallAPIError("Permission denied for this resource", status)
            elif status == 404:
                raise AircallAPIError("Resource not found", status)
            elif status == 429:
                raise AircallAPIError("Rate limit exceeded (60 req/min)", status)
            elif status >= 500:
                raise AircallAPIError("Aircall API temporarily unavailable", status)
            raise AircallAPIError(f"API request failed: {e.response.text}", status)
        except httpx.TimeoutException:
            raise AircallAPIError("Request timed out")
        except httpx.RequestError as e:
            raise AircallAPIError(f"Request failed: {str(e)}")

    # === Call Methods ===

    async def list_calls(
        self,
        page: int = 1,
        per_page: int = 20,
        order: str = "desc",
        direction: Optional[str] = None,
        from_timestamp: Optional[int] = None,
        to_timestamp: Optional[int] = None,
    ) -> dict[str, Any]:
        """List calls with pagination and filtering."""
        params = {
            "page": page,
            "per_page": per_page,
            "order": order,
        }
        if direction:
            params["direction"] = direction
        if from_timestamp:
            params["from"] = from_timestamp
        if to_timestamp:
            params["to"] = to_timestamp

        return await self._request("GET", "/calls", params=params)

    async def get_call(self, call_id: int) -> dict[str, Any]:
        """Get details for a specific call."""
        data = await self._request("GET", f"/calls/{call_id}")
        return data.get("call", data)

    # === Transcript Methods ===

    async def get_transcript(self, call_id: int) -> Optional[dict[str, Any]]:
        """Get transcript for a call. Returns None if not available."""
        try:
            data = await self._request("GET", f"/calls/{call_id}/transcription")
            return data.get("transcription", data)
        except AircallAPIError as e:
            if e.status_code == 404:
                return None
            raise

    # === Summary Methods ===

    async def get_summary(self, call_id: int) -> Optional[dict[str, Any]]:
        """Get AI summary for a call. Returns None if not available."""
        try:
            data = await self._request("GET", f"/calls/{call_id}/summary")
            return data.get("summary", data)
        except AircallAPIError as e:
            if e.status_code == 404:
                return None
            raise
