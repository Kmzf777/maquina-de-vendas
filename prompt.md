me ajude a montar uma mensagem de utilidade para meu vendedor: Modelos de utilidade, o seguinte texto é a documentação da meta sobre utilidade, entenda os fundamentos para conseguir criar uma que é utilidade:
Updated: 21 de mai de 2026
Este documento descreve como criar e enviar modelos de utilidade.
Normalmente, os modelos de utilidade são enviados em resposta a uma ação ou solicitação do usuário, como uma atualização ou confirmação de pedido.
Os modelos de utilidade têm requisitos de conteúdo rigorosos, sobretudo em relação a materiais de marketing. Se você tentar criar ou atualizar um modelo de utilidade com material de marketing, ele será automaticamente recategorizado como modelo de marketing.
Para ver as diretrizes de conteúdo, consulte a documentação sobre categorização de modelos.
Componentes com suporte

Os modelos de utilidade oferecem suporte para os seguintes componentes:
1 cabeçalho (opcional; todos os tipos aceitos)
1 corpo
1 rodapé (opcional)
Até 10 botões (opcional). Tipos com suporte:Solicitação de ligação
Copiar código
Telefone
Respostas rápidas
URL
Criar um modelo de utilidade

Sintaxe da solicitação

Use a API de Modelos de Mensagens para criar um modelo de utilidade.
curl 'https://graph.facebook.com/<API_VERSION>/<WHATSAPP_BUSINESS_ACCOUNT_ID>/message_templates' \-H 'Content-Type: application/json' \-H 'Authorization: Bearer <ACCESS_TOKEN>' \-d '
{
  "name": "<TEMPLATE_NAME>",
  "language": "<TEMPLATE_LANGUAGE>",
  "category": "utility",
  "parameter_format": "<PARAMETER_FORMAT>",
  "components": [

    <!-- header component optional -->
    {
      "type": "header",
      "format": "<HEADER_TYPE>",
      "example": {
        "header_handle": [
          "<HEADER_HANDLE>"
        ]
      }
    },

    <!-- body component required -->
    {
      "type": "body",
      "text": "<BODY_TEXT>",

      <!-- example required if <BODY_TEXT> contains one or more parameters -->
      "example": {
        "body_text_named_params": [
          {
            "param_name": "<PARAMETER_NAME>",
            "example": "<PARAMETER_EXAMPLE_VALUE>"
          },

          <!-- additional parameters would follow, if using multiple parameters -->
        ]
      }
    },

    <!-- footer component optional -->
    {
      "type": "footer",
      "text": "<FOOTER_TEXT>"
    },

    <!-- button components optional -->
    {
      "type": "buttons",
      "buttons": [
        {
          "type": "url",
          "text": "<URL_BUTTON_LABEL_TEXT>",
          "url": "<URL>"
        },
        {
          "type": "phone_number",
          "text": "<PHONE_BUTTON_LABEL_TEXT>",
          "phone_number": "<PHONE_NUMBER>"
        },
        {
          "type": "quick_reply",
          "text": "<QUICK_REPLY_BUTTON_LABEL_TEXT>"
        }
      ]
    }
  ]
}'

Parâmetros de solicitação

Espaço reservadoDescriçãoValor de exemplo<ACCESS_TOKEN>
String
Obrigatório.
Token do sistema ou token da empresa.
EAAA...
<API_VERSION>
String
Opcional.
Versão da Graph API.
v25.0
<BODY_TEXT>
String
Obrigatório.

Texto do corpo do modelo. Variáveis têm suporte

Máximo de 1.024 caracteres.
You're all set! Your reservation for {{number_of_guests}} at Lucky Shrub Eatery on {{day}}, {{date}}, at {{time}}, is confirmed. See you then!
<FOOTER_TEXT>
String
Opcional.
Texto de rodapé do modelo. Variáveis têm suporte
Máximo de 60 caracteres.
Lucky Shrub Eatery: The Luckiest Eatery in Town!
<HEADER_ASSET_HANDLE>
String
Obrigatório se um cabeçalho com ativo de mídia for usado.
O nome de usuário do ativo de mídia de exemplo carregado na sua conta do WhatsApp Business.
Máximo de 60 caracteres.
4::aW1hZ2UvcG5n:ARYpf5zqqUjggwGfsZOJ2_o26Zs8ntcO2mss2vKpFb8P_IvskL043YXKpehYTD7IxqEB4t-uZcIzOTxOFRavEcN_tZLhk1WXFb3IOr4S8UKJcQ:e:1759093121:634974688087057:100089620928913:ARYyOAh63uQLhDpqOdk\n4::aW1hZ2UvcG5n:ARZW8t9-cBNjpdmxV5Z9wcRAMhfmw4ATpJcJiHT0nY62hXq4ppOeBaTWaGI0IwX-twF2IkeKo-_MyW2pEDuBAE5vyw2oHTNgPZQkntclrgWMGg:e:1759093121:634974688087057:100089620928913:ARZE4NC5MrxnZUe5GRw
<HEADER_TYPE>
String
Obrigatório se um cabeçalho for usado.
Formato do cabeçalho. Os valores podem ser os seguintes:
documentação
imagem
location
text
um vídeo
image
<PARAMETER_EXAMPLE_VALUE>
String
Obrigatório se você usar uma string de componente de corpo que inclua um ou mais parâmetros.
Exemplo de valor do parâmetro. É preciso fornecer um exemplo para cada parâmetro definido na string do componente do corpo.
Saturday
<PARAMETER_NAME>
String
Obrigatório ao usar parâmetros nomeados.
Deve ser uma string única, composta por caracteres em letra minúscula e sublinhados, expressa entre chaves.
{{day}}
<PHONE_BUTTON_LABEL_TEXT>
String
Obrigatório ao usar um botão de número de telefone.
Texto do rótulo do botão.
Máximo de 25 caracteres. Apenas caracteres alfanuméricos.
Change reservation
<PHONE_NUMBER>
String
Obrigatório se você estiver usando um componente de botão de número de telefone.
O número de telefone comercial para o qual a ligação será feita no app de telefone padrão do usuário do WhatsApp quando ele tocar no botão.
Alguns países têm números de telefone especiais que incluem zeros após o código de país (por exemplo, +55-0-955-585-95436). Se você atribuir um números nesse formato, o zero à esquerda será retirado do número. Se o número não funcionar sem o zero, atribua um número alternativo ao botão ou adicione o número como mensagem
Máximo de 20 caracteres. Apenas caracteres alfanuméricos.
15550051310
<QUICK_REPLY_BUTTON_LABEL_TEXT>
Obrigatório ao usar um botão de resposta rápida.
Texto do rótulo do botão.
Máximo de 25 caracteres. Apenas caracteres alfanuméricos.
Cancel reservation
<TEMPLATE_LANGUAGE>
String
Obrigatório.
O código de idioma do modelo.
en_US
<TEMPLATE_NAME>
String
Obrigatório.
Nome do modelo. Deve ser único, a menos que modelos existentes com o mesmo nome tenham outro idioma.
Máximo de 512 caracteres. Apenas caracteres alfanuméricos em letra minúscula e sublinhados.
reservation_confirmation
<URL>
String
Obrigatório se incluir um botão de URL.
URL a ser carregado no navegador padrão do usuário do WhatsApp quando tocado.
https://www.luckyshrubeater.com/reservations
<URL_BUTTON_LABEL_TEXT>
String
Obrigatório ao usar um botão de URL.
Texto do rótulo do botão.
Máximo de 25 caracteres. Apenas caracteres alfanuméricos.
Change reservation
<WHATSAPP_BUSINESS_ACCOUNT_ID>
Obrigatório.
Identificação da conta do WhatsApp Business.
546151681022936
Sintaxe da resposta

