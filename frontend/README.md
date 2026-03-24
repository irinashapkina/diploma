# Frontend Teacher Agent

Frontend на Vue 3 + TypeScript + Vite для существующего backend.

## Запуск

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

## Важные переменные

- `VITE_API_BASE_URL` — базовый URL API.
  - Для локальной разработки через Vite proxy: `/api`
  - Для прямого запроса к backend: `http://127.0.0.1:8000`
- `VITE_TEACHER_ID` — опциональный UUID преподавателя. Если не указан или не найден, frontend создаст контекст преподавателя автоматически.
- `VITE_TEACHER_NAME` — имя преподавателя для автоинициализации (если `VITE_TEACHER_ID` не используется).

## Proxy в dev

В `vite.config.ts` настроен proxy:

- `/api/*` → `http://127.0.0.1:8000/*`

Это позволяет избежать CORS-проблем в dev, если используется `VITE_API_BASE_URL=/api`.
