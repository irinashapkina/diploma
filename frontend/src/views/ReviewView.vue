<template>
  <section class="page">
    <header class="page-header">
      <h2>Центр проверки и рекомендаций</h2>
      <p>Раздел отключен: в текущем backend отсутствуют review endpoint’ы.</p>
    </header>

    <ApiPanel title="Статус раздела">
      <p class="pill warn">Функциональность проверки материалов недоступна в этой версии backend.</p>
    </ApiPanel>
  </section>
</template>

<script setup lang="ts">
import ApiPanel from "@/components/ApiPanel.vue";
</script>
