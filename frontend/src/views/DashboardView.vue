<template>
  <section class="page">
    <header class="page-header">
      <h2>Обзор рабочего пространства</h2>
      <p>Здесь можно быстро перейти к загрузке материалов и ИИ-помощнику.</p>
    </header>

    <div class="grid-3">
      <section class="panel">
        <div class="panel-body">
          <strong>Активный курс</strong>
          <p>{{ coursesStore.selectedCourse?.title || "Курс не выбран" }}</p>
          <RouterLink class="dashboard-action" to="/courses">Открыть курсы</RouterLink>
        </div>
      </section>

      <section class="panel">
        <div class="panel-body">
          <strong>Документы курса</strong>
          <p>{{ documentsStore.documents.length }} {{ docWord }}</p>
          <RouterLink class="dashboard-action" to="/documents">Перейти к материалам</RouterLink>
        </div>
      </section>

      <section class="panel">
        <div class="panel-body">
          <strong>ИИ-помощник</strong>
          <p>Ответы по материалам выбранного курса</p>
          <RouterLink class="dashboard-action" to="/tutor">Открыть помощника</RouterLink>
        </div>
      </section>
    </div>

    <ApiPanel title="Последние материалы">
      <p v-if="!lastMaterials.length">Пока нет загруженных материалов.</p>
      <table v-else class="issues-table">
        <thead>
          <tr>
            <th>Название</th>
            <th>Тип</th>
            <th>Страниц</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in lastMaterials" :key="item.id">
            <td>{{ item.name }}</td>
            <td>{{ item.type }}</td>
            <td>{{ item.pages }}</td>
          </tr>
        </tbody>
      </table>
    </ApiPanel>

    <ApiPanel title="Быстрые действия">
      <div class="row">
        <RouterLink class="dashboard-action" to="/documents">Загрузить документ</RouterLink>
        <RouterLink class="dashboard-action" to="/tutor">Задать вопрос ИИ-помощнику</RouterLink>
      </div>
    </ApiPanel>

    <ApiPanel title="Служебное состояние системы">
      <p class="muted-note">
        Этот блок не влияет на учебные сценарии и нужен только для технического контроля доступности
        сервиса.
      </p>
      <div v-if="healthStore.health" class="row">
        <StatusPill
          :label="`Backend API: ${healthStore.health.status === 'ok' ? 'доступен' : healthStore.health.status}`"
          :variant="healthStore.health.status === 'ok' ? 'ok' : 'warn'"
        />
      </div>
      <p v-if="healthStore.error" class="pill err">{{ healthStore.error }}</p>
    </ApiPanel>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, watch } from "vue";

import ApiPanel from "@/components/ApiPanel.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useCoursesStore } from "@/stores/courses";
import { useDocumentsStore } from "@/stores/documents";
import { useHealthStore } from "@/stores/health";

const healthStore = useHealthStore();
const coursesStore = useCoursesStore();
const documentsStore = useDocumentsStore();

const docWord = computed(() => {
  const count = documentsStore.documents.length;
  if (count % 10 === 1 && count % 100 !== 11) return "документ";
  if (count % 10 >= 2 && count % 10 <= 4 && (count % 100 < 10 || count % 100 >= 20)) {
    return "документа";
  }
  return "документов";
});

const lastMaterials = computed(() =>
  documentsStore.documents.map((item) => ({
    id: item.document_id,
    name: item.document_title || "Документ без имени",
    type: "Документ",
    pages: item.page_count,
  })),
);

watch(
  () => coursesStore.selectedCourse?.course_id,
  (courseId) => {
    if (courseId) {
      void documentsStore.loadForCourse(courseId);
    }
  },
  { immediate: true },
);

onMounted(() => {
  if (!coursesStore.courses.length) {
    void coursesStore.loadFromBackend();
  }
  if (!healthStore.health) {
    void healthStore.fetchHealth();
  }
});
</script>
