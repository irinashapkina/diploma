export interface TeacherOut {
  teacher_id: string;
  full_name: string;
}

export interface CourseOut {
  course_id: string;
  teacher_id: string;
  title: string;
  year_label: string;
  semester: string | null;
  description: string | null;
  is_active: boolean;
}

export interface CourseCreatePayload {
  teacher_id: string;
  title: string;
  year_label: string;
  semester?: string | null;
  description?: string | null;
}

export interface CourseListResponse {
  courses: CourseOut[];
}

export interface DocumentOut {
  document_id: string;
  course_id: string;
  document_title: string;
  source_pdf: string;
  page_count: number;
}

export interface DocumentListResponse {
  documents: DocumentOut[];
}

export interface UploadResponse {
  status: string;
  document: DocumentOut;
}

export interface IndexCoursePayload {
  document_id?: string | null;
}

export interface IndexCourseResponse {
  status: string;
  result: Record<string, unknown>;
}

export interface AskPayload {
  course_id: string;
  question: string;
  top_k?: number;
  debug?: boolean;
}

export interface TutorSourceRef {
  document_title: string;
  page: number;
  snippet: string;
  score: number;
  type: "text" | "visual";
}

export interface TutorAnswerResponse {
  answer: string;
  confidence: number;
  mode: "text" | "visual" | "hybrid";
  sources: TutorSourceRef[];
  debug?: Record<string, unknown> | null;
}

export interface HealthResponse {
  status: string;
}

export interface ReviewReferenceSyncPayload {
  include_concepts?: boolean;
}

export interface ReviewReferenceSyncSummary {
  run_id: string;
  created_at: string;
  raw_count: number;
  normalized_count: number;
  baseline_items: number;
}

export interface ReviewReferenceSyncResponse {
  status: string;
  summary: ReviewReferenceSyncSummary;
}

export interface ReviewBaselineResponse {
  run_id: string;
  updated_at: string;
  baseline: Record<string, unknown>;
}

export interface ReviewScanPayload {
  use_current_baseline?: boolean;
}

export interface ReviewScanSummary {
  course_id: string;
  scan_id: string;
  total_pages: number;
  issues_total: number;
  suggestions_total: number;
}

export interface ReviewScanResponse {
  status: string;
  summary: ReviewScanSummary;
}

export interface ReviewIssue {
  issue_id: string;
  course_id: string;
  fragment_id: string;
  issue_type: string;
  severity: string;
  claim_role?: string | null;
  confidence?: number | null;
  claim_text?: string | null;
  claim_span?: unknown;
  detected_text: string;
  normalized_text: string;
  evidence: string;
  suggestion: string | null;
  source_refs: string[];
  status: string;
  created_at: string;
  apply_result?: ReviewApplyResult;
}

export interface ReviewIssuesResponse {
  course_id: string;
  scan: Record<string, unknown>;
  issues: ReviewIssue[];
}

export interface ReviewApplyPayload {
  apply_to_pdf?: boolean;
}

export interface ReviewApplyResult {
  apply_id: string;
  course_id: string;
  issue_id: string;
  status: string;
  mode_used: "direct_replace" | "overlay_replace" | "annotation_only";
  fallback_used: boolean;
  message: string;
  updated_pdf_path: string | null;
  source_pdf_path: string | null;
  page_number: number | null;
  fragment_id: string | null;
  created_at: string;
}

export interface ReviewApplyResponse {
  status: string;
  result: ReviewApplyResult;
}

export interface ReviewAppliesResponse {
  course_id: string;
  items: ReviewApplyResult[];
}

export interface ReviewRunOut {
  review_run_id: string;
  course_id: string;
  baseline_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  stats: Record<string, unknown>;
}

export interface ReviewRunsResponse {
  course_id: string;
  items: ReviewRunOut[];
}

export interface ReviewIssueListResponse {
  course_id: string;
  items: ReviewIssue[];
}

export interface ReviewDecisionPayload {
  teacher_id?: string | null;
  comment?: string | null;
}

export interface ReviewEditPayload extends ReviewDecisionPayload {
  edited_text: string;
}

export interface ReviewDecisionResult {
  decision_id: string;
  issue_id: string;
  teacher_id: string;
  decision_type: "accept" | "edit" | "reject";
  edited_text: string | null;
  comment: string | null;
  created_at: string;
}

export interface ReviewDecisionResponse {
  status: string;
  decision: ReviewDecisionResult;
  apply_result?: ReviewApplyResult;
}

export interface DocumentVersionOut {
  document_version_id: string;
  document_id: string;
  version_no: number;
  is_active: boolean;
  parent_version_id: string | null;
  created_from_issue_id: string | null;
  storage_path: string;
  content_hash: string | null;
  meta_json: Record<string, unknown>;
  created_by_teacher_id: string | null;
  created_at: string;
}

export interface DocumentVersionsResponse {
  document_id: string;
  items: DocumentVersionOut[];
}

export interface IndexJobOut {
  index_job_id: string;
  course_id: string;
  document_id: string | null;
  document_version_id: string | null;
  baseline_id: string | null;
  reason: string;
  status: "queued" | "running" | "done" | "failed";
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_text: string | null;
  stats_json: Record<string, unknown>;
}

export interface IndexJobsResponse {
  course_id: string;
  items: IndexJobOut[];
}
