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
      .post<UploadResponse>(`/courses/${courseId}/documents/upload`, formData)
      .then((r) => r.data);
  },
  listDocuments: (courseId: string) =>
    http.get<DocumentListResponse>(`/courses/${courseId}/documents`).then((r) => r.data.documents),
  indexCourse: (courseId: string, payload: IndexCoursePayload) =>
    http.post<IndexCourseResponse>(`/courses/${courseId}/index`, payload).then((r) => r.data),
  askCourse: (courseId: string, payload: AskPayload) =>
    http.post<TutorAnswerResponse>(`/courses/${courseId}/ask`, payload).then((r) => r.data),
};
