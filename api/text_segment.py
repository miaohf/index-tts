from typing import List


def _merge_short_tail(segments: List[str], max_length: int) -> List[str]:
    if len(segments) < 2:
        return segments

    min_tail_length = min(24, max(1, max_length // 4))
    tail = segments[-1]
    merged_length = len(segments[-2]) + 1 + len(tail)
    if len(tail) < min_tail_length and merged_length <= max_length + min_tail_length:
        return [*segments[:-2], f"{segments[-2]} {tail}".strip()]
    return segments


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
    return _merge_short_tail(segments, max_length)