Caso a solicitação seja bem-sucedida:
{
  "id": "<TEMPLATE_ID>",
  "status": "<TEMPLATE_STATUS>",
  "category": "<TEMPLATE_CATEGORY>"}

Parâmetros da resposta

Espaço reservadoDescriçãoValor de exemplo<TEMPLATE_CATEGORY>
Categoria do modelo.
UTILITY
<TEMPLATE_ID>
ID do modelo.
546151681022936
<TEMPLATE_STATUS>
Status do modelo.
PENDING
Exemplo de pedido

Este exemplo de solicitação cria um modelo de utilidade com as seguintes características:
um componente de cabeçalho da imagem
um componente de corpo com uma string contendo 4 parâmetros nomeados
um componente de rodapé
um componente de botão de URL
um componente de botão de número de telefone
um componente de botão de resposta rápida
curl 'https://graph.facebook.com/v23.0/102290129340398/message_templates' \-H 'Content-Type: application/json' \-H 'Authorization: Bearer EAAJB...' \-d '
{
  "name": "reservation_confirmation",
  "language": "en_US",
  "category": "utility",
  "parameter_format": "named",
  "components": [
    {
      "type": "header",
      "format": "image",
      "example": {
        "header_handle": [
          "4::aW..."
        ]
      }
    },
    {
      "type": "body",
      "text": "*You're all set!*\n\nYour reservation for {{number_of_guests}} at Lucky Shrub Eatery on {{day}}, {{date}}, at {{time}}, is confirmed. See you then!",
      "example": {
        "body_text_named_params": [
          {
            "param_name": "number_of_guests",
            "example": "4"
          },
          {
            "param_name": "day",
            "example": "Saturday"
          },
          {
            "param_name": "date",
            "example": "August 30th, 2025"
          },
          {
            "param_name": "time",
            "example": "7:30 pm"
          }
        ]
      }
    },
    {
      "type": "footer",
      "text": "Lucky Shrub Eatery: The Luckiest Eatery in Town!"
    },
    {
      "type": "buttons",
      "buttons": [
        {
          "type": "url",
          "text": "Change reservation",
          "url": "https://www.luckyshrubeater.com/reservations"
        },
        {
          "type": "phone_number",
          "text": "Call us",
          "phone_number": "+15550051310"
        },
        {
          "type": "quick_reply",
          "text": "Cancel reservation"
        }
      ]
    }
  ]}'

Exemplo de resposta

{
  "id": "546151681022936",
  "status": "PENDING",
  "category": "UTILITY"
}

Enviar um modelo de utilidade

Sintaxe da solicitação

Use a API de Mensagens para enviar um modelo de utilidade aprovado em uma mensagem de modelo.
curl 'https://graph.facebook.com/<API_VERSION>/<WHATSAPP_BUSINESS_PHONE_NUMBER_ID>/messages' \-H 'Content-Type: application/json' \-H 'Authorization: Bearer <ACCESS_TOKEN>' \-d '
{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "to": "<WHATSAPP_USER_PHONE_NUMBER>",
  "type": "template",
  "template": {
    "name": "<TEMPLATE_NAME>",
    "language": {
      "code": "<TEMPLATE_LANGUAGE>"
    },
    "components": [

      <!-- Only required if the template uses a media header component -->
      {
        "type": "header",
        "parameters": [
          {
            "type": "<MEDIA_HEADER_TYPE>",
            "<MEDIA_HEADER_TYPE>": {
              "id": "<MEDIA_HEADER_ASSET_ID>"
            }
          }
        ]
      },

      <!-- Only required if the template uses body component parameters -->
      {
        "type": "body",
        "parameters": [
          {
            "type": "<NAMED_PARAM_TYPE>",
            "parameter_name": "<NAMED_PARAM_NAME>",
            "text": "<NAMED_PARAM_VALUE>"
          },

          <!-- Additional parameters values would follow, if needed -->

        ]
      }
    ]
  }
}'

