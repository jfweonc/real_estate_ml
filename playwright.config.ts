import { defineConfig } from "@playwright/test";
import * as dotenv from "dotenv";
dotenv.config({ path: ".env" });

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  reporter: [["list"]],
  use: {
    headless: process.env.HEADLESS !== "false",
    baseURL: "https://matrix.harmls.com/Matrix/",
    storageState: "artifacts/storage-state.json"
  }
});
