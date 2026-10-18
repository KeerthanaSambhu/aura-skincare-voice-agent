/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Public base URL of the Aura backend, e.g. https://aura-api.example.com. Not a secret. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
