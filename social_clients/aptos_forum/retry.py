import asyncio
import functools
import random
import traceback
from typing import Any, Awaitable, Callable, TypeVar

from config.logging_config import logger

T = TypeVar('T')


class RetryableRequest:
    def __init__(
        self, 
        max_retries: int = 3, 
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        retry_on_status_codes: tuple = (429, 500, 502, 503, 504)
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.retry_on_status_codes = retry_on_status_codes
    
    def __call__(self, func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception = None
            
            for attempt in range(1, self.max_retries + 1):
                try:
                    if 'timeout' not in kwargs and func.__name__ != 'request':
                        if 'poll' in func.__name__.lower():
                            kwargs['timeout'] = 45.0
                        else:
                            kwargs['timeout'] = 30.0
                    
                    result = await func(*args, **kwargs)
                    
                    if hasattr(result, 'status_code') and result.status_code in self.retry_on_status_codes:
                        logger.warning(
                            f"Получен статус {result.status_code} при вызове {func.__name__}. "
                            f"Повторная попытка {attempt}/{self.max_retries}."
                        )
                        
                        # Экспоненциальная задержка с джиттером
                        delay = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
                        delay = delay * (0.8 + 0.4 * random.random())
                        
                        await asyncio.sleep(delay)
                        continue
                    
                    return result
                    
                except Exception as e:
                    last_exception = e
                    
                    error_str = str(e)
                    
                    retry_exception = any(
                        err_type in error_str.lower() for err_type in 
                        ["timeout", "connection", "reset", "refused", "eof", "curl"]
                    )
                    
                    if not retry_exception and attempt == self.max_retries:
                        logger.error(f"Неповторяемая ошибка при вызове {func.__name__}: {error_str}")
                        raise
                    
                    logger.warning(
                        f"Ошибка при вызове {func.__name__}: {error_str}. "
                        f"Повторная попытка {attempt}/{self.max_retries}."
                    )
                    
                    delay = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
                    delay = delay * (0.8 + 0.4 * random.random())  # джиттер ±20%
                    
                    await asyncio.sleep(delay)
            
            if last_exception:
                raise last_exception
            
            return None
        
        return wrapper