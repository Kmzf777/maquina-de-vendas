from abc import ABC, abstractmethod


class WhatsAppClient(ABC):
    """Abstract interface for WhatsApp message sending."""

    @abstractmethod
    async def send_text(self, to: str, body: str) -> dict:
        ...

    @abstractmethod
    async def send_image(self, to: str, image_url: str, caption: str | None = None) -> dict:
        ...

    @abstractmethod
    async def send_audio(self, to: str, audio_url: str) -> dict:
        ...

    @abstractmethod
    async def mark_read(self, message_id: str, remote_jid: str = "") -> dict:
        ...
