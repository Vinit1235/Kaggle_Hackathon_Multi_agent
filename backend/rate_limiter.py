"""
rate_limiter.py: Rate Limit Guard for free-tier survival.
Tracks requests per minute (RPM) using Redis memX fallback to in-memory dict.
If limits are hit, tasks will be queued and delayed.
"""

from __future__ import annotations

import time
import asyncio
from loguru import logger
from memory import memx

class RateLimitGuard:
    def __init__(self, max_rpm: int = 15):
        """Free-tier limits (e.g. Vertex AI or Proxy limits). Default 15 RPM."""
        self.max_rpm = max_rpm

    async def acquire_token(self) -> None:
        """
        Wait if the rate limit has been exceeded.
        Uses the shared memX state manager to coordinate across workers.
        """
        while True:
            current_minute = int(time.time() / 60)
            key = f"rate_limit:rpm:{current_minute}"
            
            # Use memX to track cross-process if connected
            count_val = await memx.read_state(key)
            count = int(count_val) if count_val else 0

            if count < self.max_rpm:
                # Increment count
                await memx.update_state(key, count + 1)
                return
            
            # Limit reached, wait for next minute window
            logger.warning(f"Rate limit hit ({self.max_rpm} RPM). Throttling execution...")
            await asyncio.sleep(5.0)

rate_limiter = RateLimitGuard()
