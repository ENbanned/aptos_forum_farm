import random
import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

import httpx
from loguru import logger
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential


class ProxyType(Enum):
    SOCKS5 = "socks5"
    HTTP = "http"


@dataclass
class ProxyConfig:
    host: str
    port: str
    username: str 
    password: str
    proxy_type: ProxyType = ProxyType.HTTP
    
    def get_url(self) -> str:
        if self.proxy_type == ProxyType.SOCKS5:
            return f"socks5://{self.username}:{self.password}@{self.host}:{self.port}"
        else:
            return f"http://{self.username}:{self.password}@{self.host}:{self.port}"


class CommentGenerator:    
    def __init__(
        self, 
        api_key: str, 
        model: str = "gpt-3.5-turbo", 
        proxy: Optional[ProxyConfig] = None
    ):
        http_client = None
        
        if proxy:
            proxy_url = proxy.get_url()
            logger.info(f"Настройка прокси для OpenAI API: {proxy_url}")
            http_client = httpx.AsyncClient(proxy=proxy_url)
            
        self.client = AsyncOpenAI(
            api_key=api_key,
            http_client=http_client
        )
            
        self.model = model


    @retry(
        stop=stop_after_attempt(3), 
        wait=wait_exponential(multiplier=1, min=4, max=30),
    )
    async def generate_comment(
        self, 
        topic_title: str, 
        main_post_text: str, 
        comments_text: List[str]
    ) -> str:
        try:
            avg_length = self._get_average_length(comments_text)
            
            max_words = 10 if avg_length > 10 else max(5, avg_length)
            
            if avg_length < 5:
                max_words = 5
            
            examples = comments_text[:2] if comments_text else []
            examples_text = "\n".join([f"- {comment}" for comment in examples])
            
            prompt = f"""You are a typical forum user. People write comments like this:

{examples_text if examples_text else "Usually people write short and simple comments."}

Make a VERY short and extremely SIMPLE comment to the post with the title: "{topic_title}"

Rules:
1. Maximum {max_words} words
2. Write EXTREMELY simple and casual
3. No sophisticated words
4. No emojis
5. Don't use complex sentence structures
6. Write like a lazy user
7. Use style like "agree", "nice", "cool"
8. No formalities
9. Write VERY briefly!
10. You are NOT an assistant, write like the simplest person on the forum
11. ALWAYS write in English only
12. Match the tone of existing comments
13. Use casual English internet slang when appropriate"""

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Write a very short and primitive comment to the post in English."}
                ],
                temperature=0.4,
                max_tokens=30,
                presence_penalty=0.2,
                frequency_penalty=0.3,
            )
            
            comment = response.choices[0].message.content.strip()
            
            comment = self._simplify_comment(comment)
            
            logger.info(f"Сгенерирован комментарий: {comment}")
            return comment
            
        except Exception as e:
            logger.error(f"Ошибка при генерации комментария: {str(e)}")
            return self._generate_simple_comment(comments_text)


    def _get_average_length(self, comments: List[str]) -> int:
        if not comments:
            return 7
        
        lengths = [len(comment.split()) for comment in comments]
        return sum(lengths) // len(comments)
    
    
    def _simplify_comment(self, comment: str) -> str:
        comment = re.sub(r'[,;:"\']', '', comment)
        
        comment = re.sub(r'\s+', ' ', comment).strip()
        
        words = comment.split()
        if len(words) > 10:
            comment = ' '.join(words[:10])
        
        if random.random() < 0.7:
            comment = comment.lower()
        
        if comment.endswith('.') and random.random() < 0.7:
            comment = comment[:-1]
        
        if random.random() < 0.2 and len(comment) > 5:
            pos = random.randint(0, len(comment) - 1)
            if comment[pos].isalpha():
                comment = comment[:pos] + comment[pos+1:]
        
        return comment


    def _generate_simple_comment(self, comments_text: List[str]) -> str:
        basic_comments = [
            "agree", 
            "nice", 
            "ok", 
            "interesting", 
            "same", 
            "good", 
            "support", 
            "yes", 
            "thanks", 
            "useful", 
            "cool", 
            "+1", 
            "true", 
            "exactly", 
            "not bad",
            "got it",
            "makes sense",
            "interesting topic",
            "didnt know that",
            "yeah",
            "lol",
            "seems right",
            "good point",
            "this",
            "fair enough",
            "hmm",
            "worth a try",
            "solid",
        ]
        
        if comments_text:
            for comment in comments_text[:3]:
                if len(comment.split()) < 5 and self._is_english(comment):
                    basic_comments.append(comment.lower().strip())
        
        return random.choice(basic_comments)
    
    
    def _is_english(self, text: str) -> bool:
        return not bool(re.search('[а-яА-Я]', text))


def create_comment_generator(
    api_key: str,
    model: str = "gpt-3.5-turbo",
    proxy_config: Optional[Dict[str, str]] = None
) -> CommentGenerator:
    proxy = None
    if proxy_config:
        proxy_type = ProxyType.HTTP
        if proxy_config.get("type", "http").lower() == "socks5":
            proxy_type = ProxyType.SOCKS5
            
        proxy = ProxyConfig(
            host=proxy_config.get("host", ""),
            port=proxy_config.get("port", ""),
            username=proxy_config.get("username", ""),
            password=proxy_config.get("password", ""),
            proxy_type=proxy_type
        )
    
    return CommentGenerator(
        api_key=api_key,
        model=model,
        proxy=proxy
    )
    