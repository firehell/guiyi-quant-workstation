"""One explicit, preinstalled additive schema exception for stopped-cohort releases.

This module never migrates a database. File equality alone is insufficient: the
installed revision, exact inbox metadata and immutable guards must be read back
in a fresh read-only transaction before any stop and again before registry CAS.
"""
from __future__ import annotations

import ast
from hashlib import sha256
import json
from pathlib import Path
import re

ADDITION = "services/quant-api/alembic/versions/20261026_0053_reference_inbox.py"
ADDITION_BLOB = "91e17cb35bad5e22c06d971c9e25cc3391461e5e"
PARENT = "services/quant-api/alembic/versions/20261015_0052_alert_delivery_v2.py"
POLICY = "reference_inbox_preinstalled_additive_0053_v1"
PREFIXES = ("services/quant-api/alembic/", "services/quant-api/app/db/", "services/quant-api/app/models/")
TABLES = ("reference_inbox_inputs", "reference_inbox_deliveries")


class SchemaCompatibilityError(ValueError):
    pass


def require(value, code="COHORT_SCHEMA_CHANGE_UNSUPPORTED"):
    if not value:
        raise SchemaCompatibilityError(code)


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def installed_proof_valid(value):
    return (isinstance(value, dict) and set(value) == {"policy", "revision", "schema_sha256", "database_identity_sha256"}
            and value["policy"] == POLICY and value["revision"] == "20261026_0053"
            and all(isinstance(value[field], str) and re.fullmatch(r"[0-9a-f]{64}", value[field])
                    for field in ("schema_sha256", "database_identity_sha256")))


def prove_reference_inbox_addition(old_files, new_files, *, old_heads, new_heads, installed):
    require(isinstance(old_files, dict) and isinstance(new_files, dict))
    require(PARENT in old_files and ADDITION not in old_files and set(new_files) - set(old_files) == {ADDITION})
    require(not set(old_files) - set(new_files) and all(new_files[path] == blob for path, blob in old_files.items()))
    require(new_files[ADDITION] == ADDITION_BLOB)
    require(all(isinstance(path, str) and path.startswith(PREFIXES) and isinstance(blob, str)
                and re.fullmatch(r"[0-9a-f]{40}", blob) for files in (old_files, new_files) for path, blob in files.items()))
    require(tuple(old_heads) == ("20261015_0052",) and tuple(new_heads) == ("20261026_0053",))
    require(installed_proof_valid(installed), "COHORT_INSTALLED_SCHEMA_UNPROVEN")
    result = {"policy": POLICY, "added_path": ADDITION, "added_blob": ADDITION_BLOB,
              "old_head": "20261015_0052", "new_head": "20261026_0053",
              "old_db": digest(old_files), "new_db": digest(new_files), "installed": installed}
    result["proof_sha256"] = digest(result)
    return result


def validate_transition_proof(proof, *, old_db, new_db):
    try:
        require(set(proof) == {"policy", "added_path", "added_blob", "old_head", "new_head",
                              "old_db", "new_db", "installed", "proof_sha256"})
        require(proof["policy"] == POLICY and proof["added_path"] == ADDITION and proof["added_blob"] == ADDITION_BLOB)
        require(proof["old_head"] == "20261015_0052" and proof["new_head"] == "20261026_0053")
        require(proof["old_db"] == old_db and proof["new_db"] == new_db and old_db != new_db)
        require(installed_proof_valid(proof["installed"]), "COHORT_INSTALLED_SCHEMA_UNPROVEN")
        require(proof["proof_sha256"] == digest({k: v for k, v in proof.items() if k != "proof_sha256"}))
    except (KeyError, TypeError, ValueError) as error:
        raise SchemaCompatibilityError("COHORT_SCHEMA_PROOF_INVALID") from error


