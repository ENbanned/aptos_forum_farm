import asyncio
import datetime
import random
import signal
import sys
from typing import Any, Dict, List, Set

from config.logging_config import logger
from database.manager import DatabaseManager
from database.repositories.account_repository import AccountRepository
from services.account_service import AccountService


class TaskWatchdog:    
    def __init__(self, timeout_seconds: int = 600):
        self.tasks: Dict[int, Dict] = {}
        self.timeout_seconds = timeout_seconds
        self.running = False
        self._watchdog_task = None
        
        
    async def start(self):
        self.running = True
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
       
        
    async def stop(self):
        self.running = False
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
    
    
    def register_task(self, task_id: int, task: asyncio.Task, description: str):
        self.tasks[task_id] = {
            "task": task,
            "start_time": datetime.datetime.now(),
            "description": description
        }
        
        
    def unregister_task(self, task_id: int):

        if task_id in self.tasks:
            del self.tasks[task_id]
    
    
    async def _watchdog_loop(self):
        while self.running:
            try:
                now = datetime.datetime.now()
                for task_id, task_info in list(self.tasks.items()):
                    task = task_info["task"]
                    start_time = task_info["start_time"]
                    description = task_info["description"]
                    
                    if not task.done() and (now - start_time).total_seconds() > self.timeout_seconds:
                        logger.warning(f"Обнаружена зависшая задача: {description}. "
                                    f"Выполняется {(now - start_time).total_seconds():.1f} секунд. Перезапуск...")
                        
                        task.cancel()
                        
                        # Если это основной цикл планировщика, создаем новый
                        if task_id == -1 and description == "Основной цикл планировщика":
                            # Дожидаемся завершения старой задачи
                            try:
                                await asyncio.wait_for(task, timeout=5.0)
                            except (asyncio.CancelledError, asyncio.TimeoutError):
                                pass
                            
                            # Создаем новый цикл планировщика
                            from_scheduler = task_info.get("owner")
                            if from_scheduler and hasattr(from_scheduler, "_scheduler_loop"):
                                new_task = asyncio.create_task(from_scheduler._scheduler_loop())
                                self.tasks[task_id] = {
                                    "task": new_task,
                                    "start_time": datetime.datetime.now(),
                                    "description": description,
                                    "owner": from_scheduler
                                }
                                logger.info("Создан новый цикл планировщика взамен зависшего")
                                continue
                        
                        self.unregister_task(task_id)
            except Exception as e:
                logger.error(f"Ошибка в сторожевом таймере: {str(e)}")
                
            await asyncio.sleep(30)


