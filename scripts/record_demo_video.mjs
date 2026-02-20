import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const BASE_URL = process.env.DEMO_BASE_URL || "http://127.0.0.1:8001";
const ADMIN_USER = process.env.DEMO_ADMIN_USER || "demo_admin";
const ADMIN_PASSWORD = process.env.DEMO_ADMIN_PASSWORD || "DemoAdmin123!";
const OUT_DIR = process.env.DEMO_VIDEO_DIR || "docs/demo_video";
const TARGET_FILE = process.env.DEMO_VIDEO_NAME || "orderflow_demo_5_7min.webm";

const HOLD_SHORT = 12000;
const HOLD_MEDIUM = 18000;
const HOLD_LONG = 24000;

async function hold(page, ms, title) {
  console.log(`scene: ${title} (${Math.round(ms / 1000)}s)`);
  await page.waitForTimeout(ms);
}

async function loginAdmin(page) {
  await page.goto(`${BASE_URL}/admin/login/`, { waitUntil: "domcontentloaded" });
  await hold(page, HOLD_SHORT, "admin login screen");
  await page.fill("#id_username", ADMIN_USER);
  await page.fill("#id_password", ADMIN_PASSWORD);
  await Promise.all([
    page.waitForNavigation({ waitUntil: "domcontentloaded" }),
    page.click('input[type="submit"]'),
  ]);
}

async function recordDemo() {
  await fs.mkdir(OUT_DIR, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 },
    recordVideo: {
      dir: OUT_DIR,
      size: { width: 1280, height: 720 },
    },
  });
  const page = await context.newPage();

  console.log("start recording");

  // Intro + storefront
  await page.goto(`${BASE_URL}/storefront/`, { waitUntil: "domcontentloaded" });
  await hold(page, HOLD_LONG, "storefront intro");
  await page.fill("#id_name", "Demo Video User");
  await page.fill("#id_phone", "+79160002233");
  await page.fill("#id_email", "demo.video@example.com");
  await page.fill("#id_selected_product", "Худи");
  await page.fill("#id_quantity", "1");
  await page.fill(
    "#id_free_text",
    "Хочу 1 худи, доставка Москва, Пятницкая 10, телефон +79160002233",
  );
  await hold(page, HOLD_MEDIUM, "storefront filled form");
  await Promise.all([
    page.waitForNavigation({ waitUntil: "domcontentloaded" }),
    page.click('button[type="submit"]'),
  ]);
  await hold(page, HOLD_LONG, "storefront success");

  // Admin
  await loginAdmin(page);
  await hold(page, HOLD_MEDIUM, "admin index");
  await page.goto(`${BASE_URL}/admin/orders/order/`, { waitUntil: "domcontentloaded" });
  await hold(page, HOLD_MEDIUM, "admin orders list");
  if ((await page.locator("#result_list tbody tr").count()) > 0) {
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      page.click("#result_list tbody tr:first-child th a"),
    ]);
    await hold(page, HOLD_MEDIUM, "admin order detail");
  }

  // Dashboard A/B/C/D surfaces
  await page.goto(`${BASE_URL}/dashboard/orders/`, { waitUntil: "domcontentloaded" });
  await hold(page, HOLD_LONG, "dashboard orders table");

  await page.selectOption('select[name="status"]', "needs_info");
  await Promise.all([
    page.waitForNavigation({ waitUntil: "domcontentloaded" }),
    page.click('button[type="submit"]'),
  ]);
  await hold(page, HOLD_MEDIUM, "scenario B needs_info filter");

  await page.selectOption('select[name="status"]', "");
  await page.selectOption('select[name="channel"]', "telegram");
  await Promise.all([
    page.waitForNavigation({ waitUntil: "domcontentloaded" }),
    page.click('button[type="submit"]'),
  ]);
  await hold(page, HOLD_MEDIUM, "telegram channel orders");

  await page.selectOption('select[name="channel"]', "email");
  await Promise.all([
    page.waitForNavigation({ waitUntil: "domcontentloaded" }),
    page.click('button[type="submit"]'),
  ]);
  await hold(page, HOLD_MEDIUM, "email channel orders");

  if ((await page.locator('a[href*="/dashboard/orders/"][href$="/"]').count()) > 0) {
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      page.click('a[href*="/dashboard/orders/"][href$="/"]'),
    ]);
    await hold(page, HOLD_LONG, "dashboard order card and integrations fields");
  }

  await page.goto(`${BASE_URL}/dashboard/stats/`, { waitUntil: "domcontentloaded" });
  await hold(page, HOLD_LONG, "dashboard charts");

  await page.goto(`${BASE_URL}/api/docs/`, { waitUntil: "domcontentloaded" });
  await hold(page, HOLD_LONG, "swagger docs");

  await page.goto("https://orderflow-ai.bpium.ru", { waitUntil: "domcontentloaded" });
  await hold(page, HOLD_MEDIUM, "bpium screen");

  await page.goto("https://github.com/ergon73/orderflow-ai", { waitUntil: "domcontentloaded" });
  await hold(page, HOLD_MEDIUM, "public github repo");

  const rawVideoPath = await page.video().path();
  await context.close();
  await browser.close();

  const targetPath = path.join(OUT_DIR, TARGET_FILE);
  await fs.copyFile(rawVideoPath, targetPath);
  console.log(`saved ${targetPath}`);
}

recordDemo().catch((err) => {
  console.error(err);
  process.exit(1);
});
