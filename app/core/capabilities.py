"""
Tony's capability registry — R2.1 canonical surface.

R2.1 (2026-06-01) replaced the unprefixed legacy `capabilities` table with
the canonical `tony_capabilities` (paired migration:
db/migrations/20260601120000_create_tony_capabilities.sql). The legacy
table is left in place as read-only historical state; all writes now go
through the canonical API below.

The Python surface is unchanged for facade consumers
(prompt_assembler._capability_state_block, app/api/v1/endpoints/capabilities,
app/core/gap_detector, app/api/v1/endpoints/builder, app/prompts/tony,
app/core/seed_capabilities_v1) — they keep calling get_capabilities,
create_capability, upsert_capability, update_capability, log_capability_gap,
get_capability_summary and continue to see the old dict keys
(name / endpoint / inputs / outputs / last_tested / failure_notes /
added_at). Internally everything resolves against tony_capabilities and
the new canonical column names.

New canonical functions for planner / governor / R2.2-onward consumers:
register_capability, list_capabilities, get_capability, lookup_capabilities,
deprecate_capability — these surface the new column names directly
(capability_key, capability_type, external_effect, verification_method, etc.)
and accept the richer governance metadata.

Design rationale + review: nova-docs/master_plan_v3_self_extending_agent.md
and nova-docs/ops/reviews/2026-06-01/codex-review-master-plan-v2.md.
"""
import psycopg2
import psycopg2.extras
import os
from typing import Any, Dict, List, Optional


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


# ── Canonical column list (returned with both old and new keys) ───────────
_CANONICAL_COLUMNS = (
    "capability_key, display_name, description, status, capability_type, "
    "locator, runner, owner_module, "
    "input_schema, output_schema, invocation_contract, "
    "risk_level, approval_required, external_effect, cost_type, "
    "verification_method, last_tested_at, last_result, last_error, "
    "source, tags, notes, "
    "deprecated_at, created_at, updated_at"
)


def _row_to_dict(row) -> Dict[str, Any]:
    """Translate a tony_capabilities row into a facade-friendly dict that
    contains BOTH the new canonical keys and the old alias keys
    (name, endpoint, inputs, outputs, last_tested, failure_notes, added_at).
    This is the one place where the legacy contract is preserved — keep
    the alias keys here until consumers have migrated to canonical names.
    """
    (capability_key, display_name, description, status, capability_type,
     locator, runner, owner_module,
     input_schema, output_schema, invocation_contract,
     risk_level, approval_required, external_effect, cost_type,
     verification_method, last_tested_at, last_result, last_error,
     source, tags, notes,
     deprecated_at, created_at, updated_at) = row

    return {
        # ── New canonical keys (R2.1+ consumers) ──────────────────────
        "capability_key": capability_key,
        "display_name": display_name,
        "description": description,
        "status": status,
        "capability_type": capability_type,
        "locator": locator,
        "runner": runner,
        "owner_module": owner_module,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "invocation_contract": invocation_contract,
        "risk_level": risk_level,
        "approval_required": approval_required,
        "external_effect": external_effect,
        "cost_type": cost_type,
        "verification_method": verification_method,
        "last_tested_at": last_tested_at.isoformat() if last_tested_at else None,
        "last_result": last_result,
        "last_error": last_error,
        "source": source,
        "tags": list(tags) if tags else [],
        "notes": notes,
        "deprecated_at": deprecated_at.isoformat() if deprecated_at else None,
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,

        # ── Legacy alias keys preserved for facade consumers ───────────
        # prompt_assembler reads `name`, `risk_level`, `approval_required`,
        # `failure_notes`, `status`. capabilities endpoint reads `endpoint`,
        # `inputs`, `outputs`, `last_tested`, `failure_notes`, `added_at`.
        "name": capability_key,
        "endpoint": locator,
        "inputs": input_schema,
        "outputs": output_schema,
        "last_tested": last_tested_at.isoformat() if last_tested_at else None,
        "failure_notes": last_error,
        "added_at": created_at.isoformat() if created_at else None,
    }


def _infer_capability_type(endpoint: Optional[str], status: Optional[str]) -> str:
    """Best-effort capability_type for legacy backfill rows.

    R2.1 marks unknowable types as `legacy_imported` so a future cleanup
    pass can find them. Future writes via register_capability supply the
    type explicitly.
    """
    if status == "not_built":
        return "not_built_placeholder"
    if endpoint and endpoint.startswith("/api/v1/"):
        return "http_endpoint"
    if endpoint == "injected":
        return "python_function"
    if endpoint == "internal":
        return "python_function"
    return "legacy_imported"


# ── Init + backfill ───────────────────────────────────────────────────────

def init_capability_registry_tables() -> None:
    """R2.1 canonical init. Creates tony_capabilities + indexes (idempotent),
    creates capability_gaps log table (unchanged from legacy), backfills
    from the legacy `capabilities` table if it exists.

    Backfill uses INSERT ... ON CONFLICT (capability_key) DO NOTHING so
    re-running this on subsequent boots never overwrites canonical state
    with stale legacy data.
    """
    conn = None
    try:
        conn = get_conn()
        conn.autocommit = True
        with conn.cursor() as cur:
            # Canonical table — kept idempotent so it can co-exist with the
            # paired migration SQL file. ALTER TABLE IF NOT EXISTS chain is
            # the same shape used elsewhere in the codebase.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tony_capabilities (
                    id                  SERIAL PRIMARY KEY,
                    capability_key      TEXT NOT NULL UNIQUE,
                    display_name        TEXT,
                    description         TEXT NOT NULL,
                    status              TEXT NOT NULL DEFAULT 'active',
                    capability_type     TEXT NOT NULL,
                    locator             TEXT,
                    runner              TEXT,
                    owner_module        TEXT,
                    input_schema        JSONB,
                    output_schema       JSONB,
                    invocation_contract JSONB,
                    risk_level          TEXT NOT NULL DEFAULT 'low',
                    approval_required   BOOLEAN NOT NULL DEFAULT false,
                    external_effect     BOOLEAN NOT NULL DEFAULT false,
                    cost_type           TEXT NOT NULL DEFAULT 'free',
                    verification_method JSONB,
                    last_tested_at      TIMESTAMP,
                    last_result         TEXT,
                    last_error          TEXT,
                    source              TEXT,
                    tags                TEXT[] DEFAULT '{}',
                    notes               TEXT,
                    deprecated_at       TIMESTAMP,
                    created_at          TIMESTAMP DEFAULT NOW(),
                    updated_at          TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tony_capabilities_status ON tony_capabilities(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tony_capabilities_type ON tony_capabilities(capability_type)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tony_capabilities_tags ON tony_capabilities USING GIN(tags)")

            # Capability gaps log — keep unchanged from legacy schema; no
            # canonical replacement needed for R2.1 (it's just a log).
            cur.execute("""
                CREATE TABLE IF NOT EXISTS capability_gaps (
                    id SERIAL PRIMARY KEY,
                    request TEXT NOT NULL,
                    proposed_solution TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)

            # Backfill from legacy table (only if it exists; safe no-op
            # otherwise). The ON CONFLICT clause ensures we never overwrite
            # rows that have been written canonically.
            cur.execute("""
                SELECT to_regclass('public.capabilities')
            """)
            legacy_exists = cur.fetchone()[0] is not None
            backfilled = 0
            if legacy_exists:
                cur.execute("""
                    SELECT name, description, status, endpoint, runner,
                           risk_level, approval_required, cost_type,
                           inputs, outputs, last_tested, last_result,
                           failure_notes, notes, added_at, updated_at
                    FROM capabilities
                """)
                legacy_rows = cur.fetchall()
                for (name, description, status, endpoint, runner,
                     risk_level, approval_required, cost_type,
                     inputs, outputs, last_tested, last_result,
                     failure_notes, notes, added_at, updated_at) in legacy_rows:
                    capability_type = _infer_capability_type(endpoint, status)
                    cur.execute("""
                        INSERT INTO tony_capabilities (
                            capability_key, description, status, capability_type,
                            locator, runner,
                            input_schema, output_schema,
                            risk_level, approval_required, cost_type,
                            last_tested_at, last_result, last_error,
                            source, notes,
                            created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (capability_key) DO NOTHING
                    """, (
                        name, description or "", status or "active", capability_type,
                        endpoint, runner,
                        psycopg2.extras.Json(inputs) if inputs else None,
                        psycopg2.extras.Json(outputs) if outputs else None,
                        risk_level or "low",
                        bool(approval_required) if approval_required is not None else False,
                        cost_type or "free",
                        last_tested, last_result, failure_notes,
                        "legacy_capabilities_backfill", notes,
                        added_at, updated_at,
                    ))
                    if cur.rowcount > 0:
                        backfilled += 1
            print(f"[CAPABILITIES] Registry initialised (backfilled {backfilled} legacy row(s))")
    except Exception as e:
        print(f"[CAPABILITIES] Init failed: {e}")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ── Canonical API (R2.1+ consumers) ───────────────────────────────────────

def register_capability(
    capability_key: str,
    description: str,
    *,
    capability_type: str = "skill",
    status: str = "active",
    display_name: Optional[str] = None,
    locator: Optional[str] = None,
    runner: Optional[str] = None,
    owner_module: Optional[str] = None,
    input_schema: Optional[dict] = None,
    output_schema: Optional[dict] = None,
    invocation_contract: Optional[dict] = None,
    risk_level: str = "low",
    approval_required: bool = False,
    external_effect: bool = False,
    cost_type: str = "free",
    verification_method: Optional[dict] = None,
    tags: Optional[List[str]] = None,
    source: Optional[str] = None,
    notes: Optional[str] = None,
) -> int:
    """Insert OR update one capability. Returns row id.

    Use this for all canonical writes. Existing facade functions
    (create_capability / upsert_capability) translate the legacy kwarg
    shape onto this signature.
    """
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO tony_capabilities (
                        capability_key, display_name, description,
                        status, capability_type,
                        locator, runner, owner_module,
                        input_schema, output_schema, invocation_contract,
                        risk_level, approval_required, external_effect, cost_type,
                        verification_method,
                        source, tags, notes, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (capability_key) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        description = EXCLUDED.description,
                        status = EXCLUDED.status,
                        capability_type = EXCLUDED.capability_type,
                        locator = EXCLUDED.locator,
                        runner = EXCLUDED.runner,
                        owner_module = EXCLUDED.owner_module,
                        input_schema = EXCLUDED.input_schema,
                        output_schema = EXCLUDED.output_schema,
                        invocation_contract = EXCLUDED.invocation_contract,
                        risk_level = EXCLUDED.risk_level,
                        approval_required = EXCLUDED.approval_required,
                        external_effect = EXCLUDED.external_effect,
                        cost_type = EXCLUDED.cost_type,
                        verification_method = EXCLUDED.verification_method,
                        source = EXCLUDED.source,
                        tags = EXCLUDED.tags,
                        notes = EXCLUDED.notes,
                        updated_at = NOW()
                    RETURNING id
                """, (
                    capability_key, display_name, description,
                    status, capability_type,
                    locator, runner, owner_module,
                    psycopg2.extras.Json(input_schema) if input_schema else None,
                    psycopg2.extras.Json(output_schema) if output_schema else None,
                    psycopg2.extras.Json(invocation_contract) if invocation_contract else None,
                    risk_level, approval_required, external_effect, cost_type,
                    psycopg2.extras.Json(verification_method) if verification_method else None,
                    source, tags or [], notes,
                ))
                return cur.fetchone()[0]
    finally:
        conn.close()


def list_capabilities(
    *,
    status: Optional[str] = None,
    capability_type: Optional[str] = None,
    include_deprecated: bool = False,
) -> List[Dict[str, Any]]:
    """Return registry entries. Default excludes deprecated rows."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            where = []
            params: List[Any] = []
            if status is not None:
                where.append("status = %s")
                params.append(status)
            if capability_type is not None:
                where.append("capability_type = %s")
                params.append(capability_type)
            if not include_deprecated:
                where.append("deprecated_at IS NULL")
            where_clause = ("WHERE " + " AND ".join(where)) if where else ""
            cur.execute(
                f"SELECT {_CANONICAL_COLUMNS} FROM tony_capabilities {where_clause} "
                f"ORDER BY status, capability_key",
                tuple(params),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_capability(capability_key: str) -> Optional[Dict[str, Any]]:
    """Exact lookup by stable key. Returns None if not found."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_CANONICAL_COLUMNS} FROM tony_capabilities WHERE capability_key = %s",
                (capability_key,),
            )
            row = cur.fetchone()
            return _row_to_dict(row) if row else None
    finally:
        conn.close()


def lookup_capabilities(
    query: Optional[str] = None,
    *,
    tags: Optional[List[str]] = None,
    capability_type: Optional[str] = None,
    status: str = "active",
) -> List[Dict[str, Any]]:
    """Planner-facing search across registry. Case-insensitive ILIKE on
    description + display_name + capability_key for `query`; tag overlap
    for `tags`. Excludes deprecated.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            where = ["deprecated_at IS NULL"]
            params: List[Any] = []
            if status is not None:
                where.append("status = %s")
                params.append(status)
            if capability_type is not None:
                where.append("capability_type = %s")
                params.append(capability_type)
            if query:
                where.append(
                    "(description ILIKE %s OR display_name ILIKE %s OR capability_key ILIKE %s)"
                )
                like = f"%{query}%"
                params.extend([like, like, like])
            if tags:
                where.append("tags && %s")
                params.append(tags)
            cur.execute(
                f"SELECT {_CANONICAL_COLUMNS} FROM tony_capabilities "
                f"WHERE {' AND '.join(where)} ORDER BY capability_key",
                tuple(params),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def deprecate_capability(capability_key: str, reason: Optional[str] = None) -> bool:
    """Mark a capability deprecated without deleting history.

    Sets deprecated_at = NOW() and appends `reason` to notes if provided.
    Returns True if a row was updated.
    """
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                if reason:
                    cur.execute("""
                        UPDATE tony_capabilities
                        SET deprecated_at = NOW(),
                            notes = COALESCE(notes, '') || %s,
                            updated_at = NOW()
                        WHERE capability_key = %s
                    """, (f"\n[deprecated {reason}]", capability_key))
                else:
                    cur.execute("""
                        UPDATE tony_capabilities
                        SET deprecated_at = NOW(), updated_at = NOW()
                        WHERE capability_key = %s
                    """, (capability_key,))
                return cur.rowcount > 0
    finally:
        conn.close()


# ── Legacy facade (preserved signatures, redirected through canonical) ────

def init_capabilities_table():
    """Demoted to wrapper around init_capability_registry_tables().

    Kept under the original name because app/api/v1/router.py _inits list
    references it. R2.1 redirects all canonical writes to tony_capabilities;
    this wrapper preserves the boot contract.
    """
    init_capability_registry_tables()


def get_capabilities(status=None) -> List[Dict[str, Any]]:
    """Facade for the legacy contract. Returns dicts that include the old
    keys (name / endpoint / inputs / outputs / last_tested / failure_notes /
    added_at) plus the new canonical keys.
    """
    return list_capabilities(status=status)


def log_capability_gap(request_text: str, proposed_solution: Optional[str] = None) -> None:
    """Log when Tony encounters something he can't do. Unchanged from
    legacy — the capability_gaps table is a pure log, no canonical
    replacement in R2.1.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO capability_gaps (request, proposed_solution) VALUES (%s, %s)",
            (request_text[:500], proposed_solution),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[CAPABILITIES] Gap log failed: {e}")


def get_capability_summary() -> str:
    """Get a summary string for Tony's system prompt. Unchanged contract."""
    try:
        caps = get_capabilities()
        active = [c["name"] for c in caps if c["status"] == "active"]
        not_built = [c["name"] for c in caps if c["status"] == "not_built"]
        return f"ACTIVE CAPABILITIES: {', '.join(active)}\nNOT YET BUILT: {', '.join(not_built)}"
    except Exception:
        return ""


def _map_legacy_kwargs(kw: Dict[str, Any]) -> Dict[str, Any]:
    """Translate the legacy create/upsert kwarg shape into register_capability's
    canonical kwargs. Old names (endpoint / inputs / outputs / last_tested /
    failure_notes) map onto their new equivalents; unknown keys are dropped.
    """
    mapped: Dict[str, Any] = {}
    rename = {
        "endpoint": "locator",
        "inputs": "input_schema",
        "outputs": "output_schema",
        "last_tested": "last_tested_at",
        "failure_notes": "last_error",
    }
    canonical_allowed = {
        "capability_type", "status", "display_name", "locator", "runner",
        "owner_module", "input_schema", "output_schema", "invocation_contract",
        "risk_level", "approval_required", "external_effect", "cost_type",
        "verification_method", "tags", "source", "notes",
        "last_tested_at", "last_result", "last_error",
    }
    for k, v in kw.items():
        if v is None:
            continue
        target = rename.get(k, k)
        if target in canonical_allowed:
            mapped[target] = v
    return mapped


def create_capability(name: str, description: str, status: str = "active", **kw) -> int:
    """Legacy facade — create a new capability. Maps legacy kwargs onto the
    canonical register_capability signature. Raises psycopg2.IntegrityError
    on duplicate name (UNIQUE on capability_key).
    """
    canonical_kw = _map_legacy_kwargs(kw)
    if "capability_type" not in canonical_kw:
        canonical_kw["capability_type"] = _infer_capability_type(
            kw.get("endpoint"), status
        )
    return register_capability(
        capability_key=name,
        description=description,
        status=status,
        **canonical_kw,
    )


def upsert_capability(name: str, description: str, status: str = "active", **kw) -> int:
    """Legacy facade — insert or update. Same mapping as create_capability;
    register_capability's ON CONFLICT clause does the upsert internally.
    """
    canonical_kw = _map_legacy_kwargs(kw)
    if "capability_type" not in canonical_kw:
        canonical_kw["capability_type"] = _infer_capability_type(
            kw.get("endpoint"), status
        )
    return register_capability(
        capability_key=name,
        description=description,
        status=status,
        **canonical_kw,
    )


def update_capability(name: str, **fields) -> bool:
    """Legacy facade — update by capability_key. Whitelisted columns only.
    Returns True if a row was updated, False if name not found.
    """
    canonical = _map_legacy_kwargs(fields)
    # description is updatable here but not in _map_legacy_kwargs's allowlist
    if fields.get("description") is not None:
        canonical["description"] = fields["description"]
    if not canonical:
        return False

    set_parts: List[str] = []
    values: List[Any] = []
    for k, v in canonical.items():
        if k in ("input_schema", "output_schema", "invocation_contract", "verification_method"):
            set_parts.append(f"{k} = %s")
            values.append(psycopg2.extras.Json(v) if isinstance(v, (dict, list)) else v)
        else:
            set_parts.append(f"{k} = %s")
            values.append(v)
    set_clause = ", ".join(set_parts) + ", updated_at = NOW()"
    values.append(name)

    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE tony_capabilities SET {set_clause} WHERE capability_key = %s",
                    values,
                )
                return cur.rowcount > 0
    finally:
        conn.close()
