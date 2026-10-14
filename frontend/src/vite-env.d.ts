/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_PREVIEW_MODE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
