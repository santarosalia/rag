import asyncio
import uuid
from datetime import UTC, datetime

from celery import Celery
from celery.signals import worker_process_init
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from rag.config import get_settings
from rag.db.models import Document, DocumentStatus, IngestJob, JobStatus
from rag.observability.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)

celery_app = Celery(
    "rag",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_retry_delay=30,
    task_max_retries=3,
)

_sync_session_local: sessionmaker[Session] | None = None


def get_sync_session() -> Session:
    global _sync_session_local
    if _sync_session_local is None:
        sync_database_url = settings.database_url.replace("+asyncpg", "")
        sync_engine = create_engine(sync_database_url, pool_pre_ping=True)
        _sync_session_local = sessionmaker(sync_engine, class_=Session, expire_on_commit=False)
    return _sync_session_local()


def run_async(coro):
    return asyncio.run(coro)


@worker_process_init.connect
def _dispose_inherited_engine(**_kwargs) -> None:
    from rag.db.session import engine as async_engine

    async_engine.sync_engine.dispose()


@celery_app.task(bind=True, name="rag.ingest_document", max_retries=3)
def ingest_document_task(self, doc_id: str, job_id: str) -> dict:
    from rag.db.session import worker_session
    from rag.ingestion.pipeline import IngestionPipeline

    async def _ingest():
        async with worker_session() as session:
            job_result = await session.execute(
                select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
            )
            job = job_result.scalar_one_or_none()
            if job:
                job.status = JobStatus.RUNNING
                job.celery_task_id = self.request.id
                await session.commit()

            pipeline = IngestionPipeline()
            try:
                chunk_count = await pipeline.ingest_document(session, uuid.UUID(doc_id))
                if job:
                    job.status = JobStatus.COMPLETED
                await session.commit()
                return {"doc_id": doc_id, "chunk_count": chunk_count, "status": "completed"}
            except Exception as e:
                if job:
                    job.status = JobStatus.FAILED
                    job.error_message = str(e)
                await session.commit()
                raise
            finally:
                await pipeline.search_backend.close()

    try:
        return run_async(_ingest())
    except Exception as exc:
        logger.error("ingest_task_failed", doc_id=doc_id, error=str(exc))
        raise self.retry(exc=exc) from exc


@celery_app.task(bind=True, name="rag.delete_document", max_retries=3)
def delete_document_task(self, doc_id: str) -> dict:
    from rag.indexing.factory import get_search_backend
    from rag.storage.s3 import ObjectStorage

    async def _delete():
        backend = get_search_backend()
        try:
            deleted = await backend.delete_by_doc_id(doc_id)
            await backend.close()
            return deleted
        except Exception:
            await backend.close()
            raise

    session = get_sync_session()
    try:
        result = session.execute(select(Document).where(Document.id == uuid.UUID(doc_id)))
        document = result.scalar_one_or_none()
        if not document:
            return {"doc_id": doc_id, "status": "not_found"}

        run_async(_delete())
        storage = ObjectStorage()
        storage.delete(document.s3_key)
        document.status = DocumentStatus.DELETED
        document.deleted_at = datetime.now(UTC)
        session.commit()
        return {"doc_id": doc_id, "status": "deleted"}
    except Exception as exc:
        session.rollback()
        logger.error("delete_task_failed", doc_id=doc_id, error=str(exc))
        raise self.retry(exc=exc) from exc
    finally:
        session.close()


@celery_app.task(name="rag.reindex_document")
def reindex_document_task(doc_id: str, job_id: str) -> dict:
    return ingest_document_task(doc_id, job_id)
