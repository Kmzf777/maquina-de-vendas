from abc import ABC, abstractmethod


class WhatsAppProvider(ABC):
    """Abstract interface for WhatsApp message delivery."""

    @abstractmethod
    async def send_text(self, to: str, body: str) -> dict: ...

    @abstractmethod
    async def send_image(self, to: str, image_url: str, caption: str | None = None) -> dict: ...

    @abstractmethod
    async def send_image_base64(self, to: str, base64_data: str, mimetype: str = "image/jpeg", caption: str | None = None) -> dict: ...

    @abstractmethod
    async def send_audio(self, to: str, audio_url: str) -> dict: ...

    @abstractmethod
    async def send_template(self, to: str, template_name: str, components: dict | None = None, language_code: str = "pt_BR") -> dict: ...

    async def send_contact(self, to: str, contact_name: str, contact_phone: str) -> dict:
        """Envia um cartão de contato (vCard) ao lead.

        Método concreto com default não-suportado: apenas os provedores ativos
        (Meta) e o mock o sobrescrevem — o provedor Evolution (descontinuado) herda
        este default e não precisa implementar.
        """
        raise NotImplementedError(f"{type(self).__name__} não suporta send_contact")

    @abstractmethod
    async def mark_read(self, message_id: str, remote_jid: str = "") -> dict: ...

    async def send_typing_indicator(self, message_id: str) -> dict:
        """Mostra "digitando…" ao lead (default não-suportado).

        Como send_contact: apenas os provedores ativos (Meta) e o mock o sobrescrevem;
        provedores descontinuados (Evolution) herdam este default.
        """
        raise NotImplementedError(f"{type(self).__name__} não suporta send_typing_indicator")
