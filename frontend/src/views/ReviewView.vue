<template>
  <section class="page review-page">
    <header class="page-header">
      <h2>Центр проверки и рекомендаций</h2>
      <p>Проверяйте материалы, получайте замечания и подтверждайте изменения.</p>
    </header>

    <ApiPanel title="Синхронизация источников">
      <div class="single-line-fields single-line-fields--one">
        <label class="field-item">Технология
          <select v-model="technologyFilter" class="large-control">
            <option value="">Все доступные</option>
            <option value="java">Java</option>
          </select>
        </label>
      </div>
      <div class="row">
        <button :disabled="reviewStore.loading" @click="runReferenceSync">Обновить источники</button>
      </div>
    </ApiPanel>

    <ApiPanel title="Запуск проверки материалов">
      <div class="single-line-fields single-line-fields--one">
        <label class="field-item">Курс
          <select v-model="selectedCourseId" class="large-control">
            <option value="">Выберите курс</option>
            <option v-for="course in coursesStore.courses" :key="course.course_id" :value="course.course_id">
              {{ course.title }}
            </option>
          </select>
        </label>
      </div>
      <p class="docs-title">Выберите документы для проверки:</p>
      <div class="doc-list">
        <label v-for="doc in documentsStore.documents" :key="doc.document_id" class="doc-check">
          <input v-model="selectedDocumentIds" type="checkbox" :value="doc.document_id" />
          <span>{{ doc.document_title }}</span>
        </label>
      </div>
      <div class="row">
        <button :disabled="reviewStore.loading || !selectedCourseId" @click="runScan">Запустить проверку</button>
      </div>
      <p v-if="reviewStore.scanSummary" class="muted-note">
        scan_id: {{ reviewStore.scanSummary.scan_id }} · issues: {{ reviewStore.scanSummary.issues_total }}
      </p>
      <p v-if="reviewStore.error" class="pill err">{{ reviewStore.error }}</p>
    </ApiPanel>

    <ApiPanel title="Замечания и рекомендации">
      <div class="single-line-fields">
        <label class="field-item">Документ
          <select v-model="documentFilter" class="large-control">
            <option value="">Все документы</option>
            <option v-for="doc in documentsStore.documents" :key="doc.document_id" :value="doc.document_id">
              {{ doc.document_title }}
            </option>
          </select>
        </label>
        <label class="field-item">Тип замечания
          <select v-model="typeFilter" class="large-control">
            <option value="">Необязательно</option>
            <option v-for="option in typeOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </label>
        <label class="field-item">Статус
          <select v-model="statusFilter" class="large-control">
            <option value="">Все статусы</option>
            <option value="open">Новое</option>
            <option value="applied">Применено</option>
            <option value="rejected">Отклонено</option>
            <option value="review">На проверке</option>
          </select>
        </label>
      </div>

      <div class="row">
        <button :disabled="reviewStore.loading || !selectedCourseId" @click="showIssues">Показать замечания</button>
      </div>

      <table v-if="filteredIssues.length" class="issues-table review-table">
        <thead>
          <tr>
            <th>Статус</th>
            <th>Источник</th>
            <th>Причина</th>
            <th>Рекомендация</th>
            <th>Действие</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="issue in filteredIssues" :key="issue.issue_id">
            <td class="status-cell">
              <strong>{{ statusLabel(issue.status) }}</strong>
              <p v-if="confidenceLabel(issue)" class="issue-meta">{{ confidenceLabel(issue) }}</p>
            </td>
            <td>
              <div>{{ sourceLabel(issue) }}</div>
            </td>
            <td>{{ issue.evidence }}</td>
            <td>{{ issue.suggestion || "—" }}</td>
            <td>
              <button class="secondary action-btn" :disabled="reviewStore.loading">{{ actionLabel(issue.status) }}</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted-note">Нажмите «Показать замечания», чтобы загрузить результаты.</p>
    </ApiPanel>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import ApiPanel from "@/components/ApiPanel.vue";
import { useCoursesStore } from "@/stores/courses";
import { useDocumentsStore } from "@/stores/documents";
import { useReviewStore } from "@/stores/review";
import type { ReviewIssue } from "@/types/api";

const coursesStore = useCoursesStore();
const documentsStore = useDocumentsStore();
const reviewStore = useReviewStore();

const technologyFilter = ref("");
const selectedCourseId = ref("");
const selectedDocumentIds = ref<string[]>([]);
const documentFilter = ref("");
const typeFilter = ref("");
const statusFilter = ref("");

