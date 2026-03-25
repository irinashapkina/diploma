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
