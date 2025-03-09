import asyncio
import csv
import datetime
import os
import random
from typing import Dict, List, Optional, Tuple

from config.logging_config import logger
from database.manager import DatabaseManager
from database.repositories.account_repository import AccountRepository
from social_clients.aptos_forum.ai_generator import create_comment_generator
from social_clients.aptos_forum.client import AptosForumClient


class AccountService:    
    def __init__(self, db_manager: DatabaseManager, openai_api_key: str = "", config = None):
        self.db_manager = db_manager
        self.openai_api_key = openai_api_key
        self.config = config
        
        self.openai_model = "gpt-3.5-turbo"
        if self.config:
            try:
                model = self.config.get("openai", "model")
                if model:
                    self.openai_model = model
                    logger.info(f"Используется модель OpenAI из конфигурации: {self.openai_model}")
            except Exception as e:
                logger.error(f"Ошибка при загрузке модели OpenAI из конфигурации: {str(e)}")
    
    
    def get_active_accounts(self) -> List[Dict]:
        with self.db_manager.session_scope() as session:
            repo = AccountRepository(session)
            accounts = repo.get_active_accounts()
            
            return [
                {
                    "id": acc.id,
                    "username": acc.username,
                    "trust_level": acc.trust_level or 0,
                    "is_active": acc.is_active,
                    "current_day": acc.current_day,
                    "total_days": len(acc.activity_plan.get('days', {})) if acc.activity_plan else 0,
                    "last_login": acc.last_login.strftime("%Y-%m-%d %H:%M:%S") if acc.last_login else None
                }
                for acc in accounts
            ]
    
    
    def create_accounts_csv_template(self, path: str) -> bool:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            
            with open(path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['login', 'password', 'proxy_host', 'proxy_port', 'proxy_username', 'proxy_password', 'proxy_type'])
                writer.writerow(['example@mail.com', 'password123', '127.0.0.1', '8080', 'proxyuser', 'proxypass', 'http'])
            
            logger.info(f"Создан шаблон CSV для импорта аккаунтов: {path}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при создании шаблона CSV: {str(e)}")
            return False
    
    
    def import_accounts_from_csv(self, path: str) -> Tuple[int, int, int]:
        if not os.path.exists(path):
            logger.error(f"Файл не найден: {path}")
            return 0, 0, 0
        
        added = 0
        updated = 0
        errors = 0
        
        try:
            with open(path, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.reader(csvfile)
                headers = next(reader)
                
                is_new_format = len(headers) >= 4 and 'login' in headers[0].lower() and 'password' in headers[1].lower()
                
                with self.db_manager.session_scope() as session:
                    repo = AccountRepository(session)
                    
                    all_accounts = {}
                    for acc in repo.get_all():
                        all_accounts[acc.username.lower()] = acc
                    
                    for row_idx, row in enumerate(reader, start=2):
                        try:
                            if not row or (len(row) < 2 and is_new_format) or (len(row) < 1 and not is_new_format):
                                error_msg = f"Строка {row_idx}: Недостаточно столбцов"
                                logger.error(error_msg)
                                errors += 1
                                continue
                            
                            if is_new_format:
                                username = row[0].strip()
                                password = row[1].strip()
                                
                                proxy = None
                                if len(row) >= 4 and row[2].strip() and row[3].strip():
                                    proxy_host = row[2].strip()
                                    proxy_port = row[3].strip()
                                    proxy_user = row[4].strip() if len(row) > 4 and row[4].strip() else ""
                                    proxy_pass = row[5].strip() if len(row) > 5 and row[5].strip() else ""
                                    proxy_type = row[6].strip() if len(row) > 6 and row[6].strip() else "http"
                                    
                                    if proxy_user and proxy_pass:
                                        if proxy_type.lower() == "socks5":
                                            proxy = f"socks5://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"
                                        else:
                                            proxy = f"{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"
                                    else:
                                        if proxy_type.lower() == "socks5":
                                            proxy = f"socks5://{proxy_host}:{proxy_port}"
                                        else:
                                            proxy = f"{proxy_host}:{proxy_port}"
                            else:
                                login_password = row[0].strip()
                                if ':' not in login_password:
                                    error_msg = f"Строка {row_idx}: Неверный формат логина/пароля '{login_password}'"
                                    logger.error(error_msg)
                                    errors += 1
                                    continue
                                
                                username, password = login_password.split(':', 1)
                                
                                proxy = None
                                if len(row) > 1 and row[1].strip():
                                    proxy = row[1].strip()
                            
                            username_lower = username.lower()
                            account = all_accounts.get(username_lower)
                            
                            if account:
                                account.password = password
                                account.proxy = proxy
                                account.is_active = True
                                repo.update(account)
                                updated += 1
                                logger.info(f"Обновлен аккаунт: {username}")
                            else:
                                account = repo.create(username, password, proxy)
                                repo.generate_activity_plan(account.id)
                                all_accounts[username_lower] = account
                                added += 1
                                logger.info(f"Создан аккаунт: {username}")
                        except Exception as e:
                            error_msg = f"Строка {row_idx}: Ошибка при импорте аккаунта: {str(e)}"
                            logger.error(error_msg)
                            errors += 1
                
                return added, updated, errors
        except Exception as e:
            error_msg = f"Критическая ошибка при импорте аккаунтов: {str(e)}"
            logger.error(error_msg)
            return added, updated, errors + 1
    
    
    def generate_plans_for_all_accounts_without_plans(self) -> Dict[str, int]:
        results = {"total": 0, "success": 0, "failed": 0}
        
        with self.db_manager.session_scope() as session:
            repo = AccountRepository(session)
            accounts = repo.get_accounts_without_plans()
            
            results["total"] = len(accounts)
            
            for account in accounts:
                try:
                    success = repo.generate_activity_plan(account.id)
                    if success:
                        results["success"] += 1
                    else:
                        results["failed"] += 1
                except Exception as e:
                    logger.error(f"Ошибка при создании плана для аккаунта {account.username}: {str(e)}")
                    results["failed"] += 1
        
        logger.info(f"Созданы планы для {results['success']} из {results['total']} аккаунтов")
        return results
    
    
    async def execute_daily_activities(self) -> Dict:
        results = {}
        
        with self.db_manager.session_scope() as session:
            repo = AccountRepository(session)
            active_accounts = repo.get_active_accounts()
            
            logger.info(f"Запуск ежедневных активностей для {len(active_accounts)} аккаунтов")
            
            for account in active_accounts:
                logger.info(f"Выполнение активностей для аккаунта {account.username}")
                
                try:
                    if not account.activity_plan:
                        logger.warning(f"У аккаунта {account.username} нет плана активности")
                        results[account.id] = {
                            "username": account.username,
                            "error": "Нет плана активности",
                            "success": False
                        }
                        continue
                    
                    next_day = account.current_day + 1
                    total_days = len(account.activity_plan.get('days', {}))
                    
                    if next_day > total_days:
                        logger.info(f"План для аккаунта {account.username} уже завершен")
                        results[account.id] = {
                            "username": account.username,
                            "error": "План уже завершен",
                            "success": False
                        }
                        continue
                    
                    day_plan = account.activity_plan.get('days', {}).get(str(next_day))
                    
                    if not day_plan:
                        logger.warning(f"План на день {next_day} для аккаунта {account.username} не найден")
                        results[account.id] = {
                            "username": account.username,
                            "error": f"План на день {next_day} не найден",
                            "success": False
                        }
                        continue
                    
                    if day_plan.get('is_day_off', False):
                        logger.info(f"Сегодня выходной день для аккаунта {account.username} (день {next_day})")
                        repo.increment_current_day(account.id)
                        results[account.id] = {
                            "username": account.username,
                            "results": {"day_off": True},
                            "success": True
                        }
                        continue
                    
                    activity_results = await self._execute_plan_for_account(account, day_plan)
                    
                    repo.increment_current_day(account.id)
                    
                    results[account.id] = {
                        "username": account.username,
                        "results": activity_results,
                        "success": True
                    }
                except Exception as e:
                    logger.error(f"Ошибка при выполнении активностей для {account.username}: {str(e)}")
                    results[account.id] = {
                        "username": account.username,
                        "error": str(e),
                        "success": False
                    }
                
                await asyncio.sleep(random.uniform(30, 60))
        
        return results
    
    
    async def _execute_plan_for_account(self, account, day_plan) -> Dict:
        results = {
            "likes": 0, 
            "comments": 0, 
            "topic_views": 0, 
            "post_views": 0, 
            "reading_time": 0
        }
        
        async with AptosForumClient(
            username=account.username,
            password=account.password,
            proxy=account.proxy
        ) as client:
            if day_plan.get('topics_view_planned', 0) > 0:
                topics_count = day_plan['topics_view_planned']
                logger.info(f"Просмотр {topics_count} топиков")
                viewed_topics = await client.view_random_topics(count=topics_count)
                results["topic_views"] = viewed_topics
            
            if day_plan.get('posts_view_planned', 0) > 0:
                posts_count = day_plan['posts_view_planned']
                logger.info(f"Просмотр {posts_count} постов")
                viewed_posts = await client.view_random_posts(
                    count=posts_count,
                    posts_per_topic=min(5, posts_count)
                )
                results["post_views"] = viewed_posts
            
            if day_plan.get('likes_planned', 0) > 0:
                likes_count = day_plan['likes_planned']
                logger.info(f"Постановка {likes_count} лайков")
                likes_success = 0
                
                for _ in range(likes_count):
                    if await client.like_random_post():
                        likes_success += 1
                    await asyncio.sleep(random.uniform(2.0, 5.0))
                
                results["likes"] = likes_success
            
            if day_plan.get('comments_planned', 0) > 0 and self.openai_api_key:
                comments_count = day_plan['comments_planned']
                logger.info(f"Написание {comments_count} комментариев")
                
                openai_model = self.openai_model
                
                proxy_config = None
                if self.config:
                    try:
                        proxy_enabled = self.config.get("openai", "proxy", {}).get("enabled", False)
                        
                        if proxy_enabled:
                            proxy_config = self.config.get_openai_proxy_config()
                            if proxy_config:
                                logger.info(f"Используем прокси OpenAI из конфигурации: {proxy_config.get('host')}:{proxy_config.get('port')}")
                        else:
                            logger.info("Прокси OpenAI отключен в конфигурации, запросы будут без прокси")
                    except Exception as e:
                        logger.error(f"Ошибка при получении прокси OpenAI из конфигурации: {str(e)}")
                
                if proxy_config:
                    logger.info(f"Используются прокси для OpenAI: {proxy_config.get('host')}:{proxy_config.get('port')}")
                else:
                    logger.info("Прокси для OpenAI не используется")
                
                comment_generator = create_comment_generator(
                    api_key=self.openai_api_key,
                    model=openai_model,
                    proxy_config=proxy_config
                )
                
                comments_success = 0
                for _ in range(comments_count):
                    if await client.comment_on_random_topic(
                        min_posts=3,
                        comment_generator=comment_generator
                    ):
                        comments_success += 1
                    await asyncio.sleep(random.uniform(10.0, 20.0))
                
                results["comments"] = comments_success
            
            if day_plan.get('reading_time_planned', 0) > 0:
                reading_time = day_plan['reading_time_planned']
                logger.info(f"Симуляция онлайн-присутствия на {reading_time} минут")
                
                completed_time = 0
                while completed_time < reading_time:
                    session_duration = min(
                        random.randint(10, 30),
                        reading_time - completed_time
                    )
                    
                    await client.simulate_online_presence(duration_minutes=session_duration)
                    completed_time += session_duration
                    
                    if completed_time < reading_time:
                        await asyncio.sleep(random.uniform(30, 90))
                
                results["reading_time"] = completed_time
        
        return results
    
    
    def _parse_proxy_config(self, proxy_str: Optional[str]) -> Optional[Dict]:
        if not proxy_str:
            return None
        
        try:
            if "://" in proxy_str:
                proxy_type = proxy_str.split("://")[0]
                rest = proxy_str.split("://")[1]
            else:
                proxy_type = "http"
                rest = proxy_str
            
            if "@" in rest:
                auth, host_port = rest.split("@", 1)
                username, password = auth.split(":", 1) if ":" in auth else (auth, "")
            else:
                host_port = rest
                username = password = ""
            
            host, port = host_port.split(":", 1) if ":" in host_port else (host_port, "")
            
            return {
                "type": proxy_type,
                "host": host,
                "port": port,
                "username": username,
                "password": password
            }
        except Exception as e:
            logger.error(f"Ошибка при парсинге прокси: {str(e)}")
        
        return None
    
    
    async def execute_daily_activities_for_account(self, account_id: int) -> Dict:
        results = {}
        
        with self.db_manager.session_scope() as session:
            repo = AccountRepository(session)
            account = repo.get_by_id(account_id)
            
            if not account or not account.is_active:
                logger.warning(f"Аккаунт {account_id} не найден или не активен")
                return {"error": "Аккаунт не найден или не активен", "success": False}
            
            logger.info(f"Выполнение активностей для аккаунта {account.username}")
            
            try:
                if not account.activity_plan:
                    logger.warning(f"У аккаунта {account.username} нет плана активности")
                    return {
                        "username": account.username,
                        "error": "Нет плана активности",
                        "success": False
                    }
                
                next_day = account.current_day + 1
                total_days = len(account.activity_plan.get('days', {}))
                
                if next_day > total_days:
                    logger.info(f"План для аккаунта {account.username} уже завершен")
                    return {
                        "username": account.username,
                        "error": "План уже завершен",
                        "success": False
                    }
                
                day_plan = account.activity_plan.get('days', {}).get(str(next_day))
                
                if not day_plan:
                    logger.warning(f"План на день {next_day} для аккаунта {account.username} не найден")
                    return {
                        "username": account.username,
                        "error": f"План на день {next_day} не найден",
                        "success": False
                    }
                
                if day_plan.get('is_day_off', False):
                    logger.info(f"Сегодня выходной день для аккаунта {account.username} (день {next_day})")
                    repo.increment_current_day(account.id)
                    results = {
                        "username": account.username,
                        "results": {"day_off": True},
                        "success": True
                    }
                    return results
                
                activity_results = await self._execute_plan_for_account(account, day_plan)
                
                repo.increment_current_day(account.id)
                
                account.last_activity = datetime.datetime.utcnow()
                
                results = {
                    "username": account.username,
                    "results": activity_results,
                    "success": True
                }
                
            except Exception as e:
                logger.error(f"Ошибка при выполнении активностей для {account.username}: {str(e)}")
                results = {
                    "username": account.username,
                    "error": str(e),
                    "success": False
                }
        
        return results
    