def tracked_db_contract(root):
    from app.runtime_bindings import _tracked, _git
    files = {path: blob for path, blob in _tracked(Path(root)).items() if path.startswith(PREFIXES)}
    require(files)
    revisions = {}
    for path in files:
        if not path.startswith("services/quant-api/alembic/versions/") or not path.endswith(".py") or path.endswith("/__init__.py"):
            continue
        values = {}
        for statement in ast.parse(_git(Path(root), "show", "HEAD:" + path)).body:
            targets = statement.targets if isinstance(statement, ast.Assign) else (
                (statement.target,) if isinstance(statement, ast.AnnAssign) else ())
            for target in targets:
                if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                    require(target.id not in values)
                    try:
                        values[target.id] = ast.literal_eval(statement.value)
                    except (ValueError, TypeError):
                        raise SchemaCompatibilityError("COHORT_SCHEMA_CHANGE_UNSUPPORTED") from None
        require(set(values) == {"revision", "down_revision"}
                and isinstance(values["revision"], str) and values["revision"])
        parent = values["down_revision"]
        require(parent is None or isinstance(parent, str) and bool(parent)
                or isinstance(parent, (tuple, list)) and bool(parent)
                and all(isinstance(item, str) and item for item in parent) and len(set(parent)) == len(parent))
        require(values["revision"] not in revisions)
        revisions[values["revision"]] = values["down_revision"]
    parents = {parent for value in revisions.values() for parent in ((value,) if isinstance(value, str) else value or ())}
    require(all(parent in revisions for parent in parents))
    heads = tuple(sorted(set(revisions) - parents))
    visited = set()
    def visit(revision, active):
        require(revision not in active)
        if revision in visited:
            return
        parent = revisions[revision]
        for value in ((parent,) if isinstance(parent, str) else parent or ()):
            visit(value, active | {revision})
        visited.add(revision)
    for head in heads:
        visit(head, set())
    require(visited == set(revisions))
    return files, heads


def _space(value):
    return " ".join(value.split())


# PostgreSQL's canonical deparser output; retain parentheses, casts and boolean
# structure exactly. Unknown server deparser changes fail closed.
CHECKS = {
    "reference_inbox_inputs": {
        "ck_reference_inbox_journal_order": "journal_ms >= 0::numeric AND journal_sequence >= 0::numeric",
        "ck_reference_inbox_input_size": "payload_bytes > 0 AND target_count >= 0",
    },
    "reference_inbox_deliveries": {
        "ck_reference_inbox_delivery_generation": "generation > 0",
        "ck_reference_inbox_delivery_status": "status::text = ANY (ARRAY['PENDING'::character varying, 'WAITING_HISTORY'::character varying, 'COMPLETED'::character varying, 'BLOCKED'::character varying, 'UNKNOWN'::character varying]::text[])",
        "ck_reference_inbox_delivery_completion": "status::text = 'COMPLETED'::text AND calculation_batch_id IS NOT NULL AND calculated_at IS NOT NULL OR status::text <> 'COMPLETED'::text AND calculation_batch_id IS NULL AND calculated_at IS NULL",
    },
}
GUARD_SOURCE = """
        BEGIN
            IF TG_OP = 'DELETE' OR TG_TABLE_NAME = 'reference_inbox_inputs' THEN
                RAISE EXCEPTION 'REFERENCE_INBOX_IMMUTABLE';
            END IF;
            IF ROW(NEW.delivery_id, NEW.input_id, NEW.stream_id, NEW.revision_id,
                   NEW.generation, NEW.activation_receipt_id, NEW.activation_plan_hash,
                   NEW.recording_start, NEW.created_at, NEW.legacy_capture_batch_id)
               IS DISTINCT FROM
               ROW(OLD.delivery_id, OLD.input_id, OLD.stream_id, OLD.revision_id,
                   OLD.generation, OLD.activation_receipt_id, OLD.activation_plan_hash,
                   OLD.recording_start, OLD.created_at, OLD.legacy_capture_batch_id)
               OR OLD.status = 'COMPLETED' AND NEW IS DISTINCT FROM OLD
               OR OLD.status IN ('BLOCKED','UNKNOWN') AND NEW.status <> OLD.status THEN
                RAISE EXCEPTION 'REFERENCE_INBOX_IMMUTABLE';
            END IF;
            RETURN NEW;
        END """


