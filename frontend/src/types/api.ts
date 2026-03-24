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
