<template>
  <section class="page">
    <header class="page-header">
      <h2>Курсы</h2>
      <p>Создайте курс и выберите его как активный для загрузки и обработки материалов.</p>
    </header>

    <ApiPanel title="Новый курс">
      <div class="grid-2">
        <label>Название курса
          <input v-model="createForm.title" placeholder="Например: Введение в алгоритмы" />
        </label>
        <label>Учебный год
          <input v-model="createForm.year_label" placeholder="2025/2026" />
        </label>
        <label>Семестр
          <select v-model="createForm.semester">
            <option value="">Не указан</option>
            <option value="1">1</option>
            <option value="2">2</option>
            <option value="spring">spring</option>
            <option value="autumn">autumn</option>
          </select>
        </label>
        <label>Описание
          <textarea v-model="createForm.description" placeholder="Кратко опишите содержание курса" />
        </label>
      </div>
      <div class="row">
        <button :disabled="store.loading || !createForm.title.trim() || !createForm.year_label.trim()" @click="createCourse">
          Создать курс
        </button>
      </div>
      <p v-if="store.error" class="pill err">{{ store.error }}</p>
    </ApiPanel>

    <ApiPanel title="Список курсов">
      <p v-if="!store.courses.length">Курсы пока не созданы.</p>
      <div v-else class="grid-2">
        <section
          v-for="course in store.courses"
          :key="course.course_id"
          class="panel"
          :style="courseCardStyle(course.course_id)"
        >
          <div class="panel-body">
            <strong>{{ course.title }}</strong>
            <p>{{ course.description || "Описание пока не добавлено." }}</p>
            <p class="muted-note">Учебный год: {{ course.year_label }}</p>
            <p class="muted-note">Семестр: {{ course.semester || "не указан" }}</p>
            <div class="row">
              <button class="secondary" :disabled="store.loading" @click="selectCourse(course.course_id)">
                {{ store.selectedCourseId === course.course_id ? "Активный курс" : "Сделать активным" }}
              </button>
              <RouterLink class="dashboard-action" to="/documents">К материалам</RouterLink>
            </div>
          </div>
        </section>
      </div>
    </ApiPanel>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive } from "vue";

import ApiPanel from "@/components/ApiPanel.vue";
import { useCoursesStore } from "@/stores/courses";

const store = useCoursesStore();

const createForm = reactive({
  title: "",
  description: "",
  year_label: "",
  semester: "",
});

function courseCardStyle(courseId: string) {
  return store.selectedCourseId === courseId ? { borderColor: "#b8c9e4", background: "#f8fbff" } : undefined;
}

async function createCourse() {
  let created = null;
  try {
    created = await store.create({
      title: createForm.title,
      year_label: createForm.year_label,
      semester: createForm.semester || null,
      description: createForm.description || null,
    });
  } catch {
    return;
  }

  if (!created) return;
  createForm.title = "";
  createForm.description = "";
  createForm.year_label = "";
  createForm.semester = "";
}

function selectCourse(courseId: string) {
  store.setSelectedCourse(courseId);
}

onMounted(() => {
  void store.loadFromBackend();
});
</script>
