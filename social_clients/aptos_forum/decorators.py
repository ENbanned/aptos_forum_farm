import asyncio
import functools
from typing import Any, Awaitable, Callable, TypeVar

from config.logging_config import logger

T = TypeVar('T')


def require_client_initialized(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    @functools.wraps(func)
    async def wrapper(self, *args: Any, **kwargs: Any) -> T:
        if not self._client:
            logger.warning("Клиент не инициализирован, выполняем автоматический запуск")
            await self.start()
            
        if not self._client:
            raise RuntimeError("Не удалось инициализировать клиент")
            
        return await func(self, *args, **kwargs)
    return wrapper


def require_authentication(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    @functools.wraps(func)
    async def wrapper(self, *args: Any, **kwargs: Any) -> T:
        if not self._client:
            logger.warning("Клиент не инициализирован, выполняем автоматический запуск")
            await self.start()
            
        if not await self._ensure_authenticated():
            raise RuntimeError("Невозможно выполнить операцию: не удалось авторизоваться")
            
        return await func(self, *args, **kwargs)
    return wrapper


def require_csrf_token(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    @functools.wraps(func)
    async def wrapper(self, *args: Any, **kwargs: Any) -> T:
        if not await self._ensure_authenticated():
            raise RuntimeError("Невозможно получить CSRF токен: не удалось авторизоваться")
            
        if not self._csrf_token:
            logger.info("CSRF токен отсутствует, получаем новый")
            self._csrf_token = await self._get_csrf_token_from_api()
            
            if not self._csrf_token:
                raise RuntimeError("Не удалось получить CSRF токен")
                
            self._client.update_headers({"x-csrf-token": self._csrf_token})
            
        return await func(self, *args, **kwargs)
    return wrapper


def handle_api_errors(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    @functools.wraps(func)
    async def wrapper(self, *args: Any, **kwargs: Any) -> T:
        max_retries = 2
        retry_count = 0
        
        while retry_count <= max_retries:
            try:
                return await func(self, *args, **kwargs)
            except Exception as e:
                retry_count += 1
                logger.error(f"Ошибка при выполнении {func.__name__}: {str(e)}")
                
                if retry_count > max_retries:
                    raise
                    
                if "401" in str(e) or "403" in str(e) or "authentication" in str(e).lower():
                    logger.warning("Возможная проблема с авторизацией, пробуем переавторизоваться")
                    self._auth_cookie = None
                    self._csrf_token = None
                    
                    if not await self._ensure_authenticated():
                        raise RuntimeError("Не удалось выполнить повторную авторизацию")
                        
                    logger.info(f"Повторная авторизация успешна, повторяем {func.__name__}")
                else:
                    await asyncio.sleep(1)
                    
    return wrapper
