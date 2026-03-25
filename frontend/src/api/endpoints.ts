import { http } from "./client";
import type {
  AskPayload,
  CourseCreatePayload,
  CourseListResponse,
  CourseOut,
  DocumentListResponse,
  HealthResponse,
  IndexCoursePayload,
  IndexCourseResponse,
  ReviewBaselineResponse,
  ReviewIssuesResponse,
  ReviewReferenceSyncPayload,
  ReviewReferenceSyncResponse,
  ReviewApplyPayload,
  ReviewApplyResponse,
  ReviewAppliesResponse,
  ReviewDecisionPayload,
  ReviewDecisionResponse,
  ReviewEditPayload,
  ReviewIssueListResponse,
  ReviewRunsResponse,
  ReviewScanPayload,
  ReviewScanResponse,
  DocumentVersionsResponse,
  IndexJobsResponse,
  TeacherOut,
  TutorAnswerResponse,
  UploadResponse,
} from "@/types/api";

export const api = {
  health: () => http.get<HealthResponse>("/health").then((r) => r.data),

  createTeacher: (fullName: string) =>
    http.post<TeacherOut>("/teachers", { full_name: fullName }).then((r) => r.data),
  getTeacher: (teacherId: string) => http.get<TeacherOut>(`/teachers/${teacherId}`).then((r) => r.data),

  createCourse: (payload: CourseCreatePayload) => http.post<CourseOut>("/courses", payload).then((r) => r.data),
  listCourses: (teacherId?: string) =>
    http
      .get<CourseListResponse>("/courses", { params: { teacher_id: teacherId || undefined } })
      .then((r) => r.data.courses),

  uploadDocument: (courseId: string, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return http
      .post<UploadResponse>(`/courses/${courseId}/documents/upload`, formData, {
        timeout: 10 * 60_000,
      })
      .then((r) => r.data);
  },
  listDocuments: (courseId: string) =>
    http.get<DocumentListResponse>(`/courses/${courseId}/documents`).then((r) => r.data.documents),
  indexCourse: (courseId: string, payload: IndexCoursePayload) =>
    http
      .post<IndexCourseResponse>(`/courses/${courseId}/index`, payload, {
        timeout: 10 * 60_000,
      })
      .then((r) => r.data),
  askCourse: (courseId: string, payload: AskPayload) =>
    http.post<TutorAnswerResponse>(`/courses/${courseId}/ask`, payload).then((r) => r.data),

  syncReference: (payload: ReviewReferenceSyncPayload = {}) =>
    http.post<ReviewReferenceSyncResponse>("/review/reference/sync", payload).then((r) => r.data),
  getReferenceBaseline: (runId?: string) =>
    http
      .get<ReviewBaselineResponse>("/review/reference/baseline", { params: { run_id: runId || undefined } })
      .then((r) => r.data),
  scanCourseReview: (courseId: string, payload: ReviewScanPayload = {}) =>
    http.post<ReviewScanResponse>(`/review/courses/${courseId}/scan`, payload).then((r) => r.data),
  getCourseIssues: (courseId: string) =>
    http.get<ReviewIssuesResponse>(`/review/courses/${courseId}/issues`).then((r) => r.data),
  listReviewRuns: (courseId: string) =>
    http.get<ReviewRunsResponse>(`/courses/${courseId}/review-runs`).then((r) => r.data),
  listReviewIssues: (
    courseId: string,
    params?: { document_id?: string; status?: string; severity?: string; issue_type?: string; review_run_id?: string },
  ) => http.get<ReviewIssueListResponse>(`/courses/${courseId}/review-issues`, { params }).then((r) => r.data),
  applyIssue: (courseId: string, issueId: string, payload: ReviewApplyPayload = { apply_to_pdf: true }) =>
    http.post<ReviewApplyResponse>(`/review/courses/${courseId}/issues/${issueId}/apply`, payload).then((r) => r.data),
  getCourseApplies: (courseId: string) =>
    http.get<ReviewAppliesResponse>(`/review/courses/${courseId}/applies`).then((r) => r.data),
  acceptIssue: (issueId: string, payload: ReviewDecisionPayload = {}) =>
    http.post<ReviewDecisionResponse>(`/review-issues/${issueId}/accept`, payload).then((r) => r.data),
  editIssue: (issueId: string, payload: ReviewEditPayload) =>
    http.post<ReviewDecisionResponse>(`/review-issues/${issueId}/edit`, payload).then((r) => r.data),
  rejectIssue: (issueId: string, payload: ReviewDecisionPayload = {}) =>
    http.post<ReviewDecisionResponse>(`/review-issues/${issueId}/reject`, payload).then((r) => r.data),
  listDocumentVersions: (documentId: string) =>
    http.get<DocumentVersionsResponse>(`/documents/${documentId}/versions`).then((r) => r.data),
  listCourseIndexJobs: (courseId: string) =>
    http.get<IndexJobsResponse>(`/courses/${courseId}/index-jobs`).then((r) => r.data),
};
