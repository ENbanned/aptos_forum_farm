import asyncio
import sys
import os
import time
import traceback
import signal
from pathlib import Path
from contextlib import suppress

from config.config_manager import ConfigManager
from config.logging_config import logger
from database.manager import DatabaseManager
from services.account_service import AccountService
from services.scheduler import TaskScheduler


def setup_application() -> tuple:
    files_dir = Path("files")
    files_dir.mkdir(exist_ok=True)
    
    try:
        config = ConfigManager()
    except Exception as e:
        logger.error(f"Ошибка при загрузке конфигурации: {e}")
        config = None
    
    logger.info("Запуск Aptos Forum")
    
    try:
        db_url = config.get_database_url() if config else f"sqlite:///{files_dir}/aptos_farm.db"
        db_manager = DatabaseManager(db_url)
        db_manager.create_tables()
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных: {e}")
        sys.exit(1)
    
    openai_api_key = config.get_openai_api_key() if config else ""
    account_service = AccountService(db_manager, openai_api_key)
    
    csv_path = files_dir / "accounts.csv"
    if not csv_path.exists():
        logger.info(f"Файл аккаунтов {csv_path} не существует, создаем шаблон")
        account_service.create_accounts_csv_template(str(csv_path))
        logger.info(f"Создан шаблон файла аккаунтов: {csv_path}")
    
    try:
        scheduler = TaskScheduler(account_service, db_manager, config)
    except Exception as e:
        logger.error(f"Ошибка при инициализации планировщика: {e}")
        scheduler = None
    
    logger.info("Приложение успешно инициализировано")
    return account_service, scheduler, config


def setup_signal_handlers(shutdown_event):
    
    def signal_handler(*args):
        logger.info("\nПолучен сигнал завершения, останавливаем приложение...")
        shutdown_event.set()
    
    if sys.platform == 'win32':
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    else:
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(signal.SIGINT, signal_handler)
        loop.add_signal_handler(signal.SIGTERM, signal_handler)


async def main_async():
    shutdown_event = asyncio.Event()
    
    setup_signal_handlers(shutdown_event)
    
    try:
        account_service, scheduler, config = setup_application()
        
        header = r"""
  █████╗ ██████╗ ████████╗ ██████╗ ███████╗   ███████╗ █████╗ ██████╗ ███╗   ███╗
 ██╔══██╗██╔══██╗╚══██╔══╝██╔═══██╗██╔════╝   ██╔════╝██╔══██╗██╔══██╗████╗ ████║
 ███████║██████╔╝   ██║   ██║   ██║███████╗   █████╗  ███████║██████╔╝██╔████╔██║
 ██╔══██║██╔═══╝    ██║   ██║   ██║╚════██║   ██╔══╝  ██╔══██║██╔══██╗██║╚██╔╝██║
 ██║  ██║██║        ██║   ╚██████╔╝███████║██╗██║     ██║  ██║██║  ██║██║ ╚═╝ ██║
 ╚═╝  ╚═╝╚═╝        ╚═╝    ╚═════╝ ╚══════╝╚═╝╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝
"""

        while not shutdown_event.is_set():
            if sys.platform.startswith('win'):
                os.system('cls')
            else:
                os.system('clear')
            
            print("\033[36m" + header + "\033[0m")
            print("\033[92m{:=^80}\033[0m".format("")) 
            print("\033[93m{:^80}\033[0m".format("Telegram: https://t.me/enbanends_home"))
            print("\033[93m{:^80}\033[0m".format("@enbanned"))
            print("\033[92m{:=^80}\033[0m".format("")) 
            print("\n\033[96mМенеджер активности аккаунтов на форуме Aptos Foundation\033[0m")
            print("\033[90m{:-^80}\033[0m".format(""))
            
            print("\n\033[95mВыберите действие:\033[0m")
            print("\033[94m1. Импорт аккаунтов из CSV")
            print("2. Запустить планировщик")
            print("0. Выход\033[0m")
            print("\033[90m{:-^80}\033[0m".format(""))
            
            user_input_task = asyncio.create_task(wait_for_user_input("\n\033[93mВведите номер операции > \033[0m"))
            wait_event_task = asyncio.create_task(wait_for_event(shutdown_event))
            
            done, pending = await asyncio.wait(
                [user_input_task, wait_event_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            for task in pending:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            
            if shutdown_event.is_set():
                break
            
            choice = ""
            for task in done:
                try:
                    choice = task.result()
                except Exception:
                    pass
            
            if choice == "1":
                csv_path = Path("files") / "accounts.csv"
                
                os.system('cls' if os.name == 'nt' else 'clear')
                print("\033[36m" + header + "\033[0m")
                print("\033[92m{:=^80}\033[0m".format(""))
                print("\033[93m{:^80}\033[0m".format("Telegram: https://t.me/enbanends_home"))
                print("\033[93m{:^80}\033[0m".format("@enbanned"))
                print("\033[92m{:=^80}\033[0m".format(""))
                
                try:
                    print("\n\033[96mИмпорт аккаунтов из CSV\033[0m")
                    print("\033[90m{:-^80}\033[0m".format(""))
                    
                    logger.info(f"Импорт аккаунтов из файла '{csv_path}'...")
                    
                    if not csv_path.exists():
                        print("\033[91mФайл не найден! Создаю шаблон...\033[0m")
                        account_service.create_accounts_csv_template(str(csv_path))
                        print(f"\033[92mШаблон создан: {csv_path}\033[0m")
                    else:
                        added, updated, errors = account_service.import_accounts_from_csv(str(csv_path))
                        print("\n\033[93mРезультаты импорта:\033[0m")
                        print(f"\033[92mДобавлено: {added}\033[0m")
                        print(f"\033[93mОбновлено: {updated}\033[0m")
                        print(f"\033[91mОшибок: {errors}\033[0m")
                        
                except Exception as e:
                    print(f"\033[91mОшибка: {str(e)}\033[0m")
                
                print("\n\033[94mНажмите Enter чтобы продолжить...\033[0m")
                await wait_for_enter()
                
            elif choice == "2":
                logger.info("\nЗапуск планировщика...")
                await scheduler.start()
                logger.success("\nПланировщик запущен. Нажмите Ctrl+C для завершения.")
                
                watchdog_task = asyncio.create_task(scheduler_watchdog(scheduler))
                
                try:
                    while not shutdown_event.is_set():
                        await asyncio.sleep(1)
                finally:
                    watchdog_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await watchdog_task
                    
                    logger.info("\nОстановка планировщика...")
                    await scheduler.stop()
                    logger.info("Планировщик остановлен.")
                
            elif choice == "0":
                logger.info("\nЗавершение работы программы...")
                break
            
            else:
                logger.error("\nНеверный выбор. Пожалуйста, попробуйте снова.")
        
    except KeyboardInterrupt:
        logger.info("Завершение работы приложения")
        if 'scheduler' in locals() and scheduler and scheduler.running:
            await scheduler.stop()
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}")
        if 'scheduler' in locals() and scheduler and scheduler.running:
            await scheduler.stop()
        sys.exit(1)


async def wait_for_user_input(prompt):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, input, prompt)


async def wait_for_enter():
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input)


async def wait_for_event(event):
    await event.wait()
    return ""


async def scheduler_watchdog(scheduler, check_interval=300):
    last_check_time = time.time()
    
    while True:
        try:
            if not scheduler.running:
                logger.warning("Сторожевой таймер: Планировщик не запущен, перезапускаем...")
                await scheduler.start()
            
            current_time = time.time()
            if current_time - last_check_time > check_interval:
                logger.info("Сторожевой таймер: Проверка работоспособности планировщика...")
                
                last_check_time = current_time
            
            await asyncio.sleep(60)
            
        except asyncio.CancelledError:
            logger.info("Сторожевой таймер планировщика остановлен")
            break
        except Exception as e:
            logger.error(f"Ошибка в сторожевом таймере планировщика: {str(e)}")
            await asyncio.sleep(60)


def main():
    try:
        files_dir = Path("files")
        files_dir.mkdir(exist_ok=True)
        
        if sys.version_info >= (3, 8):
            loop_policy = asyncio.get_event_loop_policy()
            loop = loop_policy.new_event_loop()
            loop.set_exception_handler(custom_exception_handler)
            asyncio.set_event_loop(loop)
            loop.run_until_complete(main_async())
            loop.close()
        else:
            loop = asyncio.get_event_loop()
            loop.set_exception_handler(custom_exception_handler)
            loop.run_until_complete(main_async())
            loop.close()
        
    except KeyboardInterrupt:
        logger.info("\nЗавершение работы приложения...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}")
        traceback.print_exc()
        sys.exit(1)


def custom_exception_handler(loop, context):
    exception = context.get('exception')
    message = context.get('message')
    
    if isinstance(exception, asyncio.CancelledError):
        logger.debug(f"Задача отменена: {message}")
        return
        
    logger.error(f"Необработанное исключение в асинхронном коде: {message}")
    if exception:
        logger.error(f"Исключение: {exception}")
        logger.error(f"Трассировка: {traceback.format_exception(type(exception), exception, exception.__traceback__)}")


if __name__ == "__main__":
    main()