Parâmetros de solicitação

Espaço reservadoDescriçãoValor de exemplo<ACCESS_TOKEN>
String
Obrigatório.
Token do sistema ou token da empresa.
EAAA...
<API_VERSION>
String
Opcional.
Versão da API. Em caso de omissão, o padrão será a versão da API mais recente disponível para o seu app.
v25.0
<MEDIA_HEADER_ASSET_ID>
String
Obrigatório se o modelo usar um componente de cabeçalho com mídia.
2871834006348767
<MEDIA_HEADER_TYPE>
String
Obrigatório se o modelo usar um componente de cabeçalho com mídia.
Tipo de cabeçalho com mídia. Os valores podem ser os seguintes:
document
imagem
um vídeo
Observe que esse espaço reservado aparece duas vezes na sintaxe da solicitação acima.
image
<NAMED_PARAM_NAME>
Obrigatório se o modelo usar parâmetros de componente de corpo.
Nome do parâmetro conforme definido na string de texto do componente do corpo do modelo.
number_of_guests
<NAMED_PARAM_TYPE>
Obrigatório se o modelo usar parâmetros de componente de corpo.
Tipo de parâmetro. Defina como texto.
text
<NAMED_PARAM_VALUE>
Obrigatório se o modelo usar parâmetros de componente de corpo.
Valor do parâmetro.
4
<TEMPLATE_LANGUAGE>
String
Obrigatório.
O código de idioma do modelo.
en_US
<TEMPLATE_NAME>
String
Obrigatório.
Nome do modelo. Deve ser único, a menos que modelos existentes com o mesmo nome tenham outro idioma.
Máximo de 512 caracteres. Apenas caracteres alfanuméricos em letra minúscula e sublinhados.
reservation_confirmation
<WHATSAPP_BUSINESS_ACCOUNT_ID>
Obrigatório.
Identificação da conta do WhatsApp Business.
546151681022936
<WHATSAPP_USER_PHONE_NUMBER>
Obrigatório.
Número de telefone do usuário do WhatsApp.
16505551234
Sintaxe da resposta

Caso a solicitação seja bem-sucedida:
{
  "messaging_product": "whatsapp",
  "contacts": [
    {
      "input": "<WHATSAPP_USER_PHONE_NUMBER>",
      "wa_id": "<WHATSAPP_USER_ID>"
    }
  ],
  "messages": [
    {
      "id": "<WHATSAPP_MESSAGE_ID>",
      "message_status": "<PACING_STATUS>"
    }
  ]}

Parâmetros da resposta

Espaço reservadoDescriçãoValor de exemplo<PACING_STATUS>
Status de regularidade do modelo.
accepted
<WHATSAPP_MESSAGE_ID>
Identificação da mensagem do WhatsApp.
Essa identificação é incluída em webhooks de status mensagens para fins de verificação de entrega.
wamid.HBgLMTY1MDM4Nzk0MzkVAgARGBJBRkJENzExMTRFRjk2NTI1OTEA
<WHATSAPP_USER_ID>
ID do usuário do WhatsApp. Pode não corresponder ao valor de entrada.
16505551234
<WHATSAPP_USER_PHONE_NUMBER>
O número de telefone do WhatsApp do usuário. Pode não corresponder ao valor de wa_id.
16505551234
Exemplo de pedido

Veja um exemplo de solicitação que envia o modelo criado no exemplo de solicitação de criação de modelo exibida acima.
curl 'https://graph.facebook.com/v23.0/106540352242922/messages' \-H 'Content-Type: application/json' \-H 'Authorization: Bearer EAAJB...' \-d '
{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "to": "16505551234",
  "type": "template",
  "template": {
    "name": "reservation_confirmation",
    "language": {
      "code": "en_US"
    },
    "components": [
      {
        "type": "header",
        "parameters": [
          {
            "type": "image",
            "image": {
              "id": "2871834006348767"
            }
          }
        ]
      },
      {
        "type": "body",
        "parameters": [
          {
            "type": "text",
            "parameter_name": "number_of_guests",
            "text": "4"
          },
          {
            "type": "text",
            "parameter_name": "day",
            "text": "Saturday"
          },
          {
            "type": "text",
            "parameter_name": "date",
            "text": "August 30th, 2025"
          },
          {
            "type": "text",
            "parameter_name": "time",
            "text": "7:30 pm"
          }
        ]
      }
    ]
  }
}'

Exemplo de resposta

{
  "messaging_product": "whatsapp",
  "contacts": [
    {
      "input": "16505551234",
      "wa_id": "16505551234"
    }
  ],
  "messages": [
    {
      "id": "wamid.HBgLMTY1MDM4Nzk0MzkVAgARGBJBRkJENzExMTRFRjk2NTI1OTEA",
      "message_status": "accepted"
    }
  ]
}

A SEGUINTE DOCUMENTAÇÃO É A DE TEMPLATE DE MARKETING, A MENSAGEM NÃO PODE SE PARECER COM O TEMPLATE DE MARKETING SENÃO A META MUDA; E EU NAO QUERO MSG DE MARKETING QUERO DE UTILIDADE: Como enviar mensagens de marketing
Updated: 5 de mai de 2026
A API de Mensagens de Marketing para o WhatsApp só permite enviar mensagens de modelo de marketing. Para enviar outros tipos de mensagem ou receber mensagens, use a API de Nuvem em paralelo com a API de Mensagens de Marketing para o WhatsApp no mesmo número de telefone comercial.
Se você usar os portais de interface do usuário ou as APIs de um parceiro para configurar e enviar mensagens de marketing, poderá continuar fazendo isso sem precisar usar os recursos descritos nesse documento, já que seu parceiro fará a integração com as funções de envio de mensagens da API de MM para o WhatsApp em seu nome.
Pré-requisitos

