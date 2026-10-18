const { test, expect } = require("@playwright/test");
test("preview never enables hardware writes or real macro execution", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByText("DESIGN PREVIEW · no hardware control"),
  ).toBeVisible();
  await page.getByRole("button", { name: /PRO X2 SUPERSTRIKE/ }).click();
  await expect(page.getByRole("heading", { name: "DPI SPEEDS" })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Apply DPI", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Apply report rate", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Assignments", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Apply assignment", exact: true }),
  ).toBeDisabled();
  expect(errors).toEqual([]);
});
test("profiles can be created with optional fields empty, retained after refresh and selected honestly", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Games & Profiles", exact: true })
    .click();
  await page.getByRole("button", { name: "New profile", exact: true }).click();
  await page.getByLabel("Profile name", { exact: true }).fill("FPS");
  await page.getByRole("button", { name: "Save profile", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "FPS", exact: true }),
  ).toBeVisible();
  await page.reload();
  await page
    .getByRole("button", { name: "Games & Profiles", exact: true })
    .click();
  const card = page
    .locator(".profile-card")
    .filter({ has: page.getByRole("heading", { name: "FPS", exact: true }) });
  await card.getByRole("button", { name: "Activate", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Profile selected.");
  await expect(card.getByText("ACTIVE", { exact: true })).toBeVisible();
});
test("macro editor preserves ordered steps and exposes explicit Linux execution boundary", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Macros", exact: true }).click();
  await page.getByRole("button", { name: "Create macro", exact: true }).click();
  await page.getByLabel("Name", { exact: true }).fill("Test shortcut");
  await page.getByLabel("Step 1 key", { exact: true }).fill("KEY_LEFTCTRL");
  await page.getByRole("button", { name: "Add step", exact: true }).click();
  await page.getByLabel("Step 2 type", { exact: true }).selectOption("delay");
  await page.getByLabel("Step 2 value", { exact: true }).fill("100");
  await page.getByRole("button", { name: "Save macro", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Test shortcut", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/2 steps/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Run", exact: true }),
  ).toBeDisabled();
});
test("catalog is searchable and does not claim every product is Linux supported", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Device catalog/ }).click();
  await page.getByLabel("Search devices", { exact: true }).fill("g502_hero");
  await expect(
    page.locator(".catalog-row").filter({ hasText: "g502_hero" }),
  ).toBeVisible();
  await expect(
    page.getByText(/does not guarantee Linux support/),
  ).toBeVisible();
});
