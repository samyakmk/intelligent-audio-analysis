/// <reference types="expo/types" />

declare namespace NodeJS {
  interface ProcessEnv {
    EXPO_PUBLIC_API_URL?: string;
    EXPO_PUBLIC_DEMO_MODE?: string;
    EXPO_PUBLIC_STATUS_POLL_INTERVAL_MS?: string;
    EXPO_PUBLIC_MEDIA_GRANT_REFRESH_SECONDS?: string;
  }
}
