# Backend

Backend da solucao de manutencao prescritiva.

## Stack

- `FastAPI`
- `Pydantic`
- `SQLAlchemy`
- `Alembic`
- `PostgreSQL`
- `MinIO / S3 compativel`

## Estrutura

- `app/main.py`: bootstrap da API
- `app/api/`: rotas HTTP
- `app/core/`: configuracao
- `app/db/`: sessao e modelos
- `app/schemas/`: contratos Pydantic
- `app/services/`: servicos internos
- `alembic/`: migrations

## Endpoints atuais

- `GET /api/v1/health`
- `POST /api/v1/events/analyze`
- `POST /api/v1/events/similar`
- `GET /api/v1/faults`
- `GET /api/v1/faults/{fault_name}`
- `GET /api/v1/documents`
- `POST /api/v1/documents`
- `POST /api/v1/chat`

## Regras importantes

- `POST /api/v1/events/analyze` recebe `application/json`
- esse endpoint aceita o formato do case com `id`, `created_at`, metricas e `fault`
- `fault` pode entrar como referencia do registro de teste, mas nao deve ser usado como feature de similaridade
- upload de documentos deve ir para `POST /api/v1/documents`
- o backend usa `docs/banner.csv` como base historica para similaridade
- o backend usa `config/fault_document_map.yaml` para validar suporte documental
- o backend exclui o proprio evento da vizinhanca quando o `id` da entrada coincide com um registro historico
- o backend faz retrieval simples dos documentos mapeados antes de montar recommendation/chat

## Rodando localmente

Instalar dependencias:

```bash
pip install -r requirements.txt
```

Criar ambiente:

```bash
copy .env.example .env
```

Rodar migration:

```bash
alembic -c alembic.ini upgrade head
```

Se `AUTO_MIGRATE_ON_STARTUP=true`, a API tambem tenta aplicar `alembic upgrade head` no startup.

Subir API:

```bash
uvicorn app.main:app --reload
```

Ou:

```bash
python app/main.py
```

## Docker

O projeto possui `backend/Dockerfile` e `docker-compose.yml` na raiz para subir:

- `api`
- `postgres`
- `minio`

## Seguranca

Seguir as regras de `docs/security_policies.md`.
