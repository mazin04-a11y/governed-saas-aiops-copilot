from sqlalchemy.orm import Session

from app.models.records import AuditLog


def audit(session: Session, event_type: str, actor: str, entity_type: str, entity_id: int | None, details: dict) -> None:
    session.add(
        AuditLog(
            event_type=event_type,
            actor=actor,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        )
    )

