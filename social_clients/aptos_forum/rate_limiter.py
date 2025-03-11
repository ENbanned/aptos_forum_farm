import asyncio
import time
from typing import List

from config.logging_config import logger


class RateLimiter:
    def __init__(
        self,
        requests_per_minute: int = 30,
        burst_limit: int = 10,
        burst_period: float = 10.0 
    ):
        self.requests_per_minute = requests_per_minute
        self.burst_limit = burst_limit
        self.burst_period = burst_period
        
        self.request_timestamps: List[float] = []
        self.burst_count = 0
        self.last_burst_reset = time.time()
    
    
    async def wait_if_needed(self):
        current_time = time.time()
        
        minute_ago = current_time - 60.0
        self.request_timestamps = [ts for ts in self.request_timestamps if ts > minute_ago]
        
        if current_time - self.last_burst_reset > self.burst_period:
            self.burst_count = 0
            self.last_burst_reset = current_time
        
        if self.burst_count >= self.burst_limit:
            wait_time = self.last_burst_reset + self.burst_period - current_time
            if wait_time > 0:
                logger.debug(f"Rate limiter: Ожидание {wait_time:.2f}s из-за превышения лимита burst")
                await asyncio.sleep(wait_time)
                self.burst_count = 0
                self.last_burst_reset = time.time()
        
        if len(self.request_timestamps) >= self.requests_per_minute:
            oldest = self.request_timestamps[0]
            wait_time = oldest + 60.0 - current_time
            if wait_time > 0:
                logger.debug(f"Rate limiter: Ожидание {wait_time:.2f}s из-за превышения лимита RPM")
                await asyncio.sleep(wait_time)
                current_time = time.time()
        
        self.request_timestamps.append(current_time)
        self.burst_count += 1
        