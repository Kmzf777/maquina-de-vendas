# DIRETRIZES DE ENGENHARIA PARA AGENTES DE IA (CLAUDE CODE, COPILOT, ETC)

Você está atuando em um repositório mantido por múltiplos desenvolvedores (humanos e IAs). A produção é crítica (Docker Swarm). Siga ESTritamente as regras abaixo:

## 🚀 1. Fluxo de Trabalho e Git (Prática de Master)
O projeto é mantido pelo Rafael (Líder) e pelo Kelwin. **NÃO utilizamos Pull Requests (PRs)**.
- O fluxo oficial é: **Criar branch local -> Codificar -> Testar no Servidor -> Push direto para a Master**.
- Ao iniciar uma nova tarefa, crie uma branch local para organizar o trabalho (ex: `feature/novo-recurso`).
- Como testar: Você deve sempre validar se o código funciona utilizando as tarefas configuradas do VS Code (ex: `run task "Run All Dev (CRM & Backend)"`).
- Após garantir que os serviços sobem sem erros (build, lint, etc.), o push é feito *diretamente* para a branch `master` no repositório remoto (ex: `git push origin sua-branch-local:master` ou merge local e push).
- **Atenção:** O push na `master` aciona o deploy de produção no GitHub Actions. Portanto, SÓ faça o push final após os testes na sua branch passarem.

## 📞 2. Roteamento de Webhook e Whitelist (Isolamento de Testes)
Sistema crucial do negócio: Existe um "Dev Router" (Whitelist). Quando números de telefone específicos (em teste) enviam mensagens, a requisição que chega no Webhook deve ser OBRIGATORIAMENTE redirecionada para a URL do ambiente de desenvolvimento (ex: `DEV_SERVER_URL`), e não pode ser processada pela base de Produção.
- Sempre que alterar o Webhook (`backend/app/webhook/`), verifique se o roteador de dev não foi "bypassado".

## 🚦 3. Regras de Infraestrutura, Redes e Docker (Prevenção de Quedas de Produção)
Tivemos incidentes críticos causados por IP hardcodado.
- **PROIBIDO O USO DE LOCALHOST:** NUNCA use `localhost` ou `127.0.0.1` para conexões de rede em variáveis de ambiente, `.env`, `config.py`, ou qualquer arquivo de configuração (seja para Redis, Banco de Dados Postgres, RabbitMQ, etc.).
- **USE SEMPRE O DNS DO DOCKER:** Sempre utilize os nomes dos serviços definidos no arquivo `docker-compose.yml` (Exemplos obrigatórios: `redis://redis:6379`, `postgresql://user:pass@db:5432`, `http://api:8000`).
- Paridade Dev/Prod: O código deve rodar perfeitamente sem modificações tanto no `docker-compose` local quanto no `docker stack deploy` no Swarm de Produção.
- Não altere configurações de deployment no GitHub Actions sem alertar agressivamente o usuário.

## ⚛️ 4. Regras Específicas do Frontend (Next.js)
- **This is NOT the Next.js you know**: Esta versão possui quebras de paradigma (App Router vs Pages, Server Components, etc).
- As APIs, convenções e estrutura de pastas podem diferir dos seus dados de treinamento.
- Sempre verifique a documentação local ou prefira usar os padrões já desenhados em `frontend/src/app` antes de criar lógicas com bibliotecas legadas.
