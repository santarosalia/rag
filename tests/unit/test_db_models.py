from rag.db.models import Document


def test_document_status_persists_lowercase_values_for_postgres():
    values = list(Document.__table__.c.status.type.enums)
    assert values == ["pending", "processing", "completed", "failed", "deleted"]
