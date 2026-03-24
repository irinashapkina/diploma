CREATE TABLE IF NOT EXISTS teachers (
    id UUID PRIMARY KEY,
    full_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS courses (
    id UUID PRIMARY KEY,
    teacher_id UUID NOT NULL REFERENCES teachers(id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    year_label TEXT NOT NULL,
    semester TEXT NULL,
    description TEXT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_course_identity UNIQUE (teacher_id, title, year_label, semester)
);
CREATE INDEX IF NOT EXISTS ix_courses_teacher_id ON courses(teacher_id);

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    uploader_teacher_id UUID NULL REFERENCES teachers(id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    source_pdf_path TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'application/pdf',
    size_bytes BIGINT NULL,
    page_count INT NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error_message TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_document_checksum_by_course UNIQUE (course_id, checksum_sha256)
);
CREATE INDEX IF NOT EXISTS ix_documents_course_id ON documents(course_id);

CREATE TABLE IF NOT EXISTS pages (
    id TEXT PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INT NOT NULL,
    image_path TEXT NOT NULL,
    pdf_text_raw TEXT NOT NULL DEFAULT '',
    ocr_text_raw TEXT NOT NULL DEFAULT '',
    ocr_text_clean TEXT NOT NULL DEFAULT '',
    merged_text TEXT NOT NULL DEFAULT '',
    text_source TEXT NOT NULL,
    pdf_text_quality NUMERIC(4,3) NOT NULL DEFAULT 0,
    ocr_text_quality NUMERIC(4,3) NOT NULL DEFAULT 0,
    language TEXT NOT NULL DEFAULT 'unknown',
    has_diagram BOOLEAN NOT NULL DEFAULT FALSE,
    has_table BOOLEAN NOT NULL DEFAULT FALSE,
    has_code_like_text BOOLEAN NOT NULL DEFAULT FALSE,
    has_large_image BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT uq_page_per_document UNIQUE (document_id, page_number)
);
CREATE INDEX IF NOT EXISTS ix_pages_course_id ON pages(course_id);
CREATE INDEX IF NOT EXISTS ix_pages_document_id ON pages(document_id);

CREATE TABLE IF NOT EXISTS chunks (
    id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    chunk_order INT NOT NULL,
    text TEXT NOT NULL,
    cleaned_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    image_path TEXT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_chunk_order_per_page UNIQUE (page_id, chunk_order)
);
CREATE INDEX IF NOT EXISTS ix_chunks_course_id ON chunks(course_id);
CREATE INDEX IF NOT EXISTS ix_chunks_document_id ON chunks(document_id);
CREATE INDEX IF NOT EXISTS ix_chunks_page_id ON chunks(page_id);

CREATE TABLE IF NOT EXISTS indices (
    id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    index_type TEXT NOT NULL,
    backend TEXT NOT NULL,
    path TEXT NOT NULL,
    vector_dim INT NULL,
    objects_count INT NOT NULL DEFAULT 0,
    model_name TEXT NULL,
    status TEXT NOT NULL,
    checksum TEXT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_course_index_type UNIQUE (course_id, index_type)
);
CREATE INDEX IF NOT EXISTS ix_indices_course_id ON indices(course_id);

CREATE TABLE IF NOT EXISTS ask_messages (
    id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    answer_mode TEXT NOT NULL,
    confidence NUMERIC(4,3) NOT NULL DEFAULT 0,
    question_intent TEXT NULL,
    entities_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    selected_sense_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    expected_answer_shape TEXT NULL,
    support_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence_breakdown_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    debug_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_ask_messages_course_id ON ask_messages(course_id);

CREATE TABLE IF NOT EXISTS answer_sources (
    id UUID PRIMARY KEY,
    message_id UUID NOT NULL REFERENCES ask_messages(id) ON DELETE CASCADE,
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    chunk_id UUID NULL,
    source_type TEXT NOT NULL,
    score NUMERIC(6,4) NOT NULL DEFAULT 0,
    snippet TEXT NOT NULL DEFAULT '',
    used_in_final_answer BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS ix_answer_sources_message_id ON answer_sources(message_id);
CREATE INDEX IF NOT EXISTS ix_answer_sources_course_id ON answer_sources(course_id);