const activeCourseId = computed(() => coursesStore.selectedCourse?.course_id ?? "");
const typeOptions = computed(() => {
  const values = [...new Set(reviewStore.issues.map((item) => item.issue_type))];
  return values.map((value) => ({ value, label: typeLabel(value) }));
});

const filteredIssues = computed(() =>
  reviewStore.issues.filter((issue) => {
    if (documentFilter.value && parseFragment(issue.fragment_id).documentId !== documentFilter.value) return false;
    if (typeFilter.value && issue.issue_type !== typeFilter.value) return false;
    if (statusFilter.value && issue.status !== statusFilter.value) return false;
    return true;
  }),
);

watch(
  () => activeCourseId.value,
  (value) => {
    selectedCourseId.value = value;
    if (!value) return;
    void documentsStore.loadForCourse(value).catch(() => {});
  },
  { immediate: true },
);

async function runReferenceSync() {
  await reviewStore.syncReference(true);
}

async function runScan() {
  if (!selectedCourseId.value) return;
  await documentsStore.loadForCourse(selectedCourseId.value);
  await reviewStore.scanCourse(selectedCourseId.value, true);
}

async function showIssues() {
  if (!selectedCourseId.value) return;
  await documentsStore.loadForCourse(selectedCourseId.value);
  await reviewStore.loadIssues(selectedCourseId.value);
}

function statusLabel(status: string) {
  const key = status.toLowerCase();
  if (key === "applied") return "Применено";
  if (key === "rejected") return "Отклонено";
  if (key === "review") return "На проверке";
  return "Новое";
}

function actionLabel(status: string) {
  const key = status.toLowerCase();
  if (key === "applied") return "Выбрано";
  if (key === "rejected") return "Открыть";
  if (key === "review") return "Открыть";
  return "Применить";
}

function sourceLabel(issue: ReviewIssue) {
  const fragment = parseFragment(issue.fragment_id);
  const doc = documentsStore.documents.find((item) => item.document_id === fragment.documentId);
  const source = issue.source_refs.length ? issue.source_refs.join(", ") : "local";
  return `${doc?.document_title || fragment.documentId || "Документ"}, page ${fragment.page || "?"}, ${source}`;
}

function confidenceLabel(issue: ReviewIssue) {
  const match = issue.evidence.match(/confidence[:=]\s*([0-9.]+)/i);
  if (!match) return "";
  const value = Number(match[1]);
  if (Number.isNaN(value)) return "";
  return `Уверенность: ${value.toFixed(3)}`;
}

function parseFragment(fragmentId: string) {
  const match = fragmentId.match(/^(.*)_p(\d+)$/);
  if (!match) return { documentId: "", page: "" };
  return { documentId: match[1], page: match[2] };
}

function typeLabel(value: string) {
  const map: Record<string, string> = {
    DATE_ACADEMIC_YEAR_MISMATCH: "Несовпадение учебного года",
    DATE_OUTDATED_REFERENCE: "Устаревшая дата",
    TECH_VERSION_OUTDATED: "Устаревшая версия",
    TERM_OUTDATED: "Устаревший термин",
    PERSON_DATES_FUTURE_DEATH_YEAR: "Некорректные даты персоны",
    PERSON_DATES_INCORRECT: "Неточность в биодате",
  };
  return map[value] || value.replaceAll("_", " ");
}

onMounted(() => {
  if (!coursesStore.courses.length) {
    void coursesStore.loadFromBackend();
  }
});
</script>

<style scoped>
.review-page :deep(.panel) {
  border-radius: 16px;
}

.review-page :deep(.panel-head h3) {
  font-size: 1.05rem;
}

.single-line-fields {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.single-line-fields--one {
  grid-template-columns: minmax(320px, 1fr);
  max-width: 620px;
}

.field-item {
  min-width: 0;
}

.large-control {
  min-height: 46px;
  font-size: 1rem;
}

.docs-title {
  margin: 4px 0 0;
  color: #2e3a4d;
  font-weight: 600;
}

.doc-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 16px;
}

.doc-check {
  display: flex;
  gap: 10px;
  align-items: center;
  color: var(--text);
}

.doc-check input {
  width: 16px;
  height: 16px;
}

.review-table th {
  font-size: 0.74rem;
}

.review-table td {
  font-size: 0.95rem;
}

.status-cell {
  min-width: 130px;
}

.issue-meta {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 0.78rem;
}

.action-btn {
  min-width: 108px;
}

@media (max-width: 1200px) {
  .single-line-fields {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .single-line-fields--one {
    grid-template-columns: 1fr;
    max-width: none;
  }
}

@media (max-width: 760px) {
  .single-line-fields {
    grid-template-columns: 1fr;
  }

  .doc-list {
    grid-template-columns: 1fr;
  }
}
</style>
