import { createRouter, createWebHistory } from "vue-router";

import DashboardView from "@/views/DashboardView.vue";
import CoursesView from "@/views/CoursesView.vue";
import DocumentsView from "@/views/DocumentsView.vue";
import ReviewView from "@/views/ReviewView.vue";
import TutorView from "@/views/TutorView.vue";
import VideosView from "@/views/VideosView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: DashboardView },
    { path: "/courses", component: CoursesView },
    { path: "/documents", component: DocumentsView },
    { path: "/videos", component: VideosView },
    { path: "/review", component: ReviewView },
    { path: "/tutor", component: TutorView },
  ],
});
