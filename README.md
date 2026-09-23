# Lumen

A self-hosted document assistant that combines hybrid retrieval, semantic caching, multi-provider LLM fallback, and streaming answers with source citations.

[Live demo](https://lumen-three-nu.vercel.app)

![Lumen chat](docs/screenshot-chat.png)

## What it does

Users upload documents and ask questions against them. Lumen retrieves relevant passages using dense and sparse search, reranks candidates, and streams a grounded answer with citations back to the source chunks.

The system also supports multi-document questions, organization-level data isolation, asynchronous document ingestion, OCR fallback for scanned PDFs, and a retrieval debugger.

## Architecture

~~~text
                     +------------------+
                     |    Next.js UI    |
                     +--------+---------+
                              |
                         HTTPS / SSE
                              |
                     +--------v---------+
                     |    FastAPI API   |
                     +---+----------+---+
                         |          |
                  chat pipeline    documents
                         |          |
             +-----------+          +----> PostgreSQL
             |           |
             v           v
          Redis       Qdrant
       cache/rate     hybrid
         limits      retrieval
             |           |
             +-----+-----+
                   |
                   v
             LLM providers
                   |
              streamed answer
~~~

Document ingestion runs asynchronously through Celery:

~~~text
Upload -> parse -> chunk -> embed -> index
                     |
                     +-> PostgreSQL
                     +-> Qdrant
~~~

## Key engineering work

- Hybrid dense + BM25 retrieval fused with Reciprocal Rank Fusion.
- Cross-encoder reranking for retrieval precision.
- Conversational query rewriting for follow-up questions.
- Redis/Qdrant semantic cache for near-duplicate queries.
- Streaming LLM responses over SSE.
- Multi-provider LLM fallback through LiteLLM.
- Celery-based asynchronous document ingestion.
- OCR fallback for scanned PDF pages.
- JWT access/refresh authentication with bcrypt.
- Organization-level document isolation.
- Prometheus metrics and Grafana dashboards.
- Golden-dataset retrieval evaluation using Recall@k, MRR, and NDCG.
- Retrieval debugger showing rewrite, cache, retrieval, fusion, reranking, and prompt stages.

## Tech stack

| Layer | Technologies |
|---|---|
| Frontend | Next.js, React, Tailwind |
| Backend | FastAPI, SQLAlchemy, Alembic |
| Data | PostgreSQL, Redis, Qdrant |
| Async processing | Celery |
| Retrieval | Dense embeddings, BM25, RRF, cross-encoder |
| AI | LiteLLM, Gemini, OpenAI, Anthropic, Groq, Ollama |
| Infrastructure | Docker, S3/MinIO, Prometheus, Grafana |

## Run locally

The complete stack is containerized.

~~~bash
git clone https://github.com/colin-110/lumen.git
cd lumen
docker compose up --build
~~~

See the repository configuration and environment files for provider credentials and service settings.

## Why this project is interesting

The goal was not simply to make a chatbot. The system makes retrieval behavior observable and measurable: every stage from query rewriting through reranking can be inspected, and retrieval changes can be evaluated against a fixed dataset instead of judged only by subjective answers.

## License

Apache-2.0