def verify_installed_reference_inbox(session):
    """Read only. Caller supplies a fresh session to the actual Runtime database."""
    from sqlalchemy import inspect, text
    from sqlalchemy.dialects.postgresql import dialect
    from sqlalchemy import UniqueConstraint, ForeignKeyConstraint
    from app.db.readonly import readonly_transaction
    from app.reference_trading.models import ReferenceInboxInput, ReferenceInboxDelivery

    require(session.get_bind().dialect.name == "postgresql", "COHORT_INSTALLED_SCHEMA_UNPROVEN")
    try:
        with readonly_transaction(session, timeout_seconds=20):
            connection = session.connection()
            schema = session.scalar(text("SELECT current_schema()"))
            require(isinstance(schema, str) and schema, "COHORT_INSTALLED_SCHEMA_UNPROVEN")
            inspector = inspect(connection)
            require("alembic_version" in inspector.get_table_names(schema=schema), "COHORT_INSTALLED_SCHEMA_UNPROVEN")
            # Identifier is reflected authority and quoted by the dialect, never
            # interpolated as SQL syntax from an external release plan.
            version_table = connection.dialect.identifier_preparer.quote_schema(schema) + ".alembic_version"
            versions = tuple(session.scalars(text("SELECT version_num FROM " + version_table)))
            require(versions == ("20261026_0053",), "COHORT_INSTALLED_SCHEMA_UNPROVEN")
            identities = tuple(session.execute(text("""
                SELECT current_database(), d.oid, current_schema(), n.oid,
                       inet_server_addr()::text, inet_server_port()
                FROM pg_database d JOIN pg_namespace n ON n.nspname=current_schema()
                WHERE d.datname=current_database()
            """)).one())
            facts = {}
            for model in (ReferenceInboxInput, ReferenceInboxDelivery):
                table = model.__table__
                require(table.name in inspector.get_table_names(schema=schema), "COHORT_INSTALLED_SCHEMA_UNPROVEN")
                table_flags = tuple(session.execute(text("""
                    SELECT c.relkind,c.relpersistence,c.relrowsecurity,c.relforcerowsecurity,c.relispartition,c.reloftype
                    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname=:schema AND c.relname=:table
                """), {"schema": schema, "table": table.name}).one())
                require(table_flags == ("r", "p", False, False, False, 0), "COHORT_INBOX_TABLE_DRIFT")
                attributes = session.scalar(text("""
                    SELECT bool_and(a.attcollation=t.typcollation AND a.attidentity='' AND a.attgenerated='')
                    FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
                    JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_type t ON t.oid=a.atttypid
                    WHERE n.nspname=:schema AND c.relname=:table AND a.attnum>0 AND NOT a.attisdropped
                """), {"schema": schema, "table": table.name})
                require(attributes is True, "COHORT_INBOX_COLUMNS_DRIFT")
                actual_columns = inspector.get_columns(table.name, schema=schema)
                actual = [(column["name"], column["type"].compile(dialect=dialect()), column["nullable"],
                           column.get("default"), bool(column.get("identity")), bool(column.get("computed"))) for column in actual_columns]
                expected = [(column.name, column.type.compile(dialect=dialect()), column.nullable, None, False, False) for column in table.columns]
                require(actual == expected, "COHORT_INBOX_COLUMNS_DRIFT")
                primary_constraint = inspector.get_pk_constraint(table.name, schema=schema)
                require(primary_constraint["name"] == table.name + "_pkey", "COHORT_INBOX_CONSTRAINT_DRIFT")
                primary = primary_constraint["constrained_columns"]
                require(primary == [column.name for column in table.primary_key.columns], "COHORT_INBOX_CONSTRAINT_DRIFT")
                unique = sorted((item["name"], tuple(item["column_names"])) for item in inspector.get_unique_constraints(table.name, schema=schema))
                expected_unique = sorted((item.name, tuple(column.name for column in item.columns)) for item in table.constraints if isinstance(item, UniqueConstraint))
                require(unique == expected_unique, "COHORT_INBOX_CONSTRAINT_DRIFT")
                foreign = inspector.get_foreign_keys(table.name, schema=schema)
                actual_fk = sorted((tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"]),
                                    item["options"].get("ondelete"), item["referred_schema"] or schema) for item in foreign)
                expected_fk = sorted((tuple(column.name for column in item.columns), item.referred_table.name,
                                      tuple(element.column.name for element in item.elements), item.ondelete, schema)
                                     for item in table.constraints if isinstance(item, ForeignKeyConstraint))
                require(actual_fk == expected_fk, "COHORT_INBOX_CONSTRAINT_DRIFT")
                checks = {item["name"]: _space(item["sqltext"]) for item in inspector.get_check_constraints(table.name, schema=schema)}
                require(checks == CHECKS[table.name], "COHORT_INBOX_CHECK_DRIFT")
                flags = tuple(session.execute(text("""
                    SELECT contype, condeferrable, condeferred, convalidated
                    FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
                    JOIN pg_namespace n ON n.oid=t.relnamespace
                    WHERE n.nspname=:schema AND t.relname=:table ORDER BY c.conname
                """), {"schema": schema, "table": table.name}))
                require(len(flags) == 1 + len(unique) + len(foreign) + len(checks)
                        and all(kind in {"p", "u", "f", "c"} and not defer and not deferred and validated
                                for kind, defer, deferred, validated in flags), "COHORT_INBOX_CONSTRAINT_DRIFT")
                indexes = inspector.get_indexes(table.name, schema=schema)
                require(all(not item.get("include_columns") and not item.get("expressions")
                            and item.get("dialect_options", {}).get("postgresql_using", "btree") == "btree"
                            and not item.get("dialect_options", {}).get("postgresql_ops") for item in indexes),
                        "COHORT_INBOX_INDEX_DRIFT")
                custom = {item["name"]: (tuple(item["column_names"]), item["unique"],
                          item.get("dialect_options", {}).get("postgresql_where"))
                          for item in indexes if not item.get("duplicates_constraint")}
                expected_indexes = ({"ix_reference_inbox_day": (("trading_day",), False, None)} if table.name == TABLES[0] else {
                    "ix_reference_inbox_delivery_head": (("stream_id", "input_id"), False, "((status)::text <> 'COMPLETED'::text)"),
                    "ix_reference_inbox_delivery_status": (("status", "updated_at"), False, None),
                })
                require(custom == expected_indexes, "COHORT_INBOX_INDEX_DRIFT")
                valid_indexes = session.scalar(text("""
                    SELECT bool_and(i.indisvalid AND i.indisready AND NOT i.indisexclusion)
                    FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid
                    JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname=:schema AND t.relname=:table
                """), {"schema": schema, "table": table.name})
                require(valid_indexes is True, "COHORT_INBOX_INDEX_DRIFT")
                triggers = tuple(session.execute(text("""
                    SELECT tgname,tgenabled,tgtype,tgnargs,tgqual IS NULL,tgattr::text,tgconstraint,
                           p.proname,p.pronargs,p.prorettype='pg_catalog.trigger'::regtype,
                           l.lanname,p.prosecdef,p.proisstrict,p.proretset,p.provolatile,p.proparallel,
                           p.proconfig,p.prosrc,p.proleakproof,pns.nspname
                    FROM pg_trigger g JOIN pg_class t ON t.oid=g.tgrelid
                    JOIN pg_namespace n ON n.oid=t.relnamespace JOIN pg_proc p ON p.oid=g.tgfoid
                    JOIN pg_namespace pns ON pns.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang
                    WHERE n.nspname=:schema AND t.relname=:table AND NOT g.tgisinternal
                """), {"schema": schema, "table": table.name}))
                require(len(triggers) == 1, "COHORT_INBOX_GUARD_DRIFT")
                guard = tuple(triggers[0])
                require(guard[:17] == ("reference_inbox_immutable", "O", 27, 0, True, "", 0,
                                       "reference_inbox_guard", 0, True, "plpgsql", False, False, False, "v", "u", None)
                        and _space(guard[17]) == _space(GUARD_SOURCE) and guard[18:] == (False, schema),
                        "COHORT_INBOX_GUARD_DRIFT")
                facts[table.name] = {"table_flags": table_flags, "columns": actual, "pk": primary, "unique": unique, "fk": actual_fk,
                                     "checks": checks, "flags": [tuple(row) for row in flags], "indexes": custom,
                                     "guard": guard}
            return {"policy": POLICY, "revision": "20261026_0053", "schema_sha256": digest(facts),
                    "database_identity_sha256": digest(identities)}
    except SchemaCompatibilityError:
        raise
    except Exception:
        raise SchemaCompatibilityError("COHORT_INSTALLED_SCHEMA_UNPROVEN") from None
