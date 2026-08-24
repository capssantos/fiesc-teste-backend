# Backend

API da solucao de manutencao prescritiva.

## Stack

- `FastAPI`
- `Pydantic`
- `SQLAlchemy`
- `Alembic`
- `PostgreSQL`
- `MinIO / S3 compativel`
- `PyMuPDF`

## Objetivo

O backend recebe um evento novo, busca eventos historicos semelhantes, identifica a falha mais provavel, consulta a documentacao mapeada e controla o uso seguro do LLM.

## Estrutura

- `app/main.py`: bootstrap da API e handlers globais
- `app/api/`: rotas HTTP
- `app/core/`: configuracao e settings
- `app/db/`: sessao e modelos
- `app/schemas/`: contratos Pydantic
- `app/services/`: similaridade, retrieval, recommendation, storage e integrações
- `alembic/`: migrations

## Endpoints

- `GET /api/v1/health`
- `POST /api/v1/events/analyze`
- `POST /api/v1/events/similar`
- `GET /api/v1/faults`
- `GET /api/v1/faults/{fault_name}`
- `GET /api/v1/documents`
- `POST /api/v1/documents`
- `POST /api/v1/chat`

## O que o backend ja faz

- aceita o payload do case com `id`, `created_at`, metricas e `fault`
- trata `fault` apenas como referencia e nao como feature
- usa `docs/banner.csv` como historico de similaridade
- exclui o proprio evento da vizinhanca quando o `id` coincide com o historico
- calcula `neighbors`, `classification`, `history` e `documentation`
- usa `config/fault_document_map.yaml` para suporte documental
- faz retrieval simples dos documentos mapeados
- salva documentos e artifacts em `MinIO / S3`
- persiste eventos, analises e documentos no PostgreSQL

## Instalacao local

Entrar na pasta:

```bash
cd backend
```

Instalar dependencias:

```bash
pip install -r requirements.txt
```

Criar ambiente:

```bash
copy .env.example .env
```

Aplicar migrations:

```bash
alembic -c alembic.ini upgrade head
```

Subir a API:

```bash
uvicorn app.main:app --reload
```

Ou:

```bash
python app/main.py
```

Documentacao interativa:

```text
http://localhost:8000/docs
```

## Variaveis de ambiente principais

### Banco

- `DATABASE_URL`: conexao com PostgreSQL
- `AUTO_MIGRATE_ON_STARTUP`: aplica `alembic upgrade head` no startup
- `CORS_ORIGINS`: origins explicitamente permitidos no navegador

### Similaridade

- `SIMILARITY_K`: quantidade de vizinhos

### Object storage

- `STORAGE_BACKEND`: hoje `minio`
- `S3_ENDPOINT_URL`: endpoint interno do storage
- `S3_PUBLIC_BASE_URL`: base publica para links assinados
- `S3_ACCESS_KEY`: access key do storage
- `S3_SECRET_KEY`: secret key do storage
- `S3_DOCUMENTS_BUCKET`: bucket de documentos
- `S3_ARTIFACTS_BUCKET`: bucket de artifacts

### LLM

- `LLM_PROVIDER`: vazio, `openai` ou `ollama`
- `OPENAI_API_KEY`: chave da OpenAI
- `OPENAI_MODEL`: modelo OpenAI
- `OPENAI_BASE_URL`: base da API OpenAI
- `OLLAMA_MODEL`: modelo Ollama
- `OLLAMA_BASE_URL`: base do Ollama

## Exemplo de payload para analise

`POST /api/v1/events/analyze`

```json
{
  "id": 114387,
  "created_at": "2026-06-01T21:32:53.911176Z",
  "z_rms_velocity_in_s": 0.0597,
  "z_rms_velocity_mm_s": 1.517,
  "temperature_f": 76.44,
  "temperature_c": 24.69,
  "x_rms_velocity_in_s": 0.0787,
  "x_rms_velocity_mm_s": 2.0,
  "z_peak_acceleration_g": 0.484,
  "x_peak_acceleration_g": 0.631,
  "z_peak_vel_comp_freq_hz": 61.0,
  "x_peak_vel_comp_freq_hz": 61.0,
  "z_rms_acceleration_g": 0.09,
  "x_rms_acceleration_g": 0.114,
  "z_kurtosis": 2.392,
  "x_kurtosis": 2.77,
  "z_crest_factor": 3.747,
  "x_crest_factor": 4.269,
  "z_peak_velocity_in_s": 0.0844,
  "z_peak_velocity_mm_s": 2.146,
  "x_peak_velocity_in_s": 0.1113,
  "x_peak_velocity_mm_s": 2.829,
  "z_high_freq_rms_accel_g": 0.129,
  "x_high_freq_rms_accel_g": 0.147,
  "fault": "cocked_rotor_2",
  "rpm": 1000.0
}
```

## Docker

O projeto possui:

- `backend/Dockerfile`
- `docker-compose.yml` na raiz

O compose sobe:

- `frontend`
- `api`
- `postgres`
- `minio`

## Como subir tudo com Docker

Na raiz do projeto:

```bash
docker compose up --build
```

Servicos:

- backend: `http://localhost:8000`
- minio console: `http://localhost:9001`

## Seguranca

Seguir `docs/security_policies.md`.

Pontos principais:

- validacao forte de payloads
- guardrail documental antes do LLM
- sem segredos no frontend
- PostgreSQL e MinIO acessados apenas pelo backend
- links de download assinados