Antes de enviar mensagens de marketing usando a API de Mensagens de Marketing para o WhatsApp, faça o seguinte:
Uma conta do WhatsApp Business (WABA) com a integração da API de MM para WhatsApp concluída.
Pelo menos um número de telefone comercial registrado associado à sua WABA
Pelo menos um modelo de marketing aprovado
Um token de acesso com a permissão whatsapp_business_messaging
Uma integração com o Pixel da Meta ou a API de Conversões (obrigatório para a mensuração de conversões)
Como criar modelos de marketing

Você pode criar modelos de marketing de várias maneiras:
Use a interface do Gerenciador do WhatsApp Business.
Use o ponto de extremidade "Modelos de mensagem" da API de Gerenciamento do WhatsApp Business
Caso você trabalhe com um parceiro, ele poderá oferecer APIs ou interfaces do usuário para a criação de modelos, que aproveitam o ponto de extremidade "Modelos de mensagem"
Consulte a documentação sobre como criar e gerenciar modelos.
Quando você cria um novo modelo de marketing, a sincronização com a conta de anúncios correspondente pode levar até 10 minutos. Essa sincronização permite a otimização de mensagens e a mensuração de cliques e conversões posteriores.
Os modelos que ficarem inativos por mais de 7 dias também precisarão de 10 minutos para sincronização após o primeiro uso. Depois de criar um novo modelo de marketing ou reativar modelos inativos, espere 10 minutos antes de enviar tráfego de marketing.
A API de Mensagens de Marketing para o WhatsApp é compatível com todos os modelos de marketing. Além disso, a API de Mensagens de Marketing para o WhatsApp fornece os seguintes recursos adicionais que não estão disponíveis para modelos de marketing na API de Nuvem:
Tempo de vida para mensagens de modelo de marketing: se a Meta não conseguir entregar uma mensagem a um usuário do WhatsApp, novas tentativas de entrega serão feitas por um período conhecido como tempo de vida (TTL) ou período de validade da mensagem. O TTL é aplicado a mensagens que usam modelos de autenticação e utilidade na API de Nuvem. No entanto, para mensagens que usam modelos de marketing, esse recurso está disponível somente na API de MM para o WhatsApp. Para saber mais sobre a definição de TTLs em mensagens de modelo de marketing, consulte a documentação sobre como criar e gerenciar modelos via API ou como definir um período de validade de mensagem personalizado via interface do usuário⁠.
Otimizações automáticas de criativos

As otimizações automáticas de criativos testam variações com diferentes tratamentos e otimizam as mensagens de marketing com base em práticas observadas em criativos de alto desempenho. É possível desabilitar o recurso usando a desativação no nível do modelo ou a desativação no nível da conta do WhatsApp Business, o que proporciona flexibilidade e controle sobre a aplicação dos aprimoramentos de criativos. Essas otimizações são semelhantes ao criativo Advantage+⁠ para anúncios.
As otimizações automáticas de criativos, como extração e destaque de texto, geraram um aumento médio de 13,9%* nas taxas de cliques (CTR).
Esse recurso inclui variabilidade criativa para otimização do desempenho, ou seja, a saída pode ser diferente para mensagens com a mesma entrada. O recurso testa pequenas variações do seu cabeçalho de imagem e seleciona automaticamente a variante que gera a maior taxa de cliques ao longo do tempo, sem que você precise fazer nenhuma intervenção. Estamos sempre explorando e testando novas otimizações automáticas de criativos para ajudar a maximizar o desempenho da sua campanha. À medida que novas variações ficam disponíveis, elas podem ser aplicadas a modelos aceitos para gerar melhores resultados comerciais.
Filtragem de imagem

Em algumas campanhas, a Meta aplica automaticamente os filtros mais eficazes às imagens de cabeçalho para melhorar a qualidade e o apelo visual:
Extração do título

Em algumas campanhas, a Meta vai extrair palavras-chave ou frases da sua mensagem para criar um título para o texto do corpo, buscando destacar informações importantes.
Extração de título para área de toque

Em algumas campanhas, a Meta vai extrair palavras-chave ou frases da sua mensagem para criar um título para a área de toque, buscando destacar informações importantes.
Formatação de texto

Em algumas campanhas, a Meta atualiza a formatação do texto (por exemplo, removendo espaços desnecessários e frases em negrito) para melhorar o desempenho e a legibilidade da mensagem. O conteúdo do texto não é alterado, apenas o formato.
Em breve

Estamos sempre explorando e testando novas otimizações automáticas de criativos para ajudar a maximizar o desempenho da sua campanha. Esperamos disponibilizar esses aprimoramentos no futuro, mas nossos planos estão sujeitos a alterações.
Extensões de produto

Aprimoraremos os criativos de imagem única anexando um conjunto de produtos adicionais do catálogo com os quais os usuários provavelmente interagirão ou converterão, criando experiências mais personalizadas e relevantes.
Tag de promoção automática

Para algumas campanhas, a Meta extrairá automaticamente a tag de promoção (como "30% off", "50% de desconto", "Frete grátis") das mensagens para criar uma tag de promoção e colocá-la na imagem para destacar informações promocionais.
Banner de imagem

Em algumas campanhas, a Meta aplicará preenchimentos coloridos para transformar o criativo da imagem na taxa de proporção ideal a fim de melhorar o apelo visual e a digestibilidade da mídia.
CTA dinâmica

