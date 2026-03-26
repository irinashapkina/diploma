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
      <div class="row">
        <button :disabled="store.loading || !question.trim() || !coursesStore.selectedCourseId" @click="ask">
          Сформировать ответ
        </button>
      </div>
      <p v-if="store.error" class="pill err">{{ store.error }}</p>
    </ApiPanel>

    <ApiPanel v-if="store.answer" title="Ответ помощника">
      <template v-if="hasConfirmedAnswer">
        <p>{{ store.answer.answer }}</p>
      </template>
      <p v-else class="pill warn">
        Подходящий источник в материалах курса не найден. Лучше уточнить вопрос у преподавателя.
      </p>
    </ApiPanel>

    <ApiPanel v-if="hasConfirmedAnswer && relevantSources.length" title="Релевантные источники">
      <div class="grid-2">
        <section
          v-for="(source, index) in relevantSources"
          :key="`${source.document_title}-${source.page}-${source.source_label || ''}-${index}`"
          class="panel"
        >
          <div class="panel-body">
            <strong>{{ source.document_title }}</strong>
            <p v-if="source.material_type === 'video'" class="muted-note">
              Таймкод: {{ source.source_label || formatTimeRange(source.time_start_sec, source.time_end_sec) }}
            </p>
            <p v-else class="muted-note">Страница: {{ source.page }}</p>
          </div>
        </section>
      </div>
    </ApiPanel>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import ApiPanel from "@/components/ApiPanel.vue";
import { useCoursesStore } from "@/stores/courses";
import { useTutorStore } from "@/stores/tutor";

const store = useTutorStore();
const coursesStore = useCoursesStore();
const question = ref("");

const refusalPatterns = [
  "недостаточно данных",
  "не найден",
  "уточнить вопрос у преподавателя",
];

const relevantSources = computed(() => {
  if (!store.answer?.sources?.length) return [];
  const uniqueKeys = new Set<string>();
  return store.answer.sources
    .filter(
      (source) =>
        source.document_title.trim().length > 0 &&
        (source.material_type === "video" || (Number.isFinite(source.page) && source.page > 0)),
    )
    .filter((source) => {
      const key = `${source.document_title}::${source.page}::${source.source_label || ""}`;
      if (uniqueKeys.has(key)) return false;
      uniqueKeys.add(key);
      return true;
    })
    .slice(0, 3);
});

const hasConfirmedAnswer = computed(() => {
  if (!store.answer) return false;
  const text = (store.answer.answer || "").trim();
  if (!text) return false;
  if (store.answer.confidence < 0.35) return false;
  const lowered = text.toLowerCase();
  if (refusalPatterns.some((pattern) => lowered.includes(pattern))) return false;
  return true;
});

async function ask() {
  if (!coursesStore.selectedCourseId) return;
  await store.ask({
    courseId: coursesStore.selectedCourseId,
    question: question.value,
  });
}

onMounted(() => {
  if (!coursesStore.courses.length) {
    void coursesStore.loadFromBackend();
  }
});

function formatTimeRange(start?: number | null, end?: number | null) {
  if (typeof start !== "number" || typeof end !== "number") return "не указан";
  return `${formatSecs(start)}-${formatSecs(end)}`;
}

function formatSecs(value: number) {
  const total = Math.max(0, Math.floor(value));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) return `${hours.toString().padStart(2, "0")}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
  return `${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
}
</script>
