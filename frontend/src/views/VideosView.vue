<template>
  <section class="page">
    <header class="page-header">
      <h2>Видеоматериалы</h2>
      <p>Раздел отключен: в текущем backend отсутствует video flow.</p>
    </header>

    <ApiPanel title="Статус раздела">
      <p class="pill warn">Функциональность видео временно недоступна в этой версии backend.</p>
    </ApiPanel>
  </section>
</template>

<script setup lang="ts">
import ApiPanel from "@/components/ApiPanel.vue";
</script>
