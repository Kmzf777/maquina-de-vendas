import httpx
from openai import AsyncOpenAI

from app.config import settings

_openai_client: AsyncOpenAI | None = None


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.gemini_api_key)
    return _openai_client


async def download_media(media_url: str) -> tuple[bytes, str]:
    """Download media from URL. Returns (bytes, content_type)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(media_url)
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "application/octet-stream")


async def transcribe_audio(media_url: str) -> tuple[str, dict]:
    """Download audio and transcribe with Whisper.

    Returns (transcription_text, usage_info).
    usage_info has keys: model, prompt_tokens, completion_tokens, estimated_cost
    """
    audio_bytes, content_type = await download_media(media_url)

    ext = "ogg" if "ogg" in content_type else "mp4"
    transcript = await _get_openai().audio.transcriptions.create(
        model="whisper-1",
        file=(f"audio.{ext}", audio_bytes, content_type),
    )

    # Whisper charges ~$0.006/min. Estimate 30s average per message.
    estimated_cost = 0.003

    usage_info = {
        "model": "whisper-1",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "estimated_cost": estimated_cost,
    }

    return transcript.text, usage_info


async def describe_image(media_url: str) -> tuple[str, dict]:
    """Download image and describe with GPT-4o Vision.

    Returns (description_text, usage_info).
    usage_info has keys: model, prompt_tokens, completion_tokens
    """
    import base64

    image_bytes, content_type = await download_media(media_url)
    b64 = base64.b64encode(image_bytes).decode()

    response = await _get_openai().chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Descreva esta imagem em uma frase curta em portugues. Se for uma foto de produto, descreva o produto."},
                {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{b64}"}},
            ],
        }],
        max_tokens=150,
    )

    usage_info = {
        "model": "gpt-4o",
        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
    }

    return response.choices[0].message.content, usage_info
