<template>
  <div class="layout">
    <aside class="sidebar">
      <h1>Платформа преподавателя</h1>
      <p class="sidebar-subtitle">Рабочее пространство преподавателя</p>
      <nav class="nav">
        <RouterLink v-for="item in navItems" :key="item.to" :to="item.to" class="nav-link">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>

    <main class="content">
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
const navItems = [
  { to: "/", label: "Обзор" },
  { to: "/courses", label: "Курсы" },
  { to: "/documents", label: "Материалы" },
  { to: "/review", label: "Актуализация" },
  { to: "/tutor", label: "ИИ-помощник" },
];
</script>
