"""Read only explicit wall levels; builder counts cannot measure wall success."""
import re


def wall_level(texts):
    text = ' '.join(texts).casefold()
    levels = re.findall(r'\bwall\s*(?:[x×]\s*\d+\s*)?\(?\s*level\s+(\d+)\b', text)
    if len(set(levels)) != 1:
        return None
    level = int(levels[0])
    return level if 1 <= level <= 100 else None


def wall_name(texts):
    return any(re.fullmatch(r'wall(?:\s*[x×]\s*\d+)?', text.strip(), re.I) for text in texts)
