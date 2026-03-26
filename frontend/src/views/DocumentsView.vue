<template>
  <section class="page">
    <header class="page-header">
      <h2>Материалы</h2>
      <p>Загружайте PDF/DOCX/PPTX и видео (MP4/MOV/M4V/MKV/WEBM), затем индексируйте материалы для поиска и ИИ-ответов.</p>
    </header>

    <ApiPanel title="Загрузка документа">
      <div class="grid-2">
        <label>Курс
          <select v-model="uploadCourseId">
            <option value="">Выберите курс</option>
            <option v-for="course in coursesStore.courses" :key="course.course_id" :value="course.course_id">
              {{ course.title }}
            </option>
          </select>
        </label>
        <label>Файл
          <input type="file" accept=".pdf,.docx,.pptx,.mp4,.mov,.m4v,.mkv,.webm" @change="onFileChange" />
        </label>
      </div>
      <div class="row">
        <button :disabled="documentsStore.loading || !uploadCourseId || !uploadFile" @click="uploadDocument">
          Загрузить материал
        </button>
      </div>
      <p v-if="documentsStore.error" class="pill err">{{ documentsStore.error }}</p>
    </ApiPanel>

    <ApiPanel title="Список документов">
      <div class="row">
        <button class="secondary" :disabled="documentsStore.loading || !activeCourseId" @click="refreshDocuments">
          Обновить список
        </button>
        <button class="secondary" :disabled="documentsStore.loading || !activeCourseId" @click="runCourseIndexing">
          Индексировать весь курс
        </button>
      </div>

      <p v-if="!activeCourseId" class="pill warn">
        Выберите активный курс в разделе «Курсы», чтобы видеть материалы.
      </p>
      <p v-else-if="!documentsStore.documents.length">Пока нет загруженных документов.</p>
      <table v-else class="issues-table">
        <thead>
          <tr>
            <th>Документ</th>
            <th>Тип</th>
            <th>Страниц</th>
            <th>Статус</th>
            <th>Действия</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="doc in documentsStore.documents"
            :key="doc.document_id"
            :style="documentsStore.selectedDocumentId === doc.document_id ? { background: '#f7faff' } : undefined"
          >
            <td>
              <strong>{{ doc.document_title }}</strong>
            </td>
            <td>{{ doc.material_type === "video" ? "Видео" : "Документ" }}</td>
            <td>{{ doc.page_count }}</td>
            <td>
              <StatusPill
                :label="ingestStatusLabel(documentsStore.documentStatuses[doc.document_id] || doc.status || 'uploaded')"
                :variant="ingestStatusVariant(documentsStore.documentStatuses[doc.document_id] || doc.status || 'uploaded')"
              />
            </td>
            <td>
              <div class="row">
                <button class="secondary" :disabled="documentsStore.loading" @click="documentsStore.setSelectedDocument(doc.document_id)">
                  {{ documentsStore.selectedDocumentId === doc.document_id ? "Выбран" : "Открыть" }}
                </button>
                <button :disabled="documentsStore.loading || doc.status === 'transcribing'" @click="runDocumentIndexing(doc.document_id)">
                  Индексировать
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </ApiPanel>

    <ApiPanel v-if="documentsStore.selectedDocument" title="Выбранный документ">
      <p><strong>{{ documentsStore.selectedDocument.document_title }}</strong></p>
      <p class="muted-note">Путь в хранилище: {{ documentsStore.selectedDocument.source_pdf }}</p>
      <div class="row">
        <button :disabled="documentsStore.loading || !activeCourseId" @click="runDocumentIndexing(documentsStore.selectedDocument.document_id)">
          Переиндексировать документ
        </button>
      </div>
    </ApiPanel>

    <ApiPanel v-if="documentsStore.indexResult" title="Результат индексации">
      <p class="muted-note">Статус: {{ documentsStore.indexResult.status }}</p>
      <JsonOutput :data="documentsStore.indexResult.result" />
    </ApiPanel>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";

import ApiPanel from "@/components/ApiPanel.vue";
import JsonOutput from "@/components/JsonOutput.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useCoursesStore } from "@/stores/courses";
import { useDocumentsStore } from "@/stores/documents";
import { ingestStatusLabel, ingestStatusVariant } from "@/utils/ui";

const coursesStore = useCoursesStore();
const documentsStore = useDocumentsStore();

const activeCourseId = computed(() => coursesStore.selectedCourse?.course_id ?? "");
const uploadCourseId = ref(activeCourseId.value);
const uploadFile = ref<File | null>(null);
let pollTimer: ReturnType<typeof setInterval> | null = null;

watch(
  () => activeCourseId.value,
  (courseId) => {
    uploadCourseId.value = courseId;
    if (courseId) {
      void documentsStore.loadForCourse(courseId);
    } else {
      documentsStore.clearCourse();
    }
  },
  { immediate: true },
);

function onFileChange(event: Event) {
  const target = event.target as HTMLInputElement;
  uploadFile.value = target.files?.[0] ?? null;
}

async function uploadDocument() {
  if (!uploadFile.value) return;
  await documentsStore.upload(uploadCourseId.value, uploadFile.value);
  await refreshDocuments();
}

async function refreshDocuments() {
  if (!activeCourseId.value) return;
  await documentsStore.loadForCourse(activeCourseId.value);
}

async function runCourseIndexing() {
  if (!activeCourseId.value) return;
  await documentsStore.index(activeCourseId.value, null);
}

async function runDocumentIndexing(documentId: string) {
  if (!activeCourseId.value) return;
  await documentsStore.index(activeCourseId.value, documentId);
}

onMounted(() => {
  if (!coursesStore.courses.length) {
    void coursesStore.loadFromBackend();
  }
  pollTimer = setInterval(() => {
    if (!activeCourseId.value) return;
    const hasRunning = documentsStore.documents.some((doc) => {
      const status = (documentsStore.documentStatuses[doc.document_id] || doc.status || "").toLowerCase();
      return status === "uploaded" || status === "transcribing" || status === "indexing";
    });
    if (hasRunning && !documentsStore.loading) {
      void refreshDocuments();
    }
  }, 5000);
});

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
});
</script>
