import os
from dataclasses import dataclass


@dataclass
class Settings:
    database_url: str
    openai_api_key: str
    logging_level: str
    forum_base_url: str
    
    def __init__(self):
        self.database_url = os.environ.get('APTOS_DATABASE_URL', 'sqlite:///aptos_farm.db')
        self.openai_api_key = os.environ.get('OPENAI_API_KEY', '')
        self.logging_level = os.environ.get('LOGGING_LEVEL', 'INFO')
        self.forum_base_url = os.environ.get('FORUM_BASE_URL', 'https://forum.aptosfoundation.org')