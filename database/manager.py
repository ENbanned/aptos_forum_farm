import os
import sqlite3
from contextlib import contextmanager

from sqlalchemy import QueuePool, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from config.logging_config import logger
from database.models import Base


class DatabaseManager:
    def __init__(self, db_url: str = None):
        self.db_url = db_url or 'sqlite:///aptos_farm.db'
        logger.debug(f"Инициализация подключения к базе данных: {self.db_url}")
        
        self.engine = create_engine(
            self.db_url,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=3600
        )
        
        self.Session = sessionmaker(bind=self.engine)
        
        self.Base = declarative_base()
        
        self.engine = create_engine(
            self.db_url,
            connect_args={"check_same_thread": False},
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=3600
        )
        
        
    def _enable_wal_mode(self):
        with self.engine.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            
            
    def create_tables(self):        
        logger.debug("Проверка и создание таблиц базы данных")
        
        if self.db_url.startswith('sqlite:///'):
            db_path = self.db_url.replace('sqlite:///', '')
            db_dir = os.path.dirname(db_path)
            
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
                logger.debug(f"Создана директория для базы данных: {db_dir}")
        
        Base.metadata.create_all(self.engine)
        
        try:
            if self.db_url.startswith('sqlite:///'):
                db_file = self.db_url.replace('sqlite:///', '')
                
                if not os.path.exists(db_file):
                    logger.debug(f"Файл БД не найден: {db_file}")
                    return
                    
                conn = sqlite3.connect(db_file)
                cursor = conn.cursor()
                
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'")
                table_exists = cursor.fetchone()
                
                if not table_exists:
                    logger.debug("Таблица accounts не найдена, она будет создана")
                    conn.close()
                    return
                
                cursor.execute("PRAGMA table_info(accounts)")
                columns = [row[1] for row in cursor.fetchall()]
                
                if 'current_day' not in columns:
                    logger.debug("Добавление столбца current_day в таблицу accounts")
                    cursor.execute("ALTER TABLE accounts ADD COLUMN current_day INTEGER DEFAULT 0")
                
                if 'activity_plan' not in columns:
                    logger.debug("Добавление столбца activity_plan в таблицу accounts")
                    cursor.execute("ALTER TABLE accounts ADD COLUMN activity_plan TEXT DEFAULT NULL")
                
                if 'last_activity' not in columns:
                    logger.debug("Добавление столбца last_activity в таблицу accounts")
                    cursor.execute("ALTER TABLE accounts ADD COLUMN last_activity TIMESTAMP DEFAULT NULL")
                
                if 'next_run_time' not in columns:
                    logger.debug("Добавление столбца next_run_time в таблицу accounts")
                    cursor.execute("ALTER TABLE accounts ADD COLUMN next_run_time TIMESTAMP DEFAULT NULL")
                
                if 'last_run_time' not in columns:
                    logger.debug("Добавление столбца last_run_time в таблицу accounts")
                    cursor.execute("ALTER TABLE accounts ADD COLUMN last_run_time TIMESTAMP DEFAULT NULL")
                
                if 'schedule_interval' not in columns:
                    logger.debug("Добавление столбца schedule_interval в таблицу accounts")
                    cursor.execute("ALTER TABLE accounts ADD COLUMN schedule_interval INTEGER DEFAULT 24")
                
                conn.commit()
                conn.close()
                logger.debug("Обновление структуры таблиц завершено")
        except Exception as e:
            logger.error(f"Ошибка при обновлении структуры таблиц: {str(e)}")
        
        logger.debug("Таблицы базы данных успешно проверены")
        
    
    @contextmanager
    def session_scope(self):
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.debug(f"Ошибка при работе с базой данных: {str(e)}")
            raise
        finally:
            session.close()
            