import axios from "axios";

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();
const baseURL = configuredBaseUrl && configuredBaseUrl.length > 0 ? configuredBaseUrl : "/api";

export const http = axios.create({
  baseURL,
  timeout: 30_000,
});

http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.code === "ERR_NETWORK") {
      const wrapped = new Error(
        "Не удалось подключиться к backend. Проверьте, что API запущен и VITE_API_BASE_URL настроен корректно.",
      );
      return Promise.reject(wrapped);
    }
    return Promise.reject(error);
  },
);
