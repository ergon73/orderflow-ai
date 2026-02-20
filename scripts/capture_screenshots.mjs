import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const BASE_URL = process.env.DEMO_BASE_URL || "http://127.0.0.1:8001";
const ADMIN_USER = process.env.DEMO_ADMIN_USER || "demo_admin";
const ADMIN_PASSWORD = process.env.DEMO_ADMIN_PASSWORD || "DemoAdmin123!";
const OUT_DIR = process.env.DEMO_SCREENSHOT_DIR || "docs/screenshots";

async function ensureOutDir() {
  await fs.mkdir(OUT_DIR, { recursive: true });
}

async function saveShot(page, fileName) {
  const target = path.join(OUT_DIR, fileName);
  await page.screenshot({ path: target, fullPage: true });
  console.log(`saved ${target}`);
}

async function loginAdmin(page) {
  await page.goto(`${BASE_URL}/admin/login/`, { waitUntil: "domcontentloaded" });
  await saveShot(page, "04_admin_login.png");
  await page.fill("#id_username", ADMIN_USER);
  await page.fill("#id_password", ADMIN_PASSWORD);
  await Promise.all([
    page.waitForNavigation({ waitUntil: "domcontentloaded" }),
    page.click('input[type="submit"]'),
  ]);
}

async function capture() {
  await ensureOutDir();

  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
      viewport: { width: 1920, height: 1080 },
    });
    const page = await context.newPage();
    page.setDefaultTimeout(20000);

    await page.goto(`${BASE_URL}/storefront/`, { waitUntil: "domcontentloaded" });
    await saveShot(page, "01_storefront.png");

    await page.fill("#id_name", "Demo Screenshot User");
    await page.fill("#id_phone", "+79160001122");
    await page.fill("#id_email", "demo.screenshots@example.com");
    await page.fill("#id_selected_product", "Кружка");
    await page.fill("#id_quantity", "2");
    await page.fill("#id_free_text", "Хочу 2 кружки, доставка Москва, Арбат 5, телефон +79160001122");
    await saveShot(page, "02_storefront_filled_form.png");

    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      page.click('button[type="submit"]'),
    ]);
    await page.waitForSelector("text=Заказ принят");
    await saveShot(page, "03_storefront_success.png");

    await loginAdmin(page);
    await page.waitForSelector("text=Администрирование Django");
    await saveShot(page, "05_admin_index.png");

    await page.goto(`${BASE_URL}/admin/orders/order/`, { waitUntil: "domcontentloaded" });
    await saveShot(page, "06_admin_orders_list.png");

    const hasAdminOrderRows = (await page.locator("#result_list tbody tr").count()) > 0;
    if (hasAdminOrderRows) {
      await Promise.all([
        page.waitForNavigation({ waitUntil: "domcontentloaded" }),
        page.click("#result_list tbody tr:first-child th a"),
      ]);
      await saveShot(page, "07_admin_order_detail.png");
    }

    await page.goto(`${BASE_URL}/dashboard/orders/`, { waitUntil: "domcontentloaded" });
    await saveShot(page, "08_dashboard_orders.png");

    await page.selectOption('select[name="status"]', "needs_info");
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      page.click('button[type="submit"]'),
    ]);
    await saveShot(page, "09_dashboard_orders_filtered.png");

    await page.selectOption('select[name="status"]', "");
    await page.selectOption('select[name="channel"]', "telegram");
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      page.click('button[type="submit"]'),
    ]);
    await saveShot(page, "14_dashboard_channel_telegram.png");

    await page.selectOption('select[name="channel"]', "email");
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      page.click('button[type="submit"]'),
    ]);
    await saveShot(page, "15_dashboard_channel_email.png");

    const hasDashboardOrderRows = (await page.locator("table tbody tr").count()) > 0;
    if (hasDashboardOrderRows) {
      await Promise.all([
        page.waitForNavigation({ waitUntil: "domcontentloaded" }),
        page.click('a[href*="/dashboard/orders/"][href$="/"]'),
      ]);
      await saveShot(page, "10_dashboard_order_detail.png");
    }

    await page.goto(`${BASE_URL}/dashboard/stats/`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("canvas#statusChart");
    await saveShot(page, "11_dashboard_stats.png");

    await page.goto(`${BASE_URL}/api/docs/`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);
    await saveShot(page, "12_api_docs_swagger.png");
  } finally {
    if (browser) {
      await browser.close();
    }
  }
}

capture().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
