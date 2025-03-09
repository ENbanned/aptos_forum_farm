import asyncio
import hashlib
import random
import re
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

from config.logging_config import logger
from tls_client import TLSClient

from .decorators import (
    handle_api_errors,
    require_authentication,
    require_client_initialized,
    require_csrf_token
)
from .models import AccountCredentials, PostData, TopicData
from .utils import extract_text_from_html, is_success_response


class AptosForumClient:
    def __init__(
        self, 
        username: str,
        password: str,
        proxy: Optional[str] = None,
    ) -> None:
        self.base_url = "https://forum.aptosfoundation.org"
        
        self._credentials = AccountCredentials(username=username, password=password)
        self._proxy = proxy
        self._client: Optional[TLSClient] = None
        
        self._auth_cookie: Optional[str] = None
        self._csrf_token: Optional[str] = None
        self._username: Optional[str] = None
        
        self._ip_timezone_cache: Dict[str, str] = {}
    
    
    async def __aenter__(self) -> 'AptosForumClient':
        await self.start()
        return self


    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()


    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
    
    # -------------------------------------------------------------------------
    # Методы инициализации и авторизации
    # -------------------------------------------------------------------------
    
    async def start(self) -> bool:
        max_attempts = 3
        
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Попытка #{attempt} инициализации клиента для {self._credentials.username}" + 
                        (f" с прокси {self._proxy}" if self._proxy else " без прокси"))
                
                self._client = TLSClient(
                    proxy=self._proxy, 
                    disable_ssl=True,
                    randomize_fingerprint=True,
                    headers=self._get_default_headers()
                )
                
                if not await self._ensure_authenticated():
                    logger.error(f"Не удалось выполнить авторизацию для {self._credentials.username}")
                    if attempt < max_attempts:
                        await asyncio.sleep(2)
                        continue
                    return False
                
                if not self._csrf_token:
                    self._csrf_token = await self._get_csrf_token_from_api()
                    if self._csrf_token:
                        self._client.update_headers({"x-csrf-token": self._csrf_token})
                    else:
                        logger.error("Не удалось получить CSRF токен")
                        if attempt < max_attempts:
                            await asyncio.sleep(2)
                            continue
                        return False
                
                logger.success(f"Успешная инициализация клиента для {self._credentials.username}")
                return True
                
            except Exception as e:
                logger.error(f"Ошибка при инициализации клиента (попытка {attempt}/{max_attempts}): {str(e)}")
                if attempt < max_attempts:
                    await asyncio.sleep(2)
                else:
                    return False
        
        return False
    
    
    async def _ensure_authenticated(self) -> bool:
        is_auth = await self._check_authentication()
        
        if is_auth:
            return True
            
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            logger.debug(f"Попытка входа {attempt}/{max_attempts}")
            login_success = await self._login()
            if login_success:
                if await self._check_authentication():
                    return True
                else:
                    logger.warning(f"Вход выполнен, но проверка авторизации не пройдена (попытка {attempt})")
            
            if attempt < max_attempts:
                await asyncio.sleep(2)
        
        logger.error("Все попытки авторизации не удались")
        return False
    
    
    async def _check_authentication(self) -> bool:
        if not self._client:
            return False
            
        try:
            response = await self._client.get(f"{self.base_url}/session/current.json")
            
            if response.status_code == 200:
                data = response.json()
                user = data.get("current_user")
                if user:
                    self._username = user.get("username")
                    logger.info(f"Авторизация активна: {self._username}")
                    
                    if not self._csrf_token:
                        self._csrf_token = await self._get_csrf_token_from_api()
                        if self._csrf_token:
                            self._client.update_headers({"x-csrf-token": self._csrf_token})
                    
                    return True
                    
            if response.status_code != 200:
                logger.debug(f"Ошибка проверки авторизации, статус: {response.status_code}")
            else:
                logger.debug(f"Ответ не содержит данных пользователя: {response.text[:100]}...")
            
            return False
            
        except Exception as e:
            logger.error(f"Ошибка при проверке статуса авторизации: {e}")
            return False
    
    
    async def _login(self) -> bool:
        if not self._client:
            logger.error("Клиент не инициализирован")
            return False
            
        try:
            csrf_token = await self._get_csrf_token_from_api()
            
            if not csrf_token:
                logger.error("Не удалось получить CSRF токен для логина")
                return False
            
            self._client.update_headers({"x-csrf-token": csrf_token})
            
            timezone = await self._get_timezone_for_current_ip()
            
            login_data = {
                "login": self._credentials.username,
                "password": self._credentials.password,
                "second_factor_method": "1",
                "timezone": timezone
            }
            
            response = await self._client.post(
                f"{self.base_url}/session", 
                data=login_data
            )
            
            if response.status_code == 200:
                self._csrf_token = csrf_token
                
                if await self._check_authentication():
                    logger.success(f"Успешная авторизация: {self._username}")
                    
                    return True
                else:
                    logger.error("Авторизация не удалась несмотря на успешный ответ")
                    return False
            else:
                logger.error(f"Ошибка авторизации: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при выполнении авторизации: {e}")
            return False
        
    
    async def _get_csrf_token_from_api(self) -> Optional[str]:
        if not self._client:
            logger.error("Клиент не инициализирован")
            return None
            
        try:
            response = await self._client.get(f"{self.base_url}/session/csrf.json")
            data = response.json()
            csrf_token = data.get("csrf")
            
            if csrf_token:
                logger.debug(f"Получен CSRF токен: {csrf_token[:10]}...")
                return csrf_token
                
            logger.error("CSRF токен не найден в ответе")
            return None
            
        except Exception as e:
            logger.error(f"Ошибка при получении CSRF токена: {e}")
            return None
    
    async def _get_timezone_for_current_ip(self) -> str:
        try:
            ip_address = "0.0.0.0"
            if self._proxy:
                ip_match = re.search(r'@([^:]+):', self._proxy)
                if ip_match:
                    ip_address = ip_match.group(1)
            
            if ip_address in self._ip_timezone_cache:
                return self._ip_timezone_cache[ip_address]
            
            if self._client:
                response = await self._client.get(f"http://ip-api.com/json/{ip_address}")
                data = response.json()
                
                if data.get("status") == "success" and "timezone" in data:
                    timezone = data["timezone"]
                    # Сохраняем в кэш
                    self._ip_timezone_cache[ip_address] = timezone
                    return timezone
                    
            return "UTC"
            
        except Exception as e:
            logger.error(f"Ошибка при получении таймзоны: {e}")
            return "UTC"
    
    
    def _get_default_headers(self) -> Dict[str, str]:
        return {
            'accept': '*/*',
            'accept-language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'discourse-logged-in': 'true',
            'discourse-present': 'true',
            'origin': self.base_url,
            'priority': 'u=1, i',
            'sec-ch-ua': '"Chromium";v="134", "Not:A-Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
            'x-requested-with': 'XMLHttpRequest',
        }
    
    # -------------------------------------------------------------------------
    # Методы для работы с темами и постами
    # -------------------------------------------------------------------------
    
    @require_client_initialized
    @handle_api_errors
    async def get_latest_topics(self, page: int = 0, limit: int = 30) -> List[TopicData]:
        try:
            url = f"{self.base_url}/latest.json?no_definitions=true&page={page}"
            response = await self._client.get(url)
            data = response.json()
            
            topics_data = data.get('topic_list', {}).get('topics', [])
            
            topics = []
            for topic_data in topics_data[:limit]:
                topic = TopicData(
                    id=topic_data.get('id'),
                    title=topic_data.get('title'),
                    fancy_title=topic_data.get('fancy_title'),
                    slug=topic_data.get('slug'),
                    posts_count=topic_data.get('posts_count'),
                    created_at=topic_data.get('created_at'),
                    last_posted_at=topic_data.get('last_posted_at'),
                    category_id=topic_data.get('category_id'),
                )
                topics.append(topic)
            
            return topics
        except Exception as e:
            logger.error(f"Ошибка при получении списка тем: {e}")
            return []
    
    
    @require_client_initialized
    @handle_api_errors
    async def get_random_topic(self, min_posts: int = 1, pages: int = 3) -> Optional[TopicData]:
        all_topics = []
        
        for page in range(pages):
            topics = await self.get_latest_topics(page=page)
            if not topics:
                break
            all_topics.extend(topics)
        
        suitable_topics = [t for t in all_topics if t.posts_count and t.posts_count >= min_posts]
        
        if not suitable_topics:
            logger.warning(f"Не найдено тем с минимальным количеством постов: {min_posts}")
            return None
        
        return random.choice(suitable_topics)
    
    
    @require_client_initialized
    @handle_api_errors
    async def get_topic_details(self, topic_id: int) -> Tuple[Optional[TopicData], List[PostData]]:
        try:
            url = f"{self.base_url}/t/{topic_id}.json"
            response = await self._client.get(url)
            data = response.json()
            
            topic = TopicData(
                id=data.get('id'),
                title=data.get('title'),
                fancy_title=data.get('fancy_title'),
                slug=data.get('slug'),
                posts_count=data.get('posts_count'),
                created_at=data.get('created_at'),
                last_posted_at=data.get('last_posted_at'),
                category_id=data.get('category_id'),
            )
            
            posts_data = data.get('post_stream', {}).get('posts', [])
            posts = []
            
            for post_data in posts_data:
                cooked_html = post_data.get('cooked', '')
                
                post = PostData(
                    id=post_data.get('id'),
                    user_id=post_data.get('user_id'),
                    username=post_data.get('username'),
                    post_number=post_data.get('post_number'),
                    cooked=cooked_html,
                    created_at=post_data.get('created_at'),
                    topic_id=topic.id,
                    actions_summary=post_data.get('actions_summary', []),
                    raw=extract_text_from_html(cooked_html)
                )
                posts.append(post)
            
            return topic, posts
        except Exception as e:
            logger.error(f"Ошибка при получении деталей темы {topic_id}: {e}")
            return None, []
    
    # -------------------------------------------------------------------------
    # Методы для взаимодействия с постами
    # -------------------------------------------------------------------------
    
    @require_authentication
    @require_csrf_token
    @handle_api_errors
    async def like_post(self, post_id: int) -> bool:
        try:
            url = f"{self.base_url}/post_actions"
            data = {
                'id': str(post_id),
                'post_action_type_id': '2',
                'flag_topic': 'false',
            }
            
            response = await self._client.post(url, data=data)
            
            if response.status_code == 200:
                result = response.json()
                success = is_success_response(result, "like")
                
                if success:
                    logger.success(f"Лайк успешно поставлен на пост {post_id}")
                else:
                    logger.warning(f"Возможно, лайк уже был поставлен на пост {post_id}")
                
                return True
            else:
                logger.error(f"Ошибка при постановке лайка: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Ошибка при постановке лайка на пост {post_id}: {e}")
            return False
    
    
    @require_authentication
    @require_csrf_token
    @handle_api_errors
    async def post_comment(self, topic_id: int, raw_content: str, category_id: int = 4) -> bool:
        try:
            url = f"{self.base_url}/posts"
            data = {
                'raw': raw_content,
                'unlist_topic': 'false',
                'category': str(category_id),
                'topic_id': str(topic_id),
                'is_warning': 'false',
                'archetype': 'regular',
                'typing_duration_msecs': str(random.randint(1800, 4500)),
                'composer_open_duration_msecs': str(random.randint(5000, 15000)),
                'featured_link': '',
                'shared_draft': 'false',
                'draft_key': f'topic_{topic_id}',
                'nested_post': 'true',
            }
            
            response = await self._client.post(url, data=data)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    logger.success(f"Комментарий успешно отправлен в тему {topic_id}")
                    return True
                else:
                    logger.warning(f"Ошибка при отправке комментария: {result}")
                    return False
            else:
                logger.error(f"Ошибка при отправке комментария: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Ошибка при отправке комментария: {e}")
            return False
    
    # -------------------------------------------------------------------------
    # Высокоуровневые методы для выполнения действий
    # -------------------------------------------------------------------------
    
    @require_authentication
    @handle_api_errors
    async def like_random_post(self) -> bool:
        topic = await self.get_random_topic(min_posts=2)
        if not topic:
            logger.error("Не удалось получить случайную тему")
            return False
        
        logger.info(f"Выбрана тема: {topic.title} (ID: {topic.id})")
        
        _, posts = await self.get_topic_details(topic.id)
        if not posts:
            logger.error(f"Не удалось получить посты для темы {topic.id}")
            return False
        
        random_post = random.choice(posts)
        logger.info(f"Выбран пост №{random_post.post_number} от {random_post.username}")
        
        success = await self.like_post(random_post.id)
        return success
    
    
    @require_authentication
    @handle_api_errors
    async def comment_on_random_topic(self, min_posts: int = 3, comment_generator = None) -> bool:
        if comment_generator is None:
            logger.error("Генератор комментариев не предоставлен")
            return False
        
        topic = await self.get_random_topic(min_posts=min_posts)
        if not topic:
            logger.error(f"Не найдено тем с минимум {min_posts} постами")
            return False
        
        logger.info(f"Выбрана тема для комментирования: {topic.title} (ID: {topic.id})")
        
        _, posts = await self.get_topic_details(topic.id)
        if not posts:
            logger.error(f"Не удалось получить посты для темы {topic.id}")
            return False
        
        main_post = next((p for p in posts if p.post_number == 1), None)
        if not main_post:
            logger.error(f"Не удалось найти основной пост в теме {topic.id}")
            return False
        
        comments_text = [p.raw for p in posts if p.post_number > 1]
        
        logger.info(f"Генерация комментария для темы '{topic.title}'")
        comment_text = await comment_generator.generate_comment(
            topic_title=topic.title,
            main_post_text=main_post.raw,
            comments_text=comments_text
        )
        
        logger.info(f"Сгенерирован комментарий: {comment_text}")
        
        success = await self.post_comment(
            topic_id=topic.id,
            raw_content=comment_text,
            category_id=topic.category_id or 4
        )
        
        return success
    
    
    @require_authentication
    @handle_api_errors
    async def simulate_online_presence(self, duration_minutes: int = 30) -> None:
        logger.info(f"Начинаем симуляцию онлайн-активности на {duration_minutes} минут")
        
        end_time = time.time() + duration_minutes * 60
        poll_count = 0
        
        topic = await self.get_random_topic(min_posts=2)
        if not topic:
            logger.error("Не удалось получить случайную тему для онлайн-присутствия")
            return
        
        logger.info(f"Выбрана тема для симуляции онлайн: {topic.title} (ID: {topic.id})")
        
        initial_response = await self._client.get(f"{self.base_url}/t/{topic.id}")
        
        username_hash = hashlib.md5(str(self._username).encode()).hexdigest()
        message_bus_id = username_hash[:32]
        logger.info(f"Сгенерирован message-bus ID: {message_bus_id}")
        
        try:
            seq_num = 1
            last_timing_time = 0
            
            while time.time() < end_time:
                if poll_count % 10 == 0 and poll_count > 0:
                    if not await self._check_authentication():
                        logger.warning("Потеряна авторизация, выполняем повторный вход")
                        if not await self._ensure_authenticated():
                            logger.error("Не удалось восстановить авторизацию, прерываем симуляцию")
                            return
                
                poll_result = await self._send_poll_request(message_bus_id, seq_num, topic.id)
                logger.info(f"Poll request #{seq_num}, статус: {poll_result}")
                seq_num += 1
                poll_count += 1
                
                current_time = time.time()
                if current_time - last_timing_time > random.uniform(30, 50):
                    post_numbers = range(1, min(5, topic.posts_count or 5) + 1)
                    timings = {str(i): random.randint(1000, 15000) for i in post_numbers}
                    topic_time = sum(timings.values())
                    
                    timing_result = await self._send_timing_data(topic.id, timings, topic_time)
                    logger.info(f"Timing data отправлен, статус: {timing_result}, время: {topic_time}ms")
                    last_timing_time = current_time
                
                await asyncio.sleep(random.uniform(20, 40))
            
            logger.success(f"Симуляция онлайн-присутствия завершена. Отправлено {poll_count} запросов.")
            
        except Exception as e:
            logger.error(f"Ошибка при симуляции онлайн-присутствия: {e}")
    
    
    @require_authentication
    @handle_api_errors
    async def view_random_topics(self, count: int = 10) -> int:
        logger.info(f"Начинаем просмотр {count} случайных тем")
        
        viewed_count = 0
        for i in range(count):
            logger.info(f"Просмотр темы {i+1} из {count}")
            
            topics = await self.get_latest_topics(page=random.randint(0, 5))
            if not topics:
                logger.warning("Не удалось получить список тем")
                continue
            
            topic = random.choice(topics)
            logger.info(f"Выбрана тема: {topic.title} (ID: {topic.id})")
            
            success = await self._view_topic(topic.id)
            if success:
                viewed_count += 1
            
            await asyncio.sleep(random.uniform(5, 15))
        
        logger.success(f"Просмотрено тем: {viewed_count} из {count}")
        return viewed_count


    @require_authentication
    @handle_api_errors
    async def view_random_posts(self, count: int = 20, posts_per_topic: int = 5) -> int:
        logger.info(f"Начинаем просмотр {count} случайных постов")
        
        viewed_posts_count = 0
        topics_needed = max(1, count // posts_per_topic)
        
        for i in range(topics_needed):
            if viewed_posts_count >= count:
                break
            
            topic = await self.get_random_topic(min_posts=posts_per_topic)
            if not topic:
                logger.warning(f"Не удалось найти тему с {posts_per_topic} постами")
                continue
            
            logger.info(f"Выбрана тема для просмотра постов: {topic.title} (ID: {topic.id})")
            
            _, posts = await self.get_topic_details(topic.id)
            if not posts or len(posts) <= 1:
                logger.warning(f"Не удалось получить посты для темы {topic.id}")
                continue
            
            posts_to_view = min(posts_per_topic, count - viewed_posts_count, len(posts) - 1)
            
            await self._view_topic(topic.id)
            
            for j in range(posts_to_view):
                post_idx = min(j + 1, len(posts) - 1)
                post = posts[post_idx]
                
                logger.info(f"Просмотр поста #{post.post_number} в теме {topic.id}")
                
                success = await self._view_post(topic.id, post.post_number)
                if success:
                    viewed_posts_count += 1
                
                await asyncio.sleep(random.uniform(3, 8))
            
            await asyncio.sleep(random.uniform(5, 15))
        
        logger.success(f"Просмотрено постов: {viewed_posts_count} из {count}")
        return viewed_posts_count
    
    # -------------------------------------------------------------------------
    # Вспомогательные методы
    # -------------------------------------------------------------------------
    
    async def get_user_statistics(self) -> dict:
        if not self._username:
            return {}
        
        url = f"{self.base_url}/u/{self._username}/summary.json"
        response = await self._client.get(url)
        return response.json()
    
    async def _send_poll_request(self, message_bus_id: str, seq_num: int, topic_id: int) -> bool:
        try:
            if not self._client:
                return False
                
            poll_url = f"{self.base_url}/message-bus/{message_bus_id}/poll"
            
            data = {
                '/latest': '7073',
                '/new': '719',
                '/unread': '2770',
                f'/unread/{self._username}': '0',
                '/delete': '0',
                '/recover': '0',
                '/destroy': '0',
                '/site/banner': '0',
                '/file-change': '0',
                f'/logout/{self._username}': '0',
                '/site/read-only': '0',
                f'/reviewable_counts/{self._username}': '0',
                f'/notification/{self._username}': '0',
                f'/user-drafts/{self._username}': '0',
                f'/do-not-disturb/{self._username}': '0',
                '/user-status': '0',
                '/categories': '1385',
                '/client_settings': '0',
                f'/notification-alert/{self._username}': '0',
                '/refresh_client': '0',
                '/global/asset-version': '1738',
                '/refresh-sidebar-sections': '0',
                f'/topic/{topic_id}': str(random.randint(20, 60)),
                f'/polls/{topic_id}': '0',
                f'/discourse-akismet/topic-deleted/{topic_id}': '0',
                f'/presence/discourse-presence/reply/{topic_id}': '0',
                '__seq': str(seq_num)
            }
            
            form_data = '&'.join([f"{quote(key)}={quote(value)}" for key, value in data.items()])
            
            headers = {
                'accept': 'text/plain, */*; q=0.01',
                'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'discourse-present': 'true',
                'x-silence-logger': 'true'
            }
            
            response = await self._client.post(poll_url, data=form_data, headers=headers)
            logger.debug(f"_send_poll_request - статус: {response.status_code}")
            
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Ошибка при отправке poll-запроса: {e}")
            return False


    async def _send_timing_data(self, topic_id: int, timings: Dict[str, int], topic_time: int) -> bool:
        try:
            if not self._client:
                return False
                
            url = f"{self.base_url}/topics/timings"
            
            data = {}
            for post_num, time_ms in timings.items():
                data[f'timings[{post_num}]'] = str(time_ms)
            
            data['topic_time'] = str(topic_time)
            data['topic_id'] = str(topic_id)
            
            headers = {
                'accept': '*/*',
                'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'discourse-background': 'true',
                'discourse-logged-in': 'true',
                'x-silence-logger': 'true'
            }
            
            response = await self._client.post(url, data=data, headers=headers)
            logger.debug(f"_send_timing_data - статус: {response.status_code}")
            
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Ошибка при отправке данных о времени просмотра: {e}")
            return False


    async def _view_topic(self, topic_id: int) -> bool:
        try:
            if not self._client:
                return False
                
            url = f"{self.base_url}/t/{topic_id}"
            response = await self._client.get(url)
            
            if response.status_code == 200:
                timings = {str(i): random.randint(1000, 5000) for i in range(1, 3)}
                topic_time = sum(timings.values())
                await self._send_timing_data(topic_id, timings, topic_time)
                logger.debug(f"Тема {topic_id} успешно просмотрена")
                return True
            else:
                logger.warning(f"Ошибка при просмотре темы {topic_id}: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Ошибка при просмотре темы {topic_id}: {e}")
            return False


    async def _view_post(self, topic_id: int, post_number: int) -> bool:
        try:
            if not self._client:
                return False
                
            url = f"{self.base_url}/t/{topic_id}/{post_number}"
            response = await self._client.get(url)
            
            if response.status_code == 200:
                timings = {str(post_number): random.randint(3000, 8000)}
                topic_time = sum(timings.values())
                await self._send_timing_data(topic_id, timings, topic_time)
                logger.debug(f"Пост #{post_number} в теме {topic_id} успешно просмотрен")
                return True
            else:
                logger.warning(f"Ошибка при просмотре поста #{post_number} в теме {topic_id}: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Ошибка при просмотре поста #{post_number} в теме {topic_id}: {e}")
            return False
        