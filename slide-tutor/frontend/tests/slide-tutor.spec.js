import { expect, test } from "@playwright/test";

test("slide study workflow is interactive", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto("/");
  await expect(page.getByText("Folio", { exact: true })).toBeVisible();
  await expect(page.locator(".slide-canvas").getByText("How memory becomes knowledge")).toBeVisible();

  await page.getByRole("button", { name: "Open slide 3" }).click();
  await expect(page.locator(".slide-canvas").getByText("Attention is a narrow workspace")).toBeVisible();

  await page.evaluate(() => {
    const target = document.querySelector(".slide-canvas .slide-body");
    const range = document.createRange();
    range.selectNodeContents(target);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    target.closest(".slide-stage").dispatchEvent(new MouseEvent("mouseup", {
      bubbles: true,
      clientX: 520,
      clientY: 390,
    }));
  });
  await page.getByRole("button", { name: "Ask about selection" }).click();
  await expect(page.getByText("Selected from slide 3")).toBeVisible();

  const composer = page.getByPlaceholder("Ask about these slides…");
  await composer.fill("Compare this idea with @");
  await page.getByText("Select a range").click();
  await page.locator(".range-fields select").nth(0).selectOption("3");
  await page.locator(".range-fields select").nth(1).selectOption("5");
  await page.getByRole("button", { name: "Reference slides 3–5" }).click();
  await expect(composer).toHaveValue(/@3–@5/);

  await composer.press("Enter");
  await expect(page.getByText("Mock response · no AI connected").last()).toBeVisible();
  await expect(page.getByRole("button", { name: /Slide 5/ })).toBeVisible();
  await page.getByRole("button", { name: /Slide 5/ }).click();
  await expect(page.locator(".slide-canvas").getByText("Practice bringing the idea back")).toBeVisible();

  await page.getByRole("button", { name: /Upload/ }).first().click();
  await expect(page.getByRole("heading", { name: "Upload a slide deck" })).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles("../../tham-khao/Strategyn_JTBD_Playbook.pdf");
  await expect(page.getByRole("heading", { name: "Upload a slide deck" })).toBeHidden();
  await expect(page.locator(".deck-switcher b")).toContainText("Strategyn_JTBD_Playbook");

  expect(errors).toEqual([]);
  await page.screenshot({ path: "artifacts/folio-slide-tutor.png", fullPage: true });
});
