import json
from pathlib import Path
from typing import Any, Dict, Optional

from config.logging_config import logger


class ConfigManager:    
    def __init__(self, config_path: Optional[str] = None):
        self.files_dir = Path("files")
        self.files_dir.mkdir(exist_ok=True)
        
        self.config_path = Path(config_path) if config_path else self.files_dir / "config.json"
        self.config: Dict[str, Any] = {}
        
        self._load_config()
    
    
    def _create_default_config(self) -> Dict[str, Any]:
        return {
            "database": {
                "url": f"sqlite:///{self.files_dir}/aptos_farm.db"
            },
            "logging": {
                "level": "INFO",
                "to_file": True,
                "file_path": str(self.files_dir / "aptos_farm.log")
            },
            "openai": {
                "api_key": "",
                "model": "gpt-3.5-turbo",
                "proxy": {
                    "enabled": False,
                    "host": "",
                    "port": "",
                    "username": "",
                    "password": "",
                    "type": "http"
                }
            },
            "forum": {
                "base_url": "https://forum.aptosfoundation.org"
            },
            "scheduler": {
                "enabled": True,
                "random_start_window_hours": 24
            }
        }
    
    
    def _load_config(self) -> None:
        try:
            self.config_path.parent.mkdir(exist_ok=True)
            
            if not self.config_path.exists():
                self.config = self._create_default_config()
                self._save_config()
                logger.info(f"Создан новый файл конфигурации: {self.config_path}")
            else:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                logger.debug(f"Загружена конфигурация из {self.config_path}")
        except Exception as e:
            logger.debug(f"Ошибка при загрузке конфигурации: {str(e)}")
            self.config = self._create_default_config()
            try:
                self._save_config()
            except Exception:
                pass
    
    
    def _save_config(self) -> None:
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка при сохранении конфигурации: {str(e)}")
    
    
    def get(self, section: str, key: Optional[str] = None, default: Any = None) -> Any:
        if section not in self.config:
            return default
            
        if key is None:
            return self.config[section]
            
        return self.config[section].get(key, default)
    
    
    def set(self, section: str, key: str, value: Any) -> None:
        if section not in self.config:
            self.config[section] = {}
            
        self.config[section][key] = value
        self._save_config()
    
    
    def set_section(self, section: str, values: Dict[str, Any]) -> None:
        self.config[section] = values
        self._save_config()
    
    
    def get_database_url(self) -> str:
        return self.get("database", "url", f"sqlite:///{self.files_dir}/aptos_farm.db")
    
    
    def get_openai_api_key(self) -> str:
        return self.get("openai", "api_key", "")
    
    
    def get_openai_proxy_config(self) -> Dict[str, Any]:
        proxy_config = self.get("openai", "proxy", {})
        if not proxy_config.get("enabled", False):
            return None
        return {
            "host": proxy_config.get("host", ""),
            "port": proxy_config.get("port", ""),
            "username": proxy_config.get("username", ""),
            "password": proxy_config.get("password", ""),
            "type": proxy_config.get("type", "http")
        }
    
    
    def get_logging_config(self) -> Dict[str, Any]:
        logging_config = self.get("logging", {})
        if logging_config.get("to_file", True) and not logging_config.get("file_path"):
            logging_config["file_path"] = str(self.files_dir / "aptos_farm.log")
        return logging_config
    
    
    def get_forum_base_url(self) -> str:
        return self.get("forum", "base_url", "https://forum.aptosfoundation.org")
    
    
    def get_scheduler_config(self) -> Dict[str, Any]:
        return self.get("scheduler", {})
    