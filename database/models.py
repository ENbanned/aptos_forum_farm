import datetime
import json
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.types import TypeDecorator


Base = declarative_base()


class JSONEncodedDict(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return json.loads(value)


class Account(Base):
    __tablename__ = "accounts"
    
    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False, index=True)
    password = Column(String, nullable=False)
    proxy = Column(String, nullable=True)
    trust_level = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    current_day = Column(Integer, default=0)
    activity_plan = Column(JSONEncodedDict, nullable=True)
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_activity = Column(DateTime, nullable=True)
    next_run_time = Column(DateTime, nullable=True)
    last_run_time = Column(DateTime, nullable=True)
    schedule_interval = Column(Integer, default=24)

    def __repr__(self):
        return f"<Account(id={self.id}, username={self.username}, trust_level={self.trust_level})>"
    