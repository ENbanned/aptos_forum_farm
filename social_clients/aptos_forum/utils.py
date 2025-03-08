import re
from typing import Any, Dict, Optional

import html2text


def extract_text_from_html(html: Optional[str]) -> str:
    if not html:
        return ""
    
    converter = html2text.HTML2Text()
    converter.ignore_links = True
    converter.ignore_images = True
    converter.ignore_emphasis = True
    text = converter.handle(html)
    
    text = re.sub(r'\n{2,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    
    return text.strip()


def is_success_response(response: Dict[str, Any], action_type: str) -> bool:
    if action_type == "like":
        actions = response.get('actions_summary', [])
        return any(action.get('id') == 2 and action.get('acted', False) for action in actions)
    elif action_type == "comment":
        return response.get('success', False)
    return False
