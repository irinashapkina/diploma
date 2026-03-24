import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { api } from "@/api/endpoints";
import { appConfig } from "@/config/app";
import type { CourseOut, TeacherOut } from "@/types/api";
import { errorMessage } from "@/utils/format";

const STORAGE_KEY = "ta_courses";
const SELECTED_STORAGE_KEY = "ta_selected_course";
const TEACHER_STORAGE_KEY = "ta_teacher";

function loadCourses(): CourseOut[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as CourseOut[]) : [];
  } catch {
    return [];
  }
}

function loadTeacher(): TeacherOut | null {
  try {
    const raw = localStorage.getItem(TEACHER_STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as TeacherOut;
  } catch {
    return null;
  }
}

function saveCourses(courses: CourseOut[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(courses));
}

function saveTeacher(teacher: TeacherOut) {
  localStorage.setItem(TEACHER_STORAGE_KEY, JSON.stringify(teacher));
}

export const useCoursesStore = defineStore("courses", () => {
  const loading = ref(false);
  const error = ref<string | null>(null);

  const courses = ref<CourseOut[]>(loadCourses());
  const teacher = ref<TeacherOut | null>(loadTeacher());
  const selectedCourseId = ref<string | null>(localStorage.getItem(SELECTED_STORAGE_KEY));

  const selectedCourse = computed(() =>
    courses.value.find((course) => course.course_id === selectedCourseId.value) ?? null,
  );

  function setSelectedCourse(courseId: string | null) {
    selectedCourseId.value = courseId;
    if (courseId) {
      localStorage.setItem(SELECTED_STORAGE_KEY, courseId);
    } else {
      localStorage.removeItem(SELECTED_STORAGE_KEY);
    }
  }

  async function ensureTeacherContext() {
    if (teacher.value) {
      try {
        const current = await api.getTeacher(teacher.value.teacher_id);
        teacher.value = current;
        saveTeacher(current);
        return current;
      } catch {
        teacher.value = null;
        localStorage.removeItem(TEACHER_STORAGE_KEY);
      }
    }

    if (appConfig.teacherId) {
      try {
        const existing = await api.getTeacher(appConfig.teacherId);
        teacher.value = existing;
        saveTeacher(existing);
        return existing;
      } catch {
        // If configured ID is missing in backend, create a new teacher context.
      }
    }

    const created = await api.createTeacher(appConfig.teacherName || "Преподаватель");
    teacher.value = created;
    saveTeacher(created);
    return created;
  }

  function upsertCourse(course: CourseOut) {
    const index = courses.value.findIndex((item) => item.course_id === course.course_id);
    if (index >= 0) {
      courses.value[index] = course;
    } else {
      courses.value.unshift(course);
    }
    saveCourses(courses.value);
  }

  async function loadFromBackend() {
    loading.value = true;
    error.value = null;
    try {
      const teacherContext = await ensureTeacherContext();
      const items = await api.listCourses(teacherContext.teacher_id);
      courses.value = items;
      saveCourses(courses.value);
      if (
        selectedCourseId.value &&
        !courses.value.some((course) => course.course_id === selectedCourseId.value)
      ) {
        setSelectedCourse(null);
      }
      return items;
    } catch (err) {
      error.value = errorMessage(err);
      return null;
    } finally {
      loading.value = false;
    }
  }

  async function create(payload: {
    title: string;
    year_label: string;
    semester?: string | null;
    description?: string | null;
  }) {
    loading.value = true;
    error.value = null;
    try {
      const teacherContext = await ensureTeacherContext();
      const created = await api.createCourse({
        teacher_id: teacherContext.teacher_id,
        title: payload.title,
        year_label: payload.year_label,
        semester: payload.semester ?? null,
        description: payload.description ?? null,
      });
      upsertCourse(created);
      setSelectedCourse(created.course_id);
      return created;
    } catch (err) {
      error.value = errorMessage(err);
      return null;
    } finally {
      loading.value = false;
    }
  }

  return {
    loading,
    error,
    courses,
    teacher,
    selectedCourseId,
    selectedCourse,
    ensureTeacherContext,
    loadFromBackend,
    create,
    setSelectedCourse,
  };
});