Em algumas campanhas, a Meta personalizará dinamicamente o texto da CTA para que ele corresponda à proposta de valor da mensagem ou do URL, aumentando o engajamento por meio da relevância.
Formatação de hiperlink

Em algumas campanhas, a Meta detectará frases relevantes para promoção (como descontos, ofertas e incentivos) e as converterá em um hiperlink direcionado à CTA ou transformará os links de URL no corpo da mensagem encurtando o link ou aplicando formatação de hiperlink a frases adjacentes para melhorar a compreensão da mensagem.
Cartão final do perfil

Em algumas campanhas, a Meta pode anexar um cartão de perfil empresarial no final de uma mensagem de marketing com uma única imagem, exibindo detalhes do perfil comercial do WhatsApp para ajudar os usuários a saber mais sobre o remetente e incentivar o engajamento. O cartão final apresenta detalhes do perfil comercial que estão disponíveis publicamente, como categoria da empresa, descrição curta e URL do site.
Pausado ou descontinuado

Pausamos as otimizações automáticas de criativos a seguir. Por isso, não espere que elas sejam aplicadas às suas mensagens de marketing. Atualizaremos a documentação se reiniciarmos qualquer um destes programas no futuro:
Corte de imagem: a Meta corta automaticamente as imagens de cabeçalho para uma dimensão ideal, garantindo que seus recursos visuais estejam sempre perfeitamente enquadrados, sem cortar o texto da imagem.
Sobreposições de texto: a Meta adiciona automaticamente uma sobreposição de texto à sua imagem usando o conteúdo da mensagem.
Animação de imagem: a Meta transforma automaticamente sua imagem de cabeçalho em um GIF animado.
Geração de plano de fundo da imagem: a Meta gera automaticamente um novo plano de fundo para a imagem.
Notas de rodapé

*Essa descoberta se baseia em um teste A/B realizado com mais de 50 milhões de mensagens de marketing entregues por cerca de 200 anunciantes na API de MM para o WhatsApp entre 1º de dezembro de 2025 e 7 de janeiro de 2026. O estudo comparou o CTR de mensagens com e sem otimizações de criativos automáticos aplicadas, e os resultados foram estatisticamente significativos, com 95% de confiança.
Configurar otimizações automáticas de criativos (nível do modelo)

Todos os recursos de otimização são habilitados por padrão, mas você pode usar o objeto creative_features_spec para especificar quais otimizações ativar ou desativar em um determinado modelo. Para isso, defina a propriedade enroll_status de cada otimização como OPT_IN ou OPT_OUT ao criar um novo modelo ou editar um existente.
Sintaxe da solicitação

Use a API de Modelos de Mensagem para configurar otimizações automáticas de criativos no nível do modelo.
POST /<WHATSAPP_BUSINESS_ACCOUNT_ID>/message_templates{
  "name": "<TEMPLATE_NAME>",
  "language": "<TEMPLATE_LANGUAGE_AND_LOCALE_CODE>",
  "components": [<TEMPLATE_COMPONENTS>],
  "degrees_of_freedom_spec": {
    "creative_features_spec": {
      "image_brightness_and_contrast": {
        "enroll_status": "OPT_OUT"
      },
      "image_touchups": {
        "enroll_status": "OPT_IN"
      },
      "add_text_overlay": {
        "enroll_status": "OPT_OUT"
      },
      "image_animation": {
        "enroll_status": "OPT_IN"
      },
      "image_background_gen": {
        "enroll_status": "OPT_IN"
      },
      "auto_promotion_tag": {
        "enroll_status": "OPT_IN"
      },
     "text_extraction_for_headline": {
       "enroll_status": "OPT_IN"
     },
     "text_extraction_for_tap_target": {
       "enroll_status": "OPT_IN"
     },
      "product_extensions": {
        "enroll_status": "OPT_OUT"
      },
      "text_formatting_optimization": {
        "enroll_status": "OPT_OUT"
      }
    }
  }}

Use a API de Modelos para recuperar os status de otimizações automáticas de criativos no nível do modelo.
Sintaxe da solicitação

GET /<TEMPLATE_ID>?fields=degrees_of_freedom_spec

Exemplo de resposta

{
  "degrees_of_freedom_spec": {
    "creative_features_spec": [
      {
        "key": "IMAGE_BRIGHTNESS_AND_CONTRAST",
        "value": { "enroll_status": "OPT_OUT" }
      },
      {
        "key": "IMAGE_TOUCHUPS",
        "value": { "enroll_status": "OPT_OUT" }
      },
      {
        "key": "ADD_TEXT_OVERLAY",
        "value": { "enroll_status": "OPT_IN" }
      },
      {
        "key": "IMAGE_ANIMATION",
        "value": { "enroll_status": "OPT_OUT" }
      },
      {
        "key": "IMAGE_BACKGROUND_GEN",
        "value": { "enroll_status": "OPT_OUT" }
      },
      {
        "key": "AUTO_PROMOTION_TAG",
        "value": { "enroll_status": "OPT_OUT" }
      },
      {
        "key": "TEXT_EXTRACTION_FOR_HEADLINE",
        "value": { "enroll_status": "OPT_OUT" }
      },
      {
        "key": "TEXT_EXTRACTION_FOR_TAP_TARGET",
        "value": { "enroll_status": "OPT_OUT" }
      },
      {
        "key": "PRODUCT_EXTENSIONS",
        "value": { "enroll_status": "OPT_IN" }
      },
      {
        "key": "TEXT_FORMATTING_OPTIMIZATION",
        "value": { "enroll_status": "OPT_IN" }
      }
    ]
  },
  "id": "123456789"
}

Configurar otimizações automáticas de criativos (nível da conta do WhatsApp Business)