class TaskScheduler:    
    def __init__(self, account_service: AccountService, db_manager: DatabaseManager, config: Any):
        self.account_service = account_service
        self.db_manager = db_manager
        self.config = config
        self.running = False
        self.tasks = {}
        self.scheduler_task = None
        self.watchdog = TaskWatchdog(timeout_seconds=1800)  
        self.busy_accounts: Set[int] = set()
    
    
    async def start(self):
        logger.info("Запуск планировщика задач")
        self.running = True
        
        self._setup_signal_handlers()
        
        await self.watchdog.start()
        
        self._initialize_account_schedules()
        
        self.scheduler_task = asyncio.create_task(self._scheduler_loop())
        self.watchdog.register_task(-1, self.scheduler_task, "Основной цикл планировщика")
        
        logger.success("Планировщик запущен и работает. Нажмите Ctrl+C для завершения.")
    
    
    async def stop(self):
        logger.info("Остановка планировщика задач")
        self.running = False
        
        await self.watchdog.stop()
        
        if self.scheduler_task and not self.scheduler_task.done():
            self.scheduler_task.cancel()
        
        active_tasks = []
        for task_id, task in list(self.tasks.items()):
            if not task.done():
                logger.info(f"Отмена задачи для аккаунта {task_id}")
                task.cancel()
                active_tasks.append(task)
        
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)
        
        self.tasks = {}
        self.busy_accounts.clear()
        
        logger.success("Планировщик успешно остановлен")
        
    
    def _setup_signal_handlers(self):
        
        def signal_handler():
            if self.running:
                asyncio.create_task(self.stop())
                logger.info("Получен сигнал завершения, останавливаем планировщик...")
        
        if sys.platform == 'win32':
            signal.signal(signal.SIGINT, lambda s, f: signal_handler())
            signal.signal(signal.SIGTERM, lambda s, f: signal_handler())
        else:
            loop = asyncio.get_event_loop()
            loop.add_signal_handler(signal.SIGINT, signal_handler)
            loop.add_signal_handler(signal.SIGTERM, signal_handler)
        
    
    def _initialize_account_schedules(self):
        with self.db_manager.session_scope() as session:
            repo = AccountRepository(session)
            active_accounts = repo.get_active_accounts()
            
            logger.info(f"Распределение активности для {len(active_accounts)} аккаунтов:")
            
            for account in active_accounts:
                account.next_run_time = None
            
            now = datetime.datetime.now()
            
            random_start_window_minutes = 300
            
            if self.config:
                try:
                    config_minutes = self.config.get("scheduler", "random_start_window_minutes", 300)
                    if isinstance(config_minutes, (int, float)) and config_minutes > 0:
                        random_start_window_minutes = int(config_minutes)
                except Exception as e:
                    logger.error(f"Ошибка при получении конфигурации планировщика: {str(e)}")
            
            all_delays = list(range(1, random_start_window_minutes + 1))
            random.shuffle(all_delays)
            
            for i, account in enumerate(active_accounts):
                delay_idx = i % len(all_delays)
                delay_minutes = all_delays[delay_idx]
                delay_hours = delay_minutes / 60
                
                next_run = now + datetime.timedelta(minutes=delay_minutes)
                account.next_run_time = next_run
                account.schedule_interval = random.uniform(22, 28)
                
                hour_str = f"{int(delay_hours)}ч {int(delay_minutes % 60)}м"
                run_time = next_run.strftime('%H:%M:%S')
                
                logger.info(f"→ Аккаунт {account.username} запланирован на {run_time} (через {hour_str})")
    
    
    async def _scheduler_loop(self):
        check_interval = 30
        
        while self.running:
            try:
                self._clean_completed_tasks()
                
                accounts_to_run = self._get_accounts_to_run()
                
                for account_id in accounts_to_run:
                    if account_id in self.busy_accounts:
                        continue
                        
                    with self.db_manager.session_scope() as session:
                        repo = AccountRepository(session)
                        account = repo.get_by_id(account_id)
                        if account:
                            logger.success(f"Запуск задач для аккаунта {account.username}")
                            
                            self.busy_accounts.add(account_id)
                            
                            task = asyncio.create_task(self._execute_account_tasks_with_timeout(account_id))
                            self.tasks[account_id] = task
                            
                            self.watchdog.register_task(account_id, task, f"Задача для аккаунта {account.username}")
                
                await asyncio.sleep(check_interval)
                
            except asyncio.CancelledError:
                logger.info("Цикл планировщика отменен")
                raise
            except Exception as e:
                logger.error(f"Ошибка в цикле планировщика: {str(e)}")
                await asyncio.sleep(check_interval)
    
    
    def _get_accounts_to_run(self) -> List[int]:
        current_time = datetime.datetime.now()
        accounts_to_run = []
        
        with self.db_manager.session_scope() as session:
            repo = AccountRepository(session)
            active_accounts = repo.get_active_accounts()
            
            for account in active_accounts:
                if not account.next_run_time:
                    continue
                    
                try:
                    account_id = account.id
                    if not isinstance(account_id, (int, str, float, bool, tuple)):
                        logger.error(f"Некорректный тип ID аккаунта {account.username}: {type(account_id)}")
                        continue
                    
                    if (account_id not in self.busy_accounts and 
                        account_id not in self.tasks and 
                        account.next_run_time <= current_time):
                        
                        accounts_to_run.append(account_id)
                        
                        delta = current_time - account.next_run_time
                        minutes_ago = int(delta.total_seconds() / 60)
                        
                        if minutes_ago > 0:
                            logger.info(f"Запуск {account.username} (запланирован {minutes_ago} мин. назад)")
                        else:
                            logger.info(f"Запуск {account.username} (время выполнения)")
                except TypeError as e:
                    logger.error(f"Ошибка при проверке задачи для аккаунта {account.username}: {str(e)}")
                    continue
        
        return accounts_to_run
        
        
    def _clean_completed_tasks(self):
        completed_ids = []
        for task_id, task in list(self.tasks.items()):
            try:
                if task.done():
                    completed_ids.append(task_id)
                    
                    try:
                        exception = task.exception()
                        if exception:
                            logger.error(f"Задача для аккаунта {task_id} завершилась с ошибкой: {exception}")
                    except (asyncio.CancelledError, asyncio.InvalidStateError):
                        pass
                    
                    if task_id in self.busy_accounts:
                        self.busy_accounts.remove(task_id)
                    
                    self.watchdog.unregister_task(task_id)
            except Exception as e:
                logger.error(f"Ошибка при проверке задачи {task_id}: {str(e)}")
                completed_ids.append(task_id)
                
                if task_id in self.busy_accounts:
                    self.busy_accounts.remove(task_id)
                    
                self.watchdog.unregister_task(task_id)
                
        for task_id in completed_ids:
            if task_id in self.tasks:
                del self.tasks[task_id]
    
    
    async def _execute_account_tasks_with_timeout(self, account_id: int):
        max_execution_time = 1800
        
        try:
            task = asyncio.create_task(self._execute_account_tasks(account_id))
            
            try:
                return await asyncio.wait_for(task, timeout=max_execution_time)
            except asyncio.TimeoutError:
                logger.error(f"Таймаут при выполнении задач для аккаунта {account_id}")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                
                with self.db_manager.session_scope() as session:
                    repo = AccountRepository(session)
                    account = repo.get_by_id(account_id)
                    if account:
                        account.last_run_time = datetime.datetime.now()
                        account.next_run_time = account.last_run_time + datetime.timedelta(hours=1)
                        logger.info(f"Из-за таймаута следующий запуск для {account.username} запланирован через 1 час")
                
                return {"error": "Превышено время выполнения", "success": False}
        finally:
            if account_id in self.busy_accounts:
                self.busy_accounts.remove(account_id)
    
    
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
            
        except asyncio.CancelledError:
            logger.warning(f"Задача для аккаунта {account_id} была отменена")
            raise
        except Exception as e:
            logger.error(f"Ошибка при выполнении задач для аккаунта {account_id}: {str(e)}")
            with self.db_manager.session_scope() as session:
                repo = AccountRepository(session)
                account = repo.get_by_id(account_id)
                
                if account:
                    account.last_run_time = datetime.datetime.now()
                    
                    account.next_run_time = account.last_run_time + datetime.timedelta(hours=1)
                    
                    logger.info(f"Из-за ошибки следующий запуск для {account.username} запланирован через 1 час")
            
            return {"error": str(e), "success": False}
        