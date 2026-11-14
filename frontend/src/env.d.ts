/// <reference types="vite/client" />
declare module "monaco-editor/editor/editor.api" {
  export * from "monaco-editor";
}
declare module "monaco-editor/languages/definitions/python/register";
declare module "monaco-editor/editor/editor.worker?worker" {
  const WorkerCtor: new () => Worker;
  export default WorkerCtor;
}
