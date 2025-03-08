from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class TopicData:
    id: Optional[int] = None
    title: Optional[str] = None
    fancy_title: Optional[str] = None
    slug: Optional[str] = None
    posts_count: Optional[int] = None
    created_at: Optional[str] = None
    last_posted_at: Optional[str] = None
    category_id: Optional[int] = None
    category_name: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PostData:
    id: Optional[int] = None
    username: Optional[str] = None
    user_id: Optional[int] = None
    topic_id: Optional[int] = None
    post_number: Optional[int] = None
    cooked: Optional[str] = None  
    raw: Optional[str] = None     
    created_at: Optional[str] = None
    actions_summary: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    
@dataclass
class AccountCredentials:
    username: str
    password: str