Todos os recursos de otimização são habilitados por padrão, mas você pode usar o objeto creative_features_spec para especificar quais otimizações deseja ativar ou desativar para a conta inteira do WhatsApp Business. Para isso, defina a propriedade enroll_status de cada otimização que você quer modificar como OPT_IN ou OPT_OUT.
Sintaxe da solicitação

Use a API da Conta do WhatsApp Business para configurar otimizações automáticas de criativos no nível da conta do WhatsApp Business.
POST /<WHATSAPP_BUSINESS_ACCOUNT_ID>{
  "degrees_of_freedom_spec": {
    "creative_features_spec": {
      "image_touchups": {
        "enroll_status": "OPT_IN"
      },
      "image_animation": {
        "enroll_status": "OPT_IN"
      },
      "image_brightness_and_contrast": {
        "enroll_status": "OPT_IN"
      },
      "add_text_overlay": {
        "enroll_status": "OPT_IN"
      },
      "image_background_gen": {
        "enroll_status": "OPT_IN"
      },
      "auto_promotion_tag": {
        "enroll_status": "OPT_IN"
      },
      "text_extraction_for_headline": {
        "enroll_status": "OPT_IN"
      },
      "product_extensions": {
        "enroll_status": "OPT_IN"
      },
      "text_extraction_for_tap_target": {
        "enroll_status": "OPT_IN"
      },
      "text_formatting_optimization": {
        "enroll_status": "OPT_OUT"
      }
    }
  }}

Sintaxe da solicitação

Use a API da Conta do WhatsApp Business para recuperar os status de otimizações automáticas de criativos no nível da conta do WhatsApp Business.
GET /<WHATSAPP_BUSINESS_ACCOUNT_ID>?fields=degrees_of_freedom_spec

Exemplo de resposta

{
  "degrees_of_freedom_spec": {
    "data": [
      {
        "creative_features_spec": [
          {
            "image_brightness_and_contrast": "OPT_IN",
            "image_touchups": "OPT_IN",
            "add_text_overlay": "OPT_IN",
            "image_animation": "OPT_IN",
            "image_background_gen": "OPT_IN",
            "auto_promotion_tag": "OPT_IN",
            "text_extraction_for_headline": "OPT_IN",
            "product_extensions": "OPT_IN",
            "text_extraction_for_tap_target": "OPT_IN",
            "text_formatting_optimization": "OPT_IN"
          }
        ]
      }
    ]
  },
  "id": "1234567890"
}

Outras otimizações

Truncamento de texto

A Meta truncará o texto em um número de linhas específico para melhorar o desempenho. Nenhum contexto do texto é alterado e o texto original ainda pode ser acessado por meio do botão "Ler mais". As regras exatas para truncamento de número de linhas são as seguintes:
Mensagens sem CTA, mas com um link no corpo (substitui as regras abaixo): truncadas em 5 linhas
Mensagens com cabeçalho de mídia (Imagem, Vídeo, Documento, Localização e GIF): truncadas em 3 linhas
Mensagens sem cabeçalho (ou seja, SMS): truncadas em 4 linhas
Como enviar mensagens de modelo de marketing

O envio de mensagens segue a mesma sintaxe de carga da API usada para enviar mensagens na API de Nuvem e exige as mesmas permissões.
O ponto de extremidade /marketing_messages aceita apenas mensagens de modelo de marketing para a API de MM para o WhatsApp e a API de Nuvem. Todos os outros tipos de mensagem (formato livre, autenticação, serviço, utilidade) não são aceitos e resultarão em erro.
As mensagens de marketing só enviadas pela API de MM apenas para o WhatsApp quando o cliente empresarial tiver atendido a todos os requisitos de integração. Se os requisitos de integração não forem atendidos, as mensagens de marketing ainda serão encaminhadas pela API de Nuvem. Para desabilitar a opção de direcionar para a API de Nuvem, defina o campo opcional product_policy como STRICT
Observação: você ainda pode usar o ponto de extremidade /messages para enviar mensagens de marketing por meio da API de Nuvem, a menos que tenha desabilitado as mensagens de marketing na API de Nuvem.
Ponto de extremidadeAutenticação/PHONE_NUMBER_ID/marketing_messages
Os desenvolvedores podem autenticar as chamadas de API com o token de acesso gerado no Painel de Apps > WhatsApp > Configuração da API.
Caso você seja um provedor de serviços de mensagens comerciais, faça a autenticação usando um token de acesso com a permissão whatsapp_business_messaging.
Sintaxe da solicitação

POST /<WHATSAPP_BUSINESS_PHONE_NUMBER_ID>/marketing_messages{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "to": "<WHATSAPP_USER_PHONE_NUMBER>",
  "type": "<MESSAGE_TYPE>",
  "<MESSAGE_TYPE>": {
    <MESSAGE_CONTENTS>
  },
  <!-- Optional -->
  "product_policy": "<PRODUCT_POLICY>",
  "message_activity_sharing": <SHARE_MESSAGING_ACTIVITY?>}

A API de MM para o WhatsApp oferece os recursos adicionais a seguir que não estão disponíveis para mensagens de modelo de marketing na API de Nuvem:
Política de fallback de produto: defina product_policy como CLOUD_API_FALLBACK para que a API envie a mensagem pela API de Nuvem se os requisitos de integração não tiverem sido atendidos. Defina como STRICT se não quiser que a API envie a mensagem pela API de Nuvem como fallback.
Compartilhamento de atividades de mensagens:message_activity_sharing é um parâmetro opcional no nível da mensagem que ativa ou desativa o compartilhamento de atividades de mensagens com a Meta (por exemplo, leitura da mensagem) para ajudar a otimizar as mensagens de marketing. Se o parâmetro não for fornecido, será aplicada a configuração padrão no nível da conta do WhatsApp Business. Sempre que quiser, você pode editar sua configuração padrão nas configurações do negócio (consulte o registro de alterações para encontrar uma captura de tela).
Para saber mais, leia a documentação da API de Nuvem sobre tipos de mensagem, já que a API de MM para o WhatsApp usa a mesma formatação de envio.
Enviar a um BSUID (ID do usuário no escopo da empresa)

