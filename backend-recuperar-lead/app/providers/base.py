from abc import ABC, abstractmethod


class WhatsAppProvider(ABC):
    """Abstract interface for WhatsApp messaging providers."""

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    async def send_text(self, to: str, body: str) -> dict:
        """Send a text message. Returns provider response."""

    @abstractmethod
    async def send_template(self, to: str, template_name: str,
                            language: str = "pt_BR",
                            components: list | None = None) -> dict:
        """Send a template message. Only supported by MetaCloudProvider."""

    @abstractmethod
    async def send_image(self, to: str, image_url: str,
                         caption: str | None = None) -> dict:
        """Send an image message."""

    @abstractmethod
    async def mark_read(self, message_id: str, **kwargs) -> dict:
        """Mark a message as read."""

    @abstractmethod
    async def download_media(self, media_ref: str) -> tuple[bytes, str]:
        """Download media. Returns (bytes, content_type).
        media_ref is media_id for Meta, URL for Evolution.
        """
