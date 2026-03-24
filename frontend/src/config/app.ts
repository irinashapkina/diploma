export const appConfig = {
  teacherId: (import.meta.env.VITE_TEACHER_ID ?? "").trim(),
  teacherName: (import.meta.env.VITE_TEACHER_NAME ?? "Преподаватель").trim(),
};
