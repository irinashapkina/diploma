<template>
  <section class="page">
    <header class="page-header">
      <h2>ИИ-помощник</h2>
      <p>Задайте вопрос по материалам выбранного курса и получите ответ с источниками.</p>
    </header>

    <ApiPanel title="Ваш запрос">
      <p v-if="!coursesStore.selectedCourse" class="pill warn">
        Активный курс не выбран. Выберите курс в разделе «Курсы», чтобы работать в нужном контексте.
      </p>
      <p v-else class="muted-note">
        Активный курс: <strong>{{ coursesStore.selectedCourse.title }}</strong>
      </p>
      <label>
        Вопрос
        <textarea
          v-model="question"
          placeholder="Например: Объясни, что такое тезис Чёрча-Тьюринга простыми словами"
        />
      </label>
      <div class="grid-2">
        <label>Количество источников
          <input v-model.number="topK" type="number" min="1" max="20" />
        </label>
      </div>
      <div class="row">
        <button :disabled="store.loading || !question.trim() || !coursesStore.selectedCourseId" @click="ask">
          Сформировать ответ
        </button>
      </div>
      <p v-if="store.error" class="pill err">{{ store.error }}</p>
    </ApiPanel>

    <ApiPanel v-if="store.answer" title="Ответ помощника">
      <StatusPill
        :label="`Уверенность: ${store.answer.confidence.toFixed(3)}`"
        :variant="store.answer.confidence >= 0.55 ? 'ok' : 'warn'"
      />
      <p>{{ store.answer.answer }}</p>
    </ApiPanel>

    <ApiPanel v-if="store.answer?.sources?.length" title="Использованные источники">
      <table class="issues-table">
        <thead>
          <tr>
            <th>Документ</th>
            <th>Страница</th>
            <th>Тип</th>
            <th>Фрагмент</th>
            <th>Оценка</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(source, index) in store.answer.sources" :key="`${source.document_title}-${source.page}-${index}`">
            <td>{{ source.document_title }}</td>
            <td>{{ source.page }}</td>
            <td>{{ source.type }}</td>
            <td>{{ source.snippet }}</td>
            <td>{{ source.score.toFixed(4) }}</td>
          </tr>
        </tbody>
      </table>
    </ApiPanel>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";

import ApiPanel from "@/components/ApiPanel.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useCoursesStore } from "@/stores/courses";
import { useTutorStore } from "@/stores/tutor";

const store = useTutorStore();
const coursesStore = useCoursesStore();
const question = ref("");
const topK = ref(6);

async function ask() {
  if (!coursesStore.selectedCourseId) return;
  await store.ask({
    courseId: coursesStore.selectedCourseId,
    question: question.value,
    topK: topK.value,
  });
}

onMounted(() => {
  if (!coursesStore.courses.length) {
    void coursesStore.loadFromBackend();
  }
});
</script>
