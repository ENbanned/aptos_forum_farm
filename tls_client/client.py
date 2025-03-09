import inspect
import logging
import warnings
from typing import Any, Dict, Optional, TypeVar

from curl_cffi.requests import AsyncSession, Response

from .config import (
    DEFAULT_BROWSER, 
    DEFAULT_DISABLE_SSL, 
    DEFAULT_HEADERS, 
    DEFAULT_TIMEOUT
)
from .decorators import log_request
from .exceptions import TLSClientError
from .types import HeadersType, ProxyType
from .fingerprint_randomizer import FingerprintRandomizer


T = TypeVar('T')
warnings.filterwarnings("ignore", module="curl_cffi")


class TLSClient:
    def __init__(
        self,
        proxy: ProxyType = None,
        headers: Optional[HeadersType] = None,
        browser_type: Any = None,
        timeout: float = DEFAULT_TIMEOUT,
        disable_ssl: bool = DEFAULT_DISABLE_SSL,
        randomize_fingerprint: bool = True
    ) -> None:
        self._proxy = proxy
        self._timeout = timeout
        self._randomize_fingerprint = randomize_fingerprint
        
        if randomize_fingerprint:
            random_headers, random_browser_type = FingerprintRandomizer.get_random_fingerprint()
            init_headers = dict(random_headers)
            browser_type = browser_type or random_browser_type
        else:
            # Используем DEFAULT_HEADERS из импорта, если не указано иное
            from .config import DEFAULT_HEADERS, DEFAULT_BROWSER
            init_headers = dict(DEFAULT_HEADERS)
            browser_type = browser_type or DEFAULT_BROWSER
            
        if headers:
            init_headers.update(headers)

        self.logger = logging.getLogger(__name__)
        self.logger.debug(f"Инициализация TLS клиента с User-Agent: {init_headers.get('User-Agent', 'не указан')}")

        self._session = AsyncSession(
            impersonate=browser_type,
            headers=init_headers,
            proxies={"http": proxy, "https": proxy} if proxy else {},
            verify=not disable_ssl,
        )
        
        
    async def refresh_fingerprint(self) -> None:
        if not self._randomize_fingerprint:
            self.logger.debug("Обновление отпечатка пропущено, так как рандомизация отключена")
            return
        
        try:
            random_headers, random_browser_type = FingerprintRandomizer.get_random_fingerprint()
            
            self._session.headers.clear()
            self._session.headers.update(random_headers)
            
            old_session = self._session
            
            try:
                self._session = AsyncSession(
                    impersonate=random_browser_type,
                    headers=dict(self._session.headers),
                    proxies={"http": self._proxy, "https": self._proxy} if self._proxy else {},
                    verify=not DEFAULT_DISABLE_SSL,
                )
                
                if inspect.iscoroutinefunction(old_session.close):
                    await old_session.close()
                else:
                    old_session.close()
                    
                self.logger.debug(f"Отпечаток обновлен, новый User-Agent: {self._session.headers.get('User-Agent')}")
            except Exception as e:
                self._session = old_session
                self.logger.error(f"Ошибка при обновлении сессии: {str(e)}")
                
        except Exception as e:
            self.logger.error(f"Ошибка при обновлении отпечатка: {str(e)}")


    async def __aenter__(self) -> 'TLSClient':
        return self


    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()


    async def close(self) -> None:
        if inspect.iscoroutinefunction(self._session.close):
            await self._session.close()
        else:
            self._session.close()


    def update_headers(self, new_headers: Dict[str, str]) -> None:
        self._session.headers.update(new_headers)


    @property
    def cookies(self) -> Any:
        return self._session.cookies


    @log_request()
    async def request(self, method: str, url: str, *, headers: Optional[Dict[str, str]] = None, **kwargs: Any) -> Response:
        method_lower = method.lower()

        if "timeout" not in kwargs:
            kwargs["timeout"] = self._timeout
            
        if headers:
            request_headers = dict(self._session.headers)
            request_headers.update(headers)
            kwargs["headers"] = request_headers

        try:
            match method_lower:
                case "get":
                    resp = await self._session.get(url, **kwargs)
                case "post":
                    resp = await self._session.post(url, **kwargs)
                case "put":
                    resp = await self._session.put(url, **kwargs)
                case "delete":
                    resp = await self._session.delete(url, **kwargs)
                case _:
                    raise TLSClientError(f"Unsupported method: {method}")
            return resp
        except Exception as e:
            if isinstance(e, TLSClientError):
                raise
            raise TLSClientError(f"Request error: {str(e)}") from e


    async def get(self, url: str, **kwargs: Any) -> Response:
        return await self.request("GET", url, **kwargs)


    async def post(self, url: str, **kwargs: Any) -> Response:
        return await self.request("POST", url, **kwargs)


    async def put(self, url: str, **kwargs: Any) -> Response:
        return await self.request("PUT", url, **kwargs)


    async def delete(self, url: str, **kwargs: Any) -> Response:
        return await self.request("DELETE", url, **kwargs)
    
    
    