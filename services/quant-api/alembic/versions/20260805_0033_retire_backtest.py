"""retire the historical backtest persistence subsystem

Revision ID: 20260805_0033
Revises: 20260803_0032
Create Date: 2026-08-05
"""

from alembic import op


revision = "20260805_0033"
down_revision = "20260803_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Retire only the frozen production baseline or an all-empty installation."""

    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        DO $$
        DECLARE
            review_count bigint;
            review_identity_count bigint;
            review_attachment_count bigint;
            research_sample_count bigint;
            notification_count bigint;
            event_count bigint;
            signal_count bigint;
            signal_identity_count bigint;
            event_identity_count bigint;
            notification_identity_count bigint;
            dependent_event_count bigint;
            dependent_notification_count bigint;
            dependent_review_count bigint;
            task_count bigint;
            report_count bigint;
            trade_count bigint;
            order_count bigint;
            deleted_count bigint;
        BEGIN
            LOCK TABLE review_notes, review_attachments, research_samples,
                signal_notifications, signal_events, strategy_signals,
                backtest_tasks, backtest_reports, backtest_trades,
                backtest_orders IN ACCESS EXCLUSIVE MODE;

            SELECT count(*) INTO review_count
            FROM review_notes
            WHERE source_type = 'backtest_trade';
            SELECT count(*) INTO review_identity_count
            FROM review_notes AS review
            JOIN backtest_trades AS trade ON trade.id = review.source_id
            WHERE review.source_type = 'backtest_trade';
            SELECT count(*) INTO review_attachment_count
            FROM review_attachments AS attachment
            JOIN review_notes AS review ON review.id = attachment.review_id
            WHERE review.source_type = 'backtest_trade';
            SELECT count(*) INTO research_sample_count
            FROM research_samples AS sample
            JOIN review_notes AS review ON review.id = sample.review_id
            WHERE review.source_type = 'backtest_trade';

            SELECT count(*) INTO signal_count
            FROM strategy_signals
            WHERE dedupe_key = ANY (ARRAY[
                'htdy-first-seen:15d699aaeaf52f28ed2098e82d0cf23574f150af32a82fe213fc032ed397619f',
                'htdy-first-seen:b153ac90ad2de288eac5d31de352cada0e3adfdc1d72eaee6ad6315b452e88f5',
                'htdy-first-seen:7baac25bf5fecd8af83fa7ff798f7da64c6c479e50cda3fca259148e3520acee'
            ]);
            SELECT count(*) INTO signal_identity_count
            FROM strategy_signals
            WHERE strategy_name = 'htdy_original_realtime_first_seen'
              AND symbol = 'jm'
              AND product = 'jm'
              AND contract = 'JM2609'
              AND actual_contract = 'JM2609'
              AND exchange = 'DCE'
              AND period = '15m'
              AND provider = 'rqdata'
              AND source = 'htdy_realtime_snapshot'
              AND status = 'entry_signal'
              AND (
                    (dedupe_key = 'htdy-first-seen:15d699aaeaf52f28ed2098e82d0cf23574f150af32a82fe213fc032ed397619f'
                     AND strategy_version = 'v1.0'
                     AND spec_source = 'htdy_original_xma_15m_first_seen_v1'
                     AND dominant_mapping_date = DATE '2026-07-28'
                     AND direction = 'long')
                 OR (dedupe_key = 'htdy-first-seen:b153ac90ad2de288eac5d31de352cada0e3adfdc1d72eaee6ad6315b452e88f5'
                     AND strategy_version = 'v1.1'
                     AND spec_source = 'htdy_original_xma_15m_close_first_seen_v1'
                     AND dominant_mapping_date = DATE '2026-07-29'
                     AND direction = 'long')
                 OR (dedupe_key = 'htdy-first-seen:7baac25bf5fecd8af83fa7ff798f7da64c6c479e50cda3fca259148e3520acee'
                     AND strategy_version = 'v1.1'
                     AND spec_source = 'htdy_original_xma_15m_close_first_seen_v1'
                     AND dominant_mapping_date = DATE '2026-07-29'
                     AND direction = 'short')
              );

            SELECT count(*) INTO event_count
            FROM signal_events
            WHERE event_key = ANY (ARRAY[
                'signal_created:htdy-first-seen:15d699aaeaf52f28ed2098e82d0cf23574f150af32a82fe213fc032ed397619f:created',
                'signal_created:htdy-first-seen:b153ac90ad2de288eac5d31de352cada0e3adfdc1d72eaee6ad6315b452e88f5:created',
                'signal_created:htdy-first-seen:7baac25bf5fecd8af83fa7ff798f7da64c6c479e50cda3fca259148e3520acee:created'
            ]);
            SELECT count(*) INTO event_identity_count
            FROM signal_events AS event
            JOIN strategy_signals AS signal ON signal.id = event.signal_id
            WHERE event.event_key = 'signal_created:' || signal.dedupe_key || chr(58) || 'created'
              AND signal.dedupe_key = ANY (ARRAY[
                  'htdy-first-seen:15d699aaeaf52f28ed2098e82d0cf23574f150af32a82fe213fc032ed397619f',
                  'htdy-first-seen:b153ac90ad2de288eac5d31de352cada0e3adfdc1d72eaee6ad6315b452e88f5',
                  'htdy-first-seen:7baac25bf5fecd8af83fa7ff798f7da64c6c479e50cda3fca259148e3520acee'
              ])
              AND event.event_type = 'signal_created'
              AND event.decision_id IS NULL
              AND event.source_mode = 'live_realtime_repainting'
              AND event.strategy_name = signal.strategy_name
              AND event.strategy_version = signal.strategy_version
              AND event.symbol = signal.symbol
              AND event.product = signal.product
              AND event.contract = signal.contract
              AND event.actual_contract = signal.actual_contract
              AND event.dominant_mapping_date = signal.dominant_mapping_date
              AND event.exchange = signal.exchange
              AND event.period = signal.period
              AND event.source = signal.source
              AND event.signal_status = signal.status;

            SELECT count(*) INTO notification_count
            FROM signal_notifications
            WHERE dedupe_key = 'enterprise_wechat:signal_event:4';
            SELECT count(*) INTO notification_identity_count
            FROM signal_notifications AS notification
            JOIN signal_events AS event ON event.id = notification.event_id
            JOIN strategy_signals AS signal ON signal.id = notification.signal_id
            WHERE notification.dedupe_key = 'enterprise_wechat:signal_event:4'
              AND event.event_key = 'signal_created:htdy-first-seen:15d699aaeaf52f28ed2098e82d0cf23574f150af32a82fe213fc032ed397619f:created'
              AND signal.dedupe_key = 'htdy-first-seen:15d699aaeaf52f28ed2098e82d0cf23574f150af32a82fe213fc032ed397619f'
              AND event.signal_id = signal.id
              AND notification.event_type = 'signal_created'
              AND notification.channel = 'enterprise_wechat'
              AND notification.status = 'sent';

            SELECT count(*) INTO dependent_event_count
            FROM signal_events AS event
            JOIN strategy_signals AS signal ON signal.id = event.signal_id
            WHERE signal.dedupe_key = ANY (ARRAY[
                'htdy-first-seen:15d699aaeaf52f28ed2098e82d0cf23574f150af32a82fe213fc032ed397619f',
                'htdy-first-seen:b153ac90ad2de288eac5d31de352cada0e3adfdc1d72eaee6ad6315b452e88f5',
                'htdy-first-seen:7baac25bf5fecd8af83fa7ff798f7da64c6c479e50cda3fca259148e3520acee'
            ])
              AND event.event_key != 'signal_created:' || signal.dedupe_key || chr(58) || 'created';

            SELECT count(*) INTO dependent_notification_count
            FROM signal_notifications AS notification
            LEFT JOIN signal_events AS event ON event.id = notification.event_id
            LEFT JOIN strategy_signals AS signal ON signal.id = notification.signal_id
            WHERE (
                event.event_key = ANY (ARRAY[
                    'signal_created:htdy-first-seen:15d699aaeaf52f28ed2098e82d0cf23574f150af32a82fe213fc032ed397619f:created',
                    'signal_created:htdy-first-seen:b153ac90ad2de288eac5d31de352cada0e3adfdc1d72eaee6ad6315b452e88f5:created',
                    'signal_created:htdy-first-seen:7baac25bf5fecd8af83fa7ff798f7da64c6c479e50cda3fca259148e3520acee:created'
                ])
                OR signal.dedupe_key = ANY (ARRAY[
                    'htdy-first-seen:15d699aaeaf52f28ed2098e82d0cf23574f150af32a82fe213fc032ed397619f',
                    'htdy-first-seen:b153ac90ad2de288eac5d31de352cada0e3adfdc1d72eaee6ad6315b452e88f5',
                    'htdy-first-seen:7baac25bf5fecd8af83fa7ff798f7da64c6c479e50cda3fca259148e3520acee'
                ])
            )
              AND notification.dedupe_key != 'enterprise_wechat:signal_event:4';

            SELECT count(*) INTO dependent_review_count
            FROM review_notes AS review
            WHERE (
                review.source_type = 'strategy_signal'
                AND review.source_id IN (
                    SELECT id FROM strategy_signals
                    WHERE dedupe_key = ANY (ARRAY[
                        'htdy-first-seen:15d699aaeaf52f28ed2098e82d0cf23574f150af32a82fe213fc032ed397619f',
                        'htdy-first-seen:b153ac90ad2de288eac5d31de352cada0e3adfdc1d72eaee6ad6315b452e88f5',
                        'htdy-first-seen:7baac25bf5fecd8af83fa7ff798f7da64c6c479e50cda3fca259148e3520acee'
                    ])
                )
            ) OR (
                review.source_type = 'signal_event'
                AND review.source_id IN (
                    SELECT id FROM signal_events
                    WHERE event_key = ANY (ARRAY[
                        'signal_created:htdy-first-seen:15d699aaeaf52f28ed2098e82d0cf23574f150af32a82fe213fc032ed397619f:created',
                        'signal_created:htdy-first-seen:b153ac90ad2de288eac5d31de352cada0e3adfdc1d72eaee6ad6315b452e88f5:created',
                        'signal_created:htdy-first-seen:7baac25bf5fecd8af83fa7ff798f7da64c6c479e50cda3fca259148e3520acee:created'
                    ])
                )
            );

            SELECT count(*) INTO task_count FROM backtest_tasks;
            SELECT count(*) INTO report_count FROM backtest_reports;
            SELECT count(*) INTO trade_count FROM backtest_trades;
            SELECT count(*) INTO order_count FROM backtest_orders;

            IF NOT (
                (review_count = 0 AND notification_count = 0 AND event_count = 0
                 AND signal_count = 0 AND task_count = 0 AND report_count = 0
                 AND trade_count = 0 AND order_count = 0)
                OR
                (review_count = 7 AND notification_count = 1 AND event_count = 3
                 AND signal_count = 3 AND task_count = 23 AND report_count = 15
                 AND trade_count = 4361 AND order_count = 4225)
            ) THEN
                RAISE EXCEPTION
                    'backtest retirement requires exact baseline review/notification/event/signal/tasks/reports/trades/orders=7/1/3/3/23/15/4361/4225 or all zero';
            END IF;

            IF review_identity_count != review_count
               OR review_attachment_count != 0
               OR research_sample_count != 0 THEN
                RAISE EXCEPTION 'backtest retirement linked review data drift';
            END IF;
            IF signal_identity_count != signal_count
               OR event_identity_count != event_count
               OR notification_identity_count != notification_count THEN
                RAISE EXCEPTION 'legacy S6 retirement identity mismatch';
            END IF;
            IF dependent_event_count != 0
               OR dependent_notification_count != 0
               OR dependent_review_count != 0 THEN
                RAISE EXCEPTION 'legacy S6 retirement logical dependency drift';
            END IF;

            DELETE FROM review_notes WHERE source_type = 'backtest_trade';
            GET DIAGNOSTICS deleted_count = ROW_COUNT;
            IF deleted_count != review_count THEN
                RAISE EXCEPTION 'backtest review delete count mismatch';
            END IF;

            DELETE FROM signal_notifications
            WHERE dedupe_key = 'enterprise_wechat:signal_event:4';
            GET DIAGNOSTICS deleted_count = ROW_COUNT;
            IF deleted_count != notification_count THEN
                RAISE EXCEPTION 'legacy S6 notification delete count mismatch';
            END IF;

            DELETE FROM signal_events
            WHERE event_key = ANY (ARRAY[
                'signal_created:htdy-first-seen:15d699aaeaf52f28ed2098e82d0cf23574f150af32a82fe213fc032ed397619f:created',
                'signal_created:htdy-first-seen:b153ac90ad2de288eac5d31de352cada0e3adfdc1d72eaee6ad6315b452e88f5:created',
                'signal_created:htdy-first-seen:7baac25bf5fecd8af83fa7ff798f7da64c6c479e50cda3fca259148e3520acee:created'
            ]);
            GET DIAGNOSTICS deleted_count = ROW_COUNT;
            IF deleted_count != event_count THEN
                RAISE EXCEPTION 'legacy S6 event delete count mismatch';
            END IF;

            DELETE FROM strategy_signals
            WHERE dedupe_key = ANY (ARRAY[
                'htdy-first-seen:15d699aaeaf52f28ed2098e82d0cf23574f150af32a82fe213fc032ed397619f',
                'htdy-first-seen:b153ac90ad2de288eac5d31de352cada0e3adfdc1d72eaee6ad6315b452e88f5',
                'htdy-first-seen:7baac25bf5fecd8af83fa7ff798f7da64c6c479e50cda3fca259148e3520acee'
            ]);
            GET DIAGNOSTICS deleted_count = ROW_COUNT;
            IF deleted_count != signal_count THEN
                RAISE EXCEPTION 'legacy S6 signal delete count mismatch';
            END IF;

            DELETE FROM backtest_tasks;
            GET DIAGNOSTICS deleted_count = ROW_COUNT;
            IF deleted_count != task_count THEN
                RAISE EXCEPTION 'backtest task delete count mismatch';
            END IF;

            IF EXISTS (SELECT 1 FROM review_notes WHERE source_type = 'backtest_trade')
               OR EXISTS (SELECT 1 FROM signal_notifications WHERE dedupe_key = 'enterprise_wechat:signal_event:4')
               OR EXISTS (
                   SELECT 1 FROM signal_events
                   WHERE event_key = ANY (ARRAY[
                       'signal_created:htdy-first-seen:15d699aaeaf52f28ed2098e82d0cf23574f150af32a82fe213fc032ed397619f:created',
                       'signal_created:htdy-first-seen:b153ac90ad2de288eac5d31de352cada0e3adfdc1d72eaee6ad6315b452e88f5:created',
                       'signal_created:htdy-first-seen:7baac25bf5fecd8af83fa7ff798f7da64c6c479e50cda3fca259148e3520acee:created'
                   ])
               )
               OR EXISTS (
                   SELECT 1 FROM strategy_signals
                   WHERE dedupe_key = ANY (ARRAY[
                       'htdy-first-seen:15d699aaeaf52f28ed2098e82d0cf23574f150af32a82fe213fc032ed397619f',
                       'htdy-first-seen:b153ac90ad2de288eac5d31de352cada0e3adfdc1d72eaee6ad6315b452e88f5',
                       'htdy-first-seen:7baac25bf5fecd8af83fa7ff798f7da64c6c479e50cda3fca259148e3520acee'
                   ])
               )
               OR EXISTS (SELECT 1 FROM backtest_tasks)
               OR EXISTS (SELECT 1 FROM backtest_reports)
               OR EXISTS (SELECT 1 FROM backtest_trades)
               OR EXISTS (SELECT 1 FROM backtest_orders) THEN
                RAISE EXCEPTION 'backtest retirement delete count mismatch';
            END IF;
        END
        $$;
        """
    )
    op.drop_table("backtest_orders")
    op.drop_table("backtest_trades")
    op.drop_table("backtest_reports")
    op.drop_table("backtest_tasks")


def downgrade() -> None:
    raise RuntimeError(
        "backtest retirement is irreversible: recover retired code and data from Git/RQData before attempting a downgrade"
    )