A API de Mensagens de Marketing para o WhatsApp oferece suporte ao envio de mensagens usando um número de telefone, um BSUID (ou BSUID principal) ou ambos. Recomendamos enviar para números de telefone quando disponível, principalmente para continuar recebendo números de telefone em webhooks. Consulte Identificações do usuário no escopo do negócio para obter uma visão geral dos BSUIDs.
Solicitação

curl 'https://graph.facebook.com/<API_VERSION>/<BUSINESS_PHONE_NUMBER_ID>/marketing_messages' \-H 'Content-Type: application/json' \-H 'Authorization: Bearer <ACCESS_TOKEN>' \-d '
{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "to": "<USER_PHONE_NUMBER>",
  "recipient": "<BSUID>",
  "type": "template",
  "template": {
    <EXPECTED_TEMPLATE_PARAMETERS>
  }
}'

Referência de campo

CampoMudançaDescriçãoto
Agora é opcional
Número de telefone do usuário do WhatsApp (individual) ou ID do grupo (grupo). Se fornecido, terá precedência sobre recipient.
recipient
Novo (opcional)
O BSUID do usuário ou o BSUID principal para mensagens individuais. Usado somente quando to é omitido.
Precedência e validação

É preciso fornecer pelo menos um dos parâmetros to ou recipient. As solicitações que omitirem ambos falharão.
Se os dois forem fornecidos, to (número de telefone) será usado para processamento e entrega, e recipient será ignorado.
O envio por BSUID desabilita a otimização de entrega da API de Mensagens de Marketing Lite para esse envio. Veja as limitações abaixo.
Resposta

A resposta adiciona um campo user_id e altera a semântica de input e wa_id:
{
  "messaging_product": "whatsapp",
  "contacts": [
    {
      "input": "<USER_PHONE_NUMBER_OR_BSUID>",
      "wa_id": "<USER_PHONE_NUMBER>",
      "user_id": "<BSUID>"
    }
  ],
  "messages": [
    {
      "id": "<WHATSAPP_MESSAGE_ID>"
    }
  ]}

CampoDescriçãoinput
O número de telefone do usuário, se a mensagem for enviada por número de telefone, o BSUID do usuário (ou BSUID principal) se for enviada por BSUID, ou a identificação do grupo, se for enviada para um grupo.
wa_id
Número de telefone do usuário. Omitido quando a mensagem foi enviada usando um BSUID.
user_id
O BSUID do usuário (ou BSUID principal) quando a mensagem foi enviada usando um BSUID. Omitido quando apenas um número de telefone é fornecido ou quando o número de telefone e o BSUID são fornecidos.
Exemplo: enviar para número de telefone

{
  "messaging_product": "whatsapp",
  "contacts": [
    { "input": "+16505551234", "wa_id": "16505551234" }
  ],
  "messages": [
    { "id": "wamid.HBgLMTY0NjcwNDM1OTUVAgARGBI1RjQyNUE3NEYxMzAzMzQ5MkEA" }
  ]
}

Exemplo: enviar para o BSUID

{
  "messaging_product": "whatsapp",
  "contacts": [
    {
      "input": "US.13491208655302741918",
      "user_id": "US.13491208655302741918"
    }
  ],
  "messages": [
    { "id": "wamid.HBgLMTY0NjcwNDM1OTUVAgARGBI1RjQyNUE3NEYxMzAzMzQ5MkEA" }
  ]
}

Exemplo: quando o número de telefone e o BSUID são omitidos

{
  "error": {
    "message": "The parameter to is required.",
    "type": "OAuthException",
    "code": 100,
    "fbtrace_id": "ANPlYYIqhnaWG-FIJ-rABkS"
  }
}

Limitações ao enviar por BSUID

A otimização de veiculação não é aplicada. A otimização de entrega da API de Mensagens de Marketing Lite não é executada em envios realizados por BSUID.
Os preços dinâmicos (bid_spec) não são compatíveis com destinatários de BSUID. O envio de um modelo de marketing que inclui bid_spec para um destinatário BSUID retorna o código de erro 131062. Para usar bid_spec, envie para o número de telefone do usuário ou use um modelo sem bid_spec.
Erro: 131062 — Os destinatários de BSUID não são compatíveis com esta mensagem

CampoValorCódigo
131062
Tipo
OAuthException
Mensagem
"Os destinatários de ID do usuário no escopo do negócio (BSUID) não são compatíveis com esta mensagem."
Esse erro é retornado quando:
O modelo usa bid_spec (preços dinâmicos), e o destinatário é um BSUID.
Um modelo de autenticação é enviado a um destinatário BSUID.
{
  "error": {
    "message": "(#131062) Business-scoped User ID (BSUID) recipients are not supported for this message.",
    "type": "OAuthException",
    "code": 131062,
    "error_data": {
      "messaging_product": "whatsapp",
      "details": "The template specified in the request uses bid_spec, which is not supported for Business-scoped user ID (BSUID) recipients. To send this template, please provide the phone number of recipients or use a template without the bid_spec field."
    }
  }
}

Desabilitar mensagens de marketing na API de Nuvem

