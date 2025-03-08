import datetime
import random
from typing import List, Optional

from sqlalchemy.orm import Session

from config.logging_config import logger
from database.models import Account


class AccountRepository:
    def __init__(self, session: Session):
        self.session = session
    
    
    def get_by_id(self, account_id: int) -> Optional[Account]:
        return self.session.query(Account).filter_by(id=account_id).first()
    
    
    def get_by_username(self, username: str) -> Optional[Account]:
        return self.session.query(Account).filter_by(username=username).first()
    
    
    def get_all(self) -> List[Account]:
        return self.session.query(Account).all()
    
    
    def get_active_accounts(self) -> List[Account]:
        return self.session.query(Account).filter_by(is_active=True).all()
    
    
    def create(self, username: str, password: str, proxy: Optional[str] = None) -> Account:
        account = Account(
            username=username,
            password=password,
            proxy=proxy,
            is_active=True,
            trust_level=0,
            current_day=0,
            activity_plan=None,
            created_at=datetime.datetime.utcnow()
        )
        self.session.add(account)
        self.session.flush()
        logger.info(f"Создан новый аккаунт: {username}")
        return account
    
    
    def update(self, account: Account) -> Account:
        self.session.merge(account)
        logger.debug(f"Обновлен аккаунт: {account.username}")
        return account
    
    
    def delete(self, account_id: int) -> bool:
        account = self.get_by_id(account_id)
        if account:
            self.session.delete(account)
            logger.info(f"Удален аккаунт: {account.username}")
            return True
        return False
    
    
    def toggle_status(self, account_id: int, is_active: bool) -> bool:
        account = self.get_by_id(account_id)
        if account:
            account.is_active = is_active
            status = "активирован" if is_active else "деактивирован"
            logger.info(f"Аккаунт {account.username} {status}")
            return True
        return False
    
    
    def get_accounts_without_plans(self) -> List[Account]:
        return self.session.query(Account).filter(Account.activity_plan == None).all()


    def increment_current_day(self, account_id: int) -> bool:
        account = self.get_by_id(account_id)
        if account and account.activity_plan:
            total_days = len(account.activity_plan.get('days', []))
            if account.current_day < total_days:
                account.current_day += 1
                account.last_activity = datetime.datetime.utcnow()
                logger.info(f"Обновлен текущий день для {account.username}: {account.current_day}/{total_days}")
                return True
        return False


    def generate_activity_plan(self, account_id: int) -> bool:
        account = self.get_by_id(account_id)
        if not account:
            return False
            
        if account.activity_plan:
            return False
            
        total_days = random.randint(102, 115)
        
        days_off_count = int(total_days * random.uniform(0.1, 0.2))
        days_off = set(random.sample(range(1, total_days + 1), days_off_count))
        
        total_likes = random.randint(35, 80)
        total_comments = random.randint(20, 30)
        total_topics = random.randint(50, 100)
        total_posts = random.randint(300, 700)
        total_reading_time = random.randint(600, 1800)
        
        working_days = [day for day in range(1, total_days + 1) if day not in days_off]
        
        likes_distribution = self._distribute_activity(total_likes, len(working_days))
        comments_distribution = self._distribute_activity(total_comments, len(working_days))
        topics_distribution = self._distribute_activity(total_topics, len(working_days))
        posts_distribution = self._distribute_activity(total_posts, len(working_days))
        reading_distribution = self._distribute_activity(total_reading_time, len(working_days))
        
        plan = {
            'total_days': total_days,
            'creation_date': datetime.datetime.utcnow().isoformat(),
            'days': {}
        }
        
        for day in range(1, total_days + 1):
            is_day_off = day in days_off
            
            if is_day_off:
                plan['days'][str(day)] = {
                    'is_day_off': True,
                    'view_percentage': round(random.uniform(70.0, 100.0), 2)
                }
            else:
                idx = working_days.index(day)
                plan['days'][str(day)] = {
                    'is_day_off': False,
                    'likes_planned': likes_distribution[idx],
                    'comments_planned': comments_distribution[idx],
                    'topics_view_planned': topics_distribution[idx],
                    'posts_view_planned': posts_distribution[idx],
                    'reading_time_planned': reading_distribution[idx],
                    'view_percentage': round(random.uniform(70.0, 100.0), 2)
                }
        
        account.activity_plan = plan
        account.current_day = 0
        logger.info(f"Создан план активности для аккаунта {account.username} на {total_days} дней")
        return True
    
    
    def _distribute_activity(self, total: int, days: int) -> List[int]:
        if days <= 0 or total <= 0:
            return [0] * max(1, days)
        
        base = total // days
        remainder = total % days
        
        distribution = [base for _ in range(days)]
        
        for i in range(remainder):
            distribution[i] += 1
        
        for i in range(days):
            if base > 2: 
                variation = int(base * random.uniform(-0.3, 0.3))
                if distribution[i] + variation > 0:
                    distribution[i] += variation
        
        current_sum = sum(distribution)
        if current_sum != total:
            diff = total - current_sum
            step = max(1, abs(diff) // min(abs(diff), days))
            
            if diff > 0:
                for i in range(0, days, step):
                    if sum(distribution) >= total:
                        break
                    distribution[i % days] += 1
            else:
                for i in range(0, days, step):
                    if sum(distribution) <= total:
                        break
                    if distribution[i % days] > 1:
                        distribution[i % days] -= 1
        
        random.shuffle(distribution)
        
        return distribution
    