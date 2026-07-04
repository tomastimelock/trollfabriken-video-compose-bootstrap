from __future__ import annotations

import re
from pathlib import Path


def translate_srt(srt_content: str, target_language: str, model: str = "gpt-4o-mini") -> str:
    """Translate SRT subtitle content to *target_language*, preserving all timestamps."""
    blocks = _parse_srt(srt_content)
    if not blocks:
        return srt_content

    texts = [b["text"] for b in blocks]
    translated = _batch_translate(texts, target_language, model)

    out_lines: list[str] = []
    for i, block in enumerate(blocks):
        out_lines.append(str(block["index"]))
        out_lines.append(block["timing"])
        out_lines.append(translated[i] if i < len(translated) else block["text"])
        out_lines.append("")
    return "\n".join(out_lines)


def translate_srt_file(
    src_path: str | Path,
    target_language: str,
    out_path: str | Path | None = None,
    model: str = "gpt-4o-mini",
) -> Path:
    src_path = Path(src_path)
    if out_path is None:
        out_path = src_path.with_stem(src_path.stem + f"_{target_language}")
    out_path = Path(out_path)
    content = src_path.read_text(encoding="utf-8")
    translated = translate_srt(content, target_language, model)
    out_path.write_text(translated, encoding="utf-8")
    return out_path


def _parse_srt(content: str) -> list[dict]:
    blocks: list[dict] = []
    parts = re.split(r"\n\s*\n", content.strip())
    for part in parts:
        lines = part.strip().splitlines()
        if len(lines) < 3:
            continue
        try:
            idx = int(lines[0].strip())
        except ValueError:
            continue
        timing = lines[1].strip()
        text = "\n".join(lines[2:])
        blocks.append({"index": idx, "timing": timing, "text": text})
    return blocks


def _batch_translate(texts: list[str], language: str, model: str) -> list[str]:
    from auth_api_key import get_key
    import openai

    client = openai.OpenAI(api_key=get_key("OPENAI_API_KEY"))
    joined = "\n---\n".join(texts)
    system = (
        f"You are a professional subtitle translator. "
        f"Translate each segment to {language}. "
        "Return the same number of segments separated by lines of exactly '---'. "
        "Preserve line breaks within segments. Do NOT add or remove segments."
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": joined}],
        temperature=0.2,
    )
    result = response.choices[0].message.content or ""
    return [s.strip() for s in result.split("---")]
