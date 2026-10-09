"""Explicit activation, safe status and disable for the Newow notification policy."""

import argparse
from datetime import UTC, datetime
import json

from sqlalchemy import select, text

from app.notifications.newow import (
    FREQUENCIES, STRATEGIES, NewowNotificationPolicy,
    enable_newow_notifications, notification_status,
)
from app.reference_trading.models import ReferenceRevision, ReferenceStream


def require_scope(rows, products):
    expected = {(s, f, p) for s in STRATEGIES for f in FREQUENCIES for p in products}
    if set(rows) != expected or len(rows) != len(expected):
        raise ValueError("NEWOW_NOTIFICATION_SCOPE_NOT_READY")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "enable", "disable"))
    action = parser.parse_args().action
    from app.db.session import SessionLocal, engine
    from app.market_data.operational_universe import load_operational_products
    from sqlalchemy.orm import Session

    try:
        if action == "status":
            with SessionLocal() as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                result = notification_status(session)
        else:
            # Serialize changes with delivery. Never change the audience in-flight.
            with engine.connect() as connection:
                locked = connection.execute(text("SELECT pg_try_advisory_lock(1852143479, 1)")).scalar()
                connection.commit()
                if not locked:
                    raise ValueError("NEWOW_NOTIFICATION_BUSY")
                try:
                    with Session(bind=connection, expire_on_commit=False) as session:
                        if action == "enable":
                            products = load_operational_products()
                            rows = session.execute(select(
                                ReferenceStream.strategy_code, ReferenceStream.frequency, ReferenceStream.product,
                            ).join(ReferenceRevision,
                                (ReferenceStream.stream_id == ReferenceRevision.stream_id)
                                & (ReferenceStream.active_revision_id == ReferenceRevision.revision_id),
                            ).where(
                                ReferenceStream.strategy_code.in_(STRATEGIES),
                                ReferenceStream.frequency.in_(FREQUENCIES),
                                ReferenceStream.product.in_(products),
                                ReferenceStream.recording_mode == "forward_observation",
                                ReferenceStream.enabled.is_(True), ReferenceStream.health == "READY",
                                ReferenceRevision.status == "active",
                            )).all()
                            require_scope(rows, products)
                            enable_newow_notifications(session, products=products, enabled_at=datetime.now(UTC))
                        else:
                            policy = session.get(NewowNotificationPolicy, "newow_actions_v1")
                            if policy is not None:
                                policy.enabled = False
                                session.commit()
                        result = notification_status(session)
                finally:
                    connection.execute(text("SELECT pg_advisory_unlock(1852143479, 1)"))
                    connection.commit()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception:
        # Do not disclose database URLs or provider configuration on operator errors.
        print(json.dumps({"error": "NEWOW_NOTIFICATION_COMMAND_FAILED", "action": action}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
