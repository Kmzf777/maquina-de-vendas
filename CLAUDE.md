# DIRETRIZES DE ENGENHARIA PARA AGENTES DE IA (CLAUDE CODE, COPILOT, ETC)

Você está atuando em um repositório mantido por múltiplos desenvolvedores (humanos e IAs). A produção é crítica (Docker Swarm). Siga ESTritamente as regras abaixo:

## 🔒 1. Gestão de Git (Proteção da Master)
O seu usuário humano pode não ter conhecimento avançado de versionamento. Portanto, **VOCÊ é o responsável por toda a gestão do Git de forma segura**.
- **NUNCA** comite ou faça push diretamente na branch `master`.
- Antes de iniciar qualquer alteração, leia os arquivos na pasta `docs/` e crie uma branch com o padrão: `feature/nome-da-tarefa` ou `fix/nome-do-erro` (Ex: `git checkout -b feature/novo-layout`).
- Recomende e prepare comandos de Pull Request (PR) quando o trabalho for finalizado para revisão do Tech Lead.

## 🚦 2. Regras de Infraestrutura, Redes e Docker (Prevenção de Quedas de Produção)
Tivemos incidentes críticos causados por IP hardcodado.
- **PROIBIDO O USO DE LOCALHOST:** NUNCA use `localhost` ou `127.0.0.1` para conexões de rede em variáveis de ambiente, `.env`, `config.py`, ou qualquer arquivo de configuração (seja para Redis, Banco de Dados Postgres, RabbitMQ, etc.).
- **USE SEMPRE O DNS DO DOCKER:** Sempre utilize os nomes dos serviços definidos no arquivo `docker-compose.yml` (Exemplos obrigatórios: `redis://redis:6379`, `postgresql://user:pass@db:5432`, `http://api:8000`).
- Paridade Dev/Prod: O código deve rodar perfeitamente sem modificações tanto no `docker-compose` local quanto no `docker stack deploy` no Swarm de Produção.
- Não altere configurações de deployment no GitHub Actions sem alertar agressivamente o usuário.

## ⚛️ 3. Regras Específicas do Frontend (Next.js)
- **This is NOT the Next.js you know**: Esta versão possui quebras de paradigma (App Router vs Pages, Server Components, etc).
- As APIs, convenções e estrutura de pastas podem diferir dos seus dados de treinamento.
- Sempre verifique a documentação local ou prefira usar os padrões já desenhados em `frontend/src/app` antes de criar lógicas com bibliotecas legadas.
