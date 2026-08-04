import asyncio
import logging

from celery import Celery
from celery.signals import after_setup_logger, after_setup_task_logger, worker_process_init

from app.core.config import settings
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)

celery_app = Celery(
    "worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.document_tasks"],
)

celery_app.conf.update(
    task_routes={"app.tasks.document_tasks.process_document": {"queue": "ingestion"}},
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    result_expires=60 * 60 * 24,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    task_track_started=True,
)


@after_setup_logger.connect
@after_setup_task_logger.connect
def _configure_celery_logging(**kwargs) -> None:
    """Celery installs its own logging config as part of its startup
    bootstep, which runs after (and overwrites) anything done in
    worker_process_init — these are the signals Celery itself documents for
    customizing logging, so our JSON/text formatter actually sticks instead
    of being silently clobbered."""
    configure_logging()


@worker_process_init.connect
def _warm_up_worker(**kwargs) -> None:
    """Load the embedding models once per worker process at startup instead
    of on the first task, so ingestion latency is consistent from request 1."""
    from app.services import embeddings
    from app.services.qdrant_client import init_qdrant
    from app.services.storage import storage

    try:
        init_qdrant()
        embeddings.get_dense_model()
        embeddings.get_sparse_model()
        if not asyncio.run(storage.ensure_bucket()):
            logger.error("Object storage bucket unavailable; ingestion will fail until it recovers")
        logger.info("Celery worker warm-up complete")
    except Exception:
        logger.error("Worker warm-up failed; models will lazy-load on first task", exc_info=True)
