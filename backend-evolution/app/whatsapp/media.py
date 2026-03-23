import httpx
from openai import AsyncOpenAI

from app.config import settings

_openai_client: AsyncOpenAI | None = None


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


async def download_media(media_url: str) -> tuple[bytes, str]:
    """Download media from URL. Returns (bytes, content_type)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(media_url)
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "application/octet-stream")


async def transcribe_audio(media_url: str) -> str:
    """Download audio and transcribe with Whisper."""
    audio_bytes, content_type = await download_media(media_url)

    ext = "ogg" if "ogg" in content_type else "mp4"
    transcript = await _get_openai().audio.transcriptions.create(
        model="whisper-1",
        file=(f"audio.{ext}", audio_bytes, content_type),
    )
    return transcript.text


async def describe_image(media_url: str) -> str:
    """Download image and describe with GPT-4o Vision."""
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
    return response.choices[0].message.content