Caso a sua empresa tenha feito a integração com a API de MM para WhatsApp, você pode desabilitar a capacidade de enviar modelos da categoria Marketing por meio do ponto de extremidade /messages da API de Nuvem. Quando a opção estiver ativada, o ponto de extremidade /messages rejeitará os modelos da categoria Marketing. Você pode desabilitar a opção de envio de mensagens de marketing por meio do ponto de extremidade /marketing_messages.
A configuração não tem efeito em contas do WhatsApp Business (WABA, pelas iniciais em inglês) que não iniciaram o processo de integração da API de MM para WhatsApp; ela se aplica apenas a WABAs que fizeram a integração por completo. As WABAs que iniciaram o processo de integração, mas não assinaram os Termos de Serviço (ToS), poderão enfrentar bloqueios de mensagens de marketing, conforme descrito em Comportamento de fallback em /marketing_messages.
Sintaxe da solicitação

Use a API da Conta do WhatsApp Business para habilitar ou desabilitar as mensagens de marketing na API de Nuvem.
POST /<WHATSAPP_BUSINESS_ACCOUNT_ID>{
  "disable_marketing_messages_on_cloud_api": true | false}

Defina disable_marketing_messages_on_cloud_api como true para bloquear modelos da categoria Marketing no ponto de extremidade /messages da API de Nuvem. Defina como false para permitir modelos da categoria Marketing na API de Nuvem (padrão).
Exemplo de pedido

A solicitação a seguir desabilita as mensagens de marketing na API de Nuvem para a conta do WhatsApp Business especificada.
curl 'https://graph.facebook.com/v25.0/102290129340398' \-H 'Content-Type: application/json' \-H 'Authorization: Bearer EAAJB...' \-d '
{
  "disable_marketing_messages_on_cloud_api": true
}'

Exemplo de resposta

{
  "id": "102290129340398"
}

Sintaxe da solicitação

Use a API da Conta do WhatsApp Business para verificar o valor atual.
GET /<WHATSAPP_BUSINESS_ACCOUNT_ID>?fields=disable_marketing_messages_on_cloud_api

Exemplo de resposta

{
  "disable_marketing_messages_on_cloud_api": true,
  "id": "102290129340398"
}

Resposta de erro

Se disable_marketing_messages_on_cloud_api for definido como true e você tentar enviar um modelo de categoria de Marketing por meio do ponto de extremidade /messages da API de Nuvem, a API retornará o seguinte erro:
{
  "error": {
    "message": "(#131063) Marketing templates disabled for Cloud API",
    "type": "OAuthException",
    "code": 131063,
    "error_data": {
      "messaging_product": "whatsapp",
      "details": "Your template is categorized as Marketing, but marketing templates are currently disabled for your Cloud API configuration. To send this template, use the Marketing Messages API for WhatsApp or enable marketing templates on Cloud API by turning off disable_marketing_messages_on_cloud_api."
    },
    "fbtrace_id": "ABzNMWIqsLJ7hbj8xd5ytay"
  }
}

Comportamento de fallback em /marketing_messages

Quando disable_marketing_messages_on_cloud_api é definido como true, o fallback para a API de Nuvem do ponto de extremidade /marketing_messages também é afetado:
Termos de Serviço da API de MM assinados: o ponto de extremidade /marketing_messages funciona normalmente. Nenhuma mudança no comportamento.
Termos de Serviço da API de MM não assinados: em circunstâncias normais, as mensagens de modelo de marketing enviadas para /marketing_messages seriam encaminhadas de volta para a API de Nuvem. Porém, agora, o fallback é rejeitado com o erro 131063 porque a aceitação bloqueia modelos de marketing na API de Nuvem.
Para evitar esse erro, verifique se a WABA concluiu todos os requisitos de integração antes de habilitar essa configuração.
Observação: quando o product_policy por mensagem é definido como STRICT, não há tentativa de fallback para a API de Nuvem, independentemente da configuração disable_marketing_messages_on_cloud_api. O comportamento de fallback descrito acima se aplica apenas quando product_policy é definido como o padrão de CLOUD_API_FALLBACK.
Reabilitar mensagens de marketing na API de Nuvem

Para restaurar a capacidade de enviar modelos da categoria Marketing por meio do ponto de extremidade /messages da API de Nuvem, defina disable_marketing_messages_on_cloud_api como false:
curl 'https://graph.facebook.com/v25.0/102290129340398' \-H 'Content-Type: application/json' \-H 'Authorization: Bearer EAAJB...' \-d '
{
  "disable_marketing_messages_on_cloud_api": false
}'

Isso restaura o comportamento padrão. Além disso, os modelos de categoria de marketing são aceitos novamente no ponto de extremidade /messages.
Receber webhooks de status da mensagem

A API de MM para o WhatsApp dispara webhooks de status da mensagem (enviada, entregue, lida). Além disso, esses webhooks que descrevem a mensagem enviada pela API de MM para o WhatsApp e incluem informações de preços terão pricing.category e conversation.type definidos como marketing_lite. Se a mensagem for direcionada pela API de Nuvem, pricing.category será definido como marketing.
{
  "conversation": {
    "id": "<CONVERSATION_ID>",
    "origin": {
      "type": "marketing_lite"
    }
  },
  "pricing": {
    "billable": true,
    "pricing_model": "PMP",
    "category": "marketing_lite"
  }}

Mantenha registros dos IDs de cada mensagem enviada, bem como de qual API foi utilizada para o envio (Nuvem ou MM). Assim, será possível usar o ID único da mensagem, retornado nos webhooks de status, para identificar a origem da mensagem enviada.
Como receber mensagens

A MM para o WhatsApp é uma API apenas de envio. Ela não processa mensagens recebidas de consumidores. Para receber mensagens em um número de telefone comercial, use a API de Nuvem em paralelo com a API de MM para WhatsApp no mesmo número.




ignore sobre codigo agora foque nos fundamentos das mensagens, eu quero uma mensagem para meu vendedor enviar para aquele lead que a janela fechou , algo como desculpas pela demora, responda aqui para continuar seu atendimento