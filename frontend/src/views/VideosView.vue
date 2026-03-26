<template>
  <section class="page">
    <header class="page-header">
      <h2>Видеоматериалы</h2>
      <p>Здесь отображаются загруженные видео и расшифровка с таймкодами после транскрибации.</p>
    </header>

    <ApiPanel title="Видео курса">
      <p v-if="!activeCourseId" class="pill warn">Выберите активный курс в разделе «Курсы».</p>
      <div v-else class="row">
        <button class="secondary" :disabled="videosStore.loading" @click="refreshVideos">Обновить</button>
      </div>
      <p v-if="videosStore.error" class="pill err">{{ videosStore.error }}</p>
      <p v-else-if="activeCourseId && !videosStore.videos.length">Видео ещё не загружены.</p>
      <table v-else class="issues-table">
        <thead>
          <tr>
            <th>Название</th>
            <th>Сегментов</th>
            <th>Статус</th>
            <th>Действия</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in videosStore.videos" :key="item.document_id">
            <td>{{ item.document_title }}</td>
            <td>{{ item.page_count }}</td>
            <td>
              <StatusPill :label="ingestStatusLabel(item.status)" :variant="ingestStatusVariant(item.status)" />
            </td>
            <td>
              <button class="secondary" :disabled="videosStore.loading" @click="openSegments(item.document_id)">
                Сегменты
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </ApiPanel>

    <ApiPanel v-if="videosStore.selectedVideo" title="Сегменты видео">
      <p>
        <strong>{{ videosStore.selectedVideo.document_title }}</strong>
      </p>
      <p class="muted-note">Статус: {{ ingestStatusLabel(videosStore.selectedVideoStatus) }}</p>
      <p v-if="!videosStore.segments.length" class="muted-note">Сегменты пока недоступны.</p>
      <table v-else class="issues-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Таймкод</th>
            <th>Текст</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="segment in videosStore.segments" :key="segment.segment_id">
            <td>{{ segment.page_number }}</td>
            <td>{{ segment.time_label || formatRange(segment.start_sec, segment.end_sec) }}</td>
            <td>{{ segment.text }}</td>
          </tr>
        </tbody>
      </table>
    </ApiPanel>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, watch } from "vue";

import ApiPanel from "@/components/ApiPanel.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useCoursesStore } from "@/stores/courses";
import { useVideosStore } from "@/stores/videos";
import { ingestStatusLabel, ingestStatusVariant } from "@/utils/ui";

const coursesStore = useCoursesStore();
const videosStore = useVideosStore();
const activeCourseId = computed(() => coursesStore.selectedCourse?.course_id ?? "");
let pollTimer: ReturnType<typeof setInterval> | null = null;

watch(
  () => activeCourseId.value,
  (courseId) => {
    if (!courseId) return;
    void videosStore.loadForCourse(courseId);
  },
  { immediate: true },
);

async function refreshVideos() {
  if (!activeCourseId.value) return;
  await videosStore.loadForCourse(activeCourseId.value);
}

async function openSegments(documentId: string) {
  if (!activeCourseId.value) return;
  await videosStore.loadSegments(activeCourseId.value, documentId);
}

function formatRange(start: number, end: number) {
  return `${formatSecs(start)}-${formatSecs(end)}`;
}

function formatSecs(value: number) {
  const total = Math.max(0, Math.floor(value));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

onMounted(() => {
  if (!coursesStore.courses.length) {
    void coursesStore.loadFromBackend();
  }
  pollTimer = setInterval(() => {
    if (!activeCourseId.value || videosStore.loading) return;
    const hasRunning = videosStore.videos.some((item) => {
      const status = (item.status || "").toLowerCase();
      return status === "uploaded" || status === "transcribing" || status === "indexing";
    });
    if (hasRunning) {
      void videosStore.loadForCourse(activeCourseId.value);
      if (videosStore.selectedVideoId) {
        void videosStore.loadSegments(activeCourseId.value, videosStore.selectedVideoId);
      }
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
