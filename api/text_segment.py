from typing import List


def split_text(text: str, max_length: int = 100) -> List[str]:
    if len(text) <= max_length:
        return [text]
    separators = [". ", "! ", "? ", "; ", ", ", " ", "。", "！", "？", "；", "，"]
    segments = []
    while len(text) > max_length:
        segment_end = -1
        for sep in separators:
            pos = text[:max_length].rfind(sep)
            if pos > 0:
                segment_end = pos + len(sep)
                break
        if segment_end == -1:
            pos = text[:max_length].rfind(" ")
            if pos > 0:
                segment_end = pos + 1
            else:
                segment_end = max_length
        segments.append(text[:segment_end].strip())
        text = text[segment_end:].strip()
    if text:
        segments.append(text)
    return segments
