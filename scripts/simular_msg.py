import requests

payload = {
  "object": "whatsapp_business_account",
  "entry": [
    {
      "id": "1234567890",
      "changes": [
        {
          "field": "messages",
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {
              "display_phone_number": "553491461669",
              "phone_number_id": "1049315514934778"
            },
            "contacts": [
              {
                "profile": {
                  "name": "Teste Kelwin"
                },
                "wa_id": "5511999999999"
              }
            ],
            "messages": [
              {
                "from": "5511999999999",
                "id": "wamid.HBgL1234567890_TESTE",
                "timestamp": "1713182400",
                "text": {
                  "body": "Oi, estou testando porque o site tinha caído."
                },
                "type": "text"
              }
            ]
          }
        }
      ]
    }
  ]
}

r = requests.post("https://api.canastrainteligencia.com/webhook/meta", json=payload)
print(r.status_code, r.text)
