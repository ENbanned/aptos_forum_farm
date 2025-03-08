import asyncio
import datetime
import random
from typing import Any

from config.logging_config import logger
from database.manager import DatabaseManager
from database.repositories.account_repository import AccountRepository
from services.account_service import AccountService


class TaskScheduler:    
    def __init__(self, account_service: AccountService, db_manager: DatabaseManager, config: Any):
        self.account_service = account_service
        self.db_manager = db_manager
        self.config = config
        self.running = False
        self.tasks = {}
    
    
    async def start(self):
        logger.info("Запуск планировщика задач")
        self.running = True
        
        self._initialize_account_schedules()
        
        asyncio.create_task(self._scheduler_loop())
        
        logger.success("Планировщик запущен и работает. Нажмите Ctrl+C для завершения.")
    
    
    async def stop(self):
        logger.info("Остановка планировщика задач")
        self.running = False
        
        for task_id, task in self.tasks.items():
            if not task.done():
                task.cancel()
        
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        
        self.tasks = {}
        
        
    def _initialize_account_schedules(self):
        with self.db_manager.session_scope() as session:
            repo = AccountRepository(session)
            active_accounts = repo.get_active_accounts()
            
            logger.info(f"Распределение активности для {len(active_accounts)} аккаунтов:")
            
            for account in active_accounts:
                account.next_run_time = None
            
            now = datetime.datetime.now()
            active_count = len(active_accounts)
            
            for i, account in enumerate(active_accounts):
                if active_count > 1:
                    base_hours = 0.1 + (0.2 * i / (active_count - 1))
                    random_adjustment = random.uniform(-0.5, 0.5)
                    delay_hours = max(0.5, base_hours + random_adjustment)
                else:
                    delay_hours = random.uniform(1, 3)
                
                next_run = now + datetime.timedelta(hours=delay_hours)
                account.next_run_time = next_run
                account.schedule_interval = random.uniform(22, 28)
                
                hour_str = f"{int(delay_hours)}ч {int((delay_hours*60) % 60)}м"
                run_time = next_run.strftime('%H:%M:%S')
                
                logger.info(f"→ Аккаунт {account.username} запланирован на {run_time} (через {hour_str})")
    
    
    async def _scheduler_loop(self):
        check_interval = 60 
        
        while self.running:
            try:
                accounts_to_run = self._get_accounts_to_run()
                
                for account_id in accounts_to_run:
                    with self.db_manager.session_scope() as session:
                        repo = AccountRepository(session)
                        account = repo.get_by_id(account_id)
                        if account:
                            logger.success(f"Запуск задач для аккаунта {account.username}")
                    
                    task = asyncio.create_task(self._execute_account_tasks(account_id))
                    self.tasks[account_id] = task
                
                self._clean_completed_tasks()
                
                await asyncio.sleep(check_interval)
                
            except Exception as e:
                logger.error(f"Ошибка в цикле планировщика: {str(e)}")
                await asyncio.sleep(check_interval)
    
    
    def _get_accounts_to_run(self):
        current_time = datetime.datetime.now()
        accounts_to_run = []
        
        with self.db_manager.session_scope() as session:
            repo = AccountRepository(session)
            active_accounts = repo.get_active_accounts()
            
            for account in active_accounts:
                if not account.next_run_time:
                    continue
                    
                task_running = account.id in self.tasks
                
                if (account.next_run_time <= current_time and not task_running):
                    accounts_to_run.append(account.id)
                    
                    delta = current_time - account.next_run_time
                    minutes_ago = int(delta.total_seconds() / 60)
                    
                    if minutes_ago > 0:
                        logger.info(f"Запуск {account.username} (запланирован {minutes_ago} мин. назад)")
                    else:
                        logger.info(f"Запуск {account.username} (время выполнения)")
        
        return accounts_to_run
        
        
    def _clean_completed_tasks(self):
        completed_ids = []
        for task_id, task in list(self.tasks.items()):
            if task.done():
                completed_ids.append(task_id)
                
        for task_id in completed_ids:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                if task.exception():
                    logger.error(f"Задача для аккаунта {task_id} завершилась с ошибкой: {task.exception()}")
                del self.tasks[task_id]
    
    
    async def _execute_account_tasks(self, account_id: int):
        try:
            result = await self.account_service.execute_daily_activities_for_account(account_id)
            
            with self.db_manager.session_scope() as session:
                repo = AccountRepository(session)
                account = repo.get_by_id(account_id)
                
                if account:
                    account.last_run_time = datetime.datetime.now()
                    
                    interval_hours = random.uniform(22, 26)
                    account.schedule_interval = interval_hours
                    
                    account.next_run_time = account.last_run_time + datetime.timedelta(hours=interval_hours)
                    
                    logger.info(f"Следующий запуск для {account.username} запланирован на {account.next_run_time} (через {interval_hours:.2f} часов)")
                    
            return result
            
        except Exception as e:
            logger.error(f"Ошибка при выполнении задач для аккаунта {account_id}: {str(e)}")
            with self.db_manager.session_scope() as session:
                repo = AccountRepository(session)
                account = repo.get_by_id(account_id)
                
                if account:
                    account.last_run_time = datetime.datetime.now()
                    
                    account.next_run_time = account.last_run_time + datetime.timedelta(hours=1)
                    
                    logger.info(f"Из-за ошибки следующий запуск для {account.username} запланирован через 1 час")
                    