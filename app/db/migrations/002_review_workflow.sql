CREATE TABLE IF NOT EXISTS reference_baseline_runs (
    id UUID PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    technology TEXT NOT NULL DEFAULT 'java',
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    baseline_json JSONB NULL,
    raw_facts_path TEXT NULL,
    normalized_facts_path TEXT NULL,
    baseline_path TEXT NULL,
    checksum TEXT NULL
);
CREATE INDEX IF NOT EXISTS ix_reference_baseline_runs_run_id ON reference_baseline_runs(run_id);

CREATE TABLE IF NOT EXISTS review_runs (
    id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    baseline_id UUID NOT NULL REFERENCES reference_baseline_runs(id) ON DELETE RESTRICT,
    triggered_by_teacher_id UUID NULL REFERENCES teachers(id) ON DELETE RESTRICT,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ NULL,
    stats_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_text TEXT NULL
);
CREATE INDEX IF NOT EXISTS ix_review_runs_course_id ON review_runs(course_id);
CREATE INDEX IF NOT EXISTS ix_review_runs_baseline_id ON review_runs(baseline_id);

CREATE TABLE IF NOT EXISTS document_versions (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_no INT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    parent_version_id UUID NULL REFERENCES document_versions(id) ON DELETE SET NULL,
    created_from_issue_id UUID NULL,
    storage_path TEXT NOT NULL,
    content_hash TEXT NULL,
    meta_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_teacher_id UUID NULL REFERENCES teachers(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_document_version_no UNIQUE (document_id, version_no)
);
CREATE INDEX IF NOT EXISTS ix_document_versions_document_id ON document_versions(document_id);
CREATE INDEX IF NOT EXISTS ix_document_versions_is_active ON document_versions(is_active);

CREATE TABLE IF NOT EXISTS review_issues (
    id UUID PRIMARY KEY,
    review_run_id UUID NOT NULL REFERENCES review_runs(id) ON DELETE CASCADE,
    baseline_id UUID NOT NULL REFERENCES reference_baseline_runs(id) ON DELETE RESTRICT,
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_version_id UUID NULL REFERENCES document_versions(id) ON DELETE SET NULL,
    page_number INT NULL,
    fragment_id TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    claim_role TEXT NULL,
    confidence NUMERIC(5,4) NULL,
    claim_text TEXT NULL,
    claim_span_json JSONB NULL,
    detected_text TEXT NULL,
    normalized_text TEXT NULL,
    evidence_user TEXT NULL,
    evidence_debug_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    suggestion_text TEXT NULL,
    suggestion_debug_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_refs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL,
    superseded_by_issue_id UUID NULL REFERENCES review_issues(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_review_issues_course_id ON review_issues(course_id);
CREATE INDEX IF NOT EXISTS ix_review_issues_issue_type ON review_issues(issue_type);
CREATE INDEX IF NOT EXISTS ix_review_issues_status ON review_issues(status);
CREATE INDEX IF NOT EXISTS ix_review_issues_review_run_id ON review_issues(review_run_id);

CREATE TABLE IF NOT EXISTS review_decisions (
    id UUID PRIMARY KEY,
    issue_id UUID NOT NULL REFERENCES review_issues(id) ON DELETE CASCADE,
    teacher_id UUID NOT NULL REFERENCES teachers(id) ON DELETE RESTRICT,
    decision_type TEXT NOT NULL,
    edited_text TEXT NULL,
    comment TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_review_decisions_issue_id ON review_decisions(issue_id);

CREATE TABLE IF NOT EXISTS material_revisions (
    id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_version_id UUID NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    source_issue_id UUID NOT NULL REFERENCES review_issues(id) ON DELETE CASCADE,
    decision_id UUID NULL REFERENCES review_decisions(id) ON DELETE SET NULL,
    revision_type TEXT NOT NULL,
    apply_mode TEXT NOT NULL,
    original_text TEXT NULL,
    applied_text TEXT NULL,
    location_json JSONB NULL,
    fallback_used BOOLEAN NOT NULL DEFAULT FALSE,
    message TEXT NULL,
    applied_by_teacher_id UUID NULL REFERENCES teachers(id) ON DELETE RESTRICT,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_material_revisions_course_id ON material_revisions(course_id);
CREATE INDEX IF NOT EXISTS ix_material_revisions_document_id ON material_revisions(document_id);

CREATE TABLE IF NOT EXISTS index_jobs (
    id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    document_id UUID NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_version_id UUID NULL REFERENCES document_versions(id) ON DELETE SET NULL,
    baseline_id UUID NULL REFERENCES reference_baseline_runs(id) ON DELETE SET NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    error_text TEXT NULL,
    stats_json JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_index_jobs_course_id ON index_jobs(course_id);
CREATE INDEX IF NOT EXISTS ix_index_jobs_status ON index_jobs(status);

CREATE TABLE IF NOT EXISTS apply_operations (
    id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    issue_id UUID NOT NULL REFERENCES review_issues(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INT NULL,
    mode_used TEXT NOT NULL,
    fallback_used BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL,
    updated_pdf_path TEXT NULL,
    source_pdf_path TEXT NULL,
    message TEXT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_apply_operations_course_id ON apply_operations(course_id);
CREATE INDEX IF NOT EXISTS ix_apply_operations_issue_id ON apply_operations(issue_id);
