import asyncio
import time
import traceback

from config.logging_config import logger


class ClientSessionManager:
    def __init__(self, client):
        self.client = client
        self.last_refresh_time = time.time()
        self.refresh_attempts = 0
        self.max_refresh_attempts = 5
        self.min_refresh_interval = 60


    async def maybe_refresh_session(self, force: bool = False) -> bool:
        current_time = time.time()
        
        if not force and (current_time - self.last_refresh_time) < self.min_refresh_interval:
            return False
        
        if self.refresh_attempts >= self.max_refresh_attempts:
            logger.warning(
                f"Достигнут лимит попыток обновления сессии ({self.max_refresh_attempts}). "
                "Сброс счетчика и ожидание перед следующей попыткой."
            )
            self.refresh_attempts = 0
            await asyncio.sleep(self.min_refresh_interval)
        
        self.refresh_attempts += 1
        self.last_refresh_time = current_time
        
        try:
            logger.info("Обновление сессии клиента...")
            
            new_csrf_token = await self.client._get_csrf_token_from_api()
            
            if new_csrf_token:
                self.client._csrf_token = new_csrf_token
                self.client._client.update_headers({"x-csrf-token": new_csrf_token})
                logger.info("CSRF токен успешно обновлен")
            
            is_auth = await self.client._check_authentication()
            
            if not is_auth:
                logger.warning("Сессия устарела, выполняем повторную авторизацию")
                login_success = await self.client._login()
                
                if login_success:
                    logger.success("Повторная авторизация успешна")
                    self.refresh_attempts = 0
                    return True
                else:
                    logger.error("Не удалось выполнить повторную авторизацию")
                    return False
            
            logger.info("Сессия клиента успешно обновлена")
            self.refresh_attempts = 0
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при обновлении сессии клиента: {str(e)}")
            logger.error(traceback.format_exc())
            return False