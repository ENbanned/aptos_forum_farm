import asyncio
import sys
import os
import traceback
from pathlib import Path

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


async def main_async():
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

        while True:
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
            
            choice = input("\n\033[93mВведите номер операции > \033[0m")
            
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
                input()
                
            elif choice == "2":
                logger.info("\nЗапуск планировщика...")
                await scheduler.start()
                logger.success("\nПланировщик запущен. Нажмите Ctrl+C для завершения.")
                
                try:
                    while True:
                        await asyncio.sleep(60)
                except KeyboardInterrupt:
                    logger.info("\nОстановка планировщика...")
                    await scheduler.stop()
                    logger.info("Планировщик остановлен.")
                    break
                
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


def main():
    try:
        files_dir = Path("files")
        files_dir.mkdir(exist_ok=True)
        
        asyncio.run(main_async())
        
    except KeyboardInterrupt:
        logger.info("\nЗавершение работы приложения...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
    