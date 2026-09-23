# Lumen

Self-hosted document assistant combining hybrid retrieval, semantic caching, asynchronous ingestion, multi-provider LLM fallback, and streaming answers with source citations.

[Live demo](https://lumen-three-nu.vercel.app)

![Lumen chat](docs/screenshot-chat.png)

## Problem

A document QA system needs more than an LLM call. Retrieval quality, ingestion latency, cache behavior, tenant isolation, and failure handling all affect the backend's correctness and user experience.

Lumen treats retrieval as an observable pipeline rather than a black box.

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
       cache/rate     retrieval
         limits
             |           |
             +-----+-----+
                   |
                   v
             LLM providers
                   |
              streamed answer
~~~

Document ingestion runs asynchronously:

~~~text
Upload -> parse -> chunk -> embed -> index
                     |
                     +-> PostgreSQL
                     +-> Qdrant
~~~

## Engineering decisions

- **Hybrid retrieval:** combine dense retrieval with BM25 and fuse rankings with Reciprocal Rank Fusion.
- **Cross-encoder reranking:** improve ordering of retrieved candidates before generation.
- **Semantic caching:** avoid repeating expensive work for near-duplicate queries.
- **SSE streaming:** return generated output incrementally instead of waiting for the complete response.
- **Celery ingestion:** move document parsing, embedding, and indexing off the request path.
- **Tenant isolation:** enforce organization-level document boundaries in the backend.
- **Retrieval evaluation:** measure Recall@k, MRR, and NDCG against a fixed golden dataset.
- **Observability:** expose Prometheus metrics and a retrieval debugger for pipeline inspection.

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

Configure the required provider credentials and service settings using the repository's environment configuration.

## What I focused on

The main engineering goal was to make retrieval behavior measurable and debuggable. The system exposes the stages from query rewriting through caching, retrieval, fusion, reranking, and generation so changes can be evaluated systematically rather than judged only from a few manual prompts.

## License

Apache-2.0
