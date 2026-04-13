import httpx
from openai import AsyncOpenAI

from app.config import settings

_openai_client: AsyncOpenAI | None = None

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(
            api_key=settings.gemini_api_key,
            base_url=_GEMINI_BASE_URL,
        )
    return _openai_client


def _media_url() -> str:
    return f"https://graph.facebook.com/{settings.meta_api_version}"


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.meta_access_token}"}


async def download_media(media_id: str) -> tuple[bytes, str]:
    """Download media from Meta. Returns (bytes, content_type)."""
    async with httpx.AsyncClient() as client:
        # Step 1: get media URL
        resp = await client.get(f"{_media_url()}/{media_id}", headers=_headers())
        resp.raise_for_status()
        media_url = resp.json()["url"]

        # Step 2: download the file
        resp = await client.get(media_url, headers=_headers())
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "application/octet-stream")


async def transcribe_audio(media_id: str) -> str:
    """Download audio from Meta and transcribe with Whisper."""
    audio_bytes, content_type = await download_media(media_id)

    ext = "ogg" if "ogg" in content_type else "mp4"
    transcript = await _get_openai().audio.transcriptions.create(
        model="gemini-3-flash-preview",
        file=(f"audio.{ext}", audio_bytes, content_type),
    )
    return transcript.text


async def describe_image(media_id: str) -> str:
    """Download image from Meta and describe with GPT-4o Vision."""
    import base64

    image_bytes, content_type = await download_media(media_id)
    b64 = base64.b64encode(image_bytes).decode()

    response = await _get_openai().chat.completions.create(
        model="gemini-3-flash-preview",
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
