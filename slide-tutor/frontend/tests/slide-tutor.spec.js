import { expect, test } from "@playwright/test";

test("slide study workflow is interactive", async ({ page }) => {
  const errors = [];
  let uploadBody = "";
  let chatPayload = null;
  const uploadedSlides = Array.from({ length: 29 }, (_, index) => {
    const slideNumber = index + 1;
    const suffix = String(slideNumber).padStart(12, "0");
    return {
      id: `30000000-0000-0000-0000-${suffix}`,
      slide_number: slideNumber,
      title: slideNumber === 1 ? "AI & LLM Foundation" : `Day 1 · Slide ${slideNumber}`,
      section: slideNumber === 1 ? "AI IN ACTION" : "COURSE MATERIAL",
      normalized_text: slideNumber === 1
        ? "Bạn đang dùng AI mỗi ngày — nhưng thực sự bên trong nó đang làm gì?"
        : `Canonical content for slide ${slideNumber}.`,
      blocks: [{
        id: `40000000-0000-0000-0000-${suffix}`,
        block_type: "paragraph",
        reading_order: 1,
        bullet_level: null,
        text: slideNumber === 1
          ? "Bạn đang dùng AI mỗi ngày — nhưng thực sự bên trong nó đang làm gì?"
          : `Canonical content for slide ${slideNumber}.`,
      }],
    };
  });
  page.on("pageerror", (error) => errors.push(error.message));

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/decks" && request.method() === "POST") {
      uploadBody = request.postData() || "";
      await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({
        deck_id: "10000000-0000-0000-0000-000000000001",
        deck_version_id: "20000000-0000-0000-0000-000000000001",
        status: "uploaded",
        status_url: "/api/decks/10000000-0000-0000-0000-000000000001/status",
      }) });
      return;
    }
    if (path.endsWith("/status")) {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({
        deck_id: "10000000-0000-0000-0000-000000000001",
        deck_version_id: "20000000-0000-0000-0000-000000000001",
        active_version_id: "20000000-0000-0000-0000-000000000001",
        status: "ready",
        stage: "completed",
        slide_count: 29,
        textless_slide_count: 0,
        expected_chunk_count: 29,
        indexed_chunk_count: 29,
        index_status: "in_sync",
        error_code: null,
        error_detail: null,
        created_at: "2026-07-30T00:00:00Z",
        ready_at: "2026-07-30T00:00:01Z",
      }) });
      return;
    }
    if (path.endsWith("/slides")) {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({
        deck_id: "10000000-0000-0000-0000-000000000001",
        deck_version_id: "20000000-0000-0000-0000-000000000001",
        slides: uploadedSlides,
      }) });
      return;
    }
    if (path === "/api/chat/answer") {
      chatPayload = request.postDataJSON();
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({
        conversation_id: "50000000-0000-0000-0000-000000000001",
        message_id: "60000000-0000-0000-0000-000000000001",
        answer: "The course explains what happens inside modern AI and large language models.",
        citations: [{ slide_id: "30000000-0000-0000-0000-000000000001", slide_number: 1, title: "AI & LLM Foundation", chunk_ids: [] }],
        confidence: "high",
        insufficient_evidence: false,
        missing_content_types: [],
        retrieval_debug_id: "70000000-0000-0000-0000-000000000001",
      }) });
      return;
    }
    await route.abort();
  });

  await page.goto("/");
  await expect(page.getByLabel("VLearn - Canteen AI Tutor")).toBeVisible();
  await expect(page.locator(".slide-canvas").getByText("How memory becomes knowledge")).toBeVisible();

  await page.locator(".deck-switcher").click();
  const deckMenu = page.locator(".deck-menu");
  await expect(deckMenu).toBeVisible();
  const menuBounds = await deckMenu.boundingBox();
  const workspaceBounds = await page.locator(".workspace").boundingBox();
  expect(menuBounds.y + menuBounds.height).toBeGreaterThan(workspaceBounds.y);
  const menuIsTopmost = await page.evaluate(({ x, y }) => {
    const menu = document.querySelector(".deck-menu");
    return menu.contains(document.elementFromPoint(x, y));
  }, { x: menuBounds.x + menuBounds.width / 2, y: menuBounds.y + menuBounds.height - 24 });
  expect(menuIsTopmost).toBe(true);
  await deckMenu.getByRole("button").first().click();
  await expect(deckMenu).toBeHidden();

  const panelSeparator = page.getByRole("separator", { name: "Resize tutor panel" });
  const tutorPanel = page.locator(".chat-panel");
  const panelWidthBefore = (await tutorPanel.boundingBox()).width;
  await panelSeparator.focus();
  await panelSeparator.press("ArrowLeft");
  expect((await tutorPanel.boundingBox()).width).toBeGreaterThan(panelWidthBefore);
  await page.getByRole("button", { name: "Hide tutor panel" }).click();
  await expect(page.locator(".workspace")).toHaveClass(/chat-closed/);
  await page.getByRole("button", { name: "Show tutor panel" }).click();
  await expect(page.locator(".workspace")).not.toHaveClass(/chat-closed/);

  await page.getByRole("button", { name: "Open slide 3" }).click();
  await expect(page.locator(".slide-canvas").getByText("Attention is a narrow workspace")).toBeVisible();

  for (let step = 0; step < 6; step += 1) await page.getByRole("button", { name: "Zoom in slide" }).click();
  await expect(page.getByRole("button", { name: "Reset slide zoom" })).toHaveText("250%");
  await expect(page.getByText("Select text to ask the tutor")).toBeHidden();
  const slideStage = page.locator(".slide-stage");
  const scrollMetrics = await slideStage.evaluate((node) => ({
    horizontal: node.scrollWidth > node.clientWidth,
    vertical: node.scrollHeight > node.clientHeight,
    scrollWidth: node.scrollWidth,
    clientWidth: node.clientWidth,
    scrollHeight: node.scrollHeight,
    clientHeight: node.clientHeight,
  }));
  expect(scrollMetrics.horizontal).toBe(true);
  expect(scrollMetrics.vertical).toBe(true);
  await expect.poll(() => slideStage.evaluate((node) => node.scrollLeft + node.scrollTop)).toBe(0);
  const originBounds = await page.evaluate(() => {
    const stage = document.querySelector(".slide-stage");
    const surface = document.querySelector(".slide-scroll-surface");
    return {
      stageLeft: stage.getBoundingClientRect().left,
      stageTop: stage.getBoundingClientRect().top,
      surfaceLeft: surface.getBoundingClientRect().left,
      surfaceTop: surface.getBoundingClientRect().top,
    };
  });
  expect(originBounds.surfaceLeft).toBeGreaterThanOrEqual(originBounds.stageLeft);
  expect(originBounds.surfaceTop).toBeGreaterThanOrEqual(originBounds.stageTop);
  await slideStage.evaluate((node) => node.scrollTo({ left: node.scrollWidth, top: node.scrollHeight }));
  await expect.poll(() => slideStage.evaluate((node) => node.scrollLeft)).toBeGreaterThan(0);
  await expect.poll(() => slideStage.evaluate((node) => node.scrollTop)).toBeGreaterThan(0);
  await slideStage.evaluate((node) => node.scrollTo({ left: 0, top: 0 }));
  await expect.poll(() => slideStage.evaluate((node) => node.scrollLeft + node.scrollTop)).toBe(0);
  await page.getByRole("button", { name: "Reset slide zoom" }).click();
  await expect(page.getByRole("button", { name: "Reset slide zoom" })).toHaveText("100%");
  await expect(page.getByText("Select text to ask the tutor")).toBeVisible();
  await expect.poll(() => slideStage.evaluate((node) => node.scrollLeft + node.scrollTop)).toBe(0);

  await expect(page.getByLabel("Slide annotation tools")).toBeVisible();
  await page.getByRole("button", { name: "Pen annotation tool" }).click();
  const annotationLayer = page.locator(".annotation-layer");
  const annotationBox = await annotationLayer.boundingBox();
  await page.mouse.move(annotationBox.x + 220, annotationBox.y + 210);
  await page.mouse.down();
  await page.mouse.move(annotationBox.x + 390, annotationBox.y + 270, { steps: 8 });
  await page.mouse.up();
  await expect(annotationLayer.locator("polyline")).toHaveCount(1);
  await page.keyboard.press("Control+z");
  await expect(annotationLayer.locator("polyline")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Redo annotation" })).toBeEnabled();
  await page.keyboard.press("Control+Shift+z");
  await expect(annotationLayer.locator("polyline")).toHaveCount(1);

  await page.getByRole("button", { name: "More annotation tools" }).click();
  await page.getByRole("button", { name: "Shape annotation tool" }).click();
  await page.mouse.move(annotationBox.x + 440, annotationBox.y + 150);
  await page.mouse.down();
  await page.mouse.move(annotationBox.x + 600, annotationBox.y + 300, { steps: 5 });
  await page.mouse.up();
  await expect(annotationLayer.locator("ellipse")).toHaveCount(1);

  page.once("dialog", (dialog) => dialog.accept("Review this definition"));
  await page.getByRole("button", { name: "Text annotation tool" }).click();
  await page.mouse.click(annotationBox.x + 260, annotationBox.y + 340);
  await expect(annotationLayer.getByText("Review this definition")).toBeVisible();

  await page.getByRole("button", { name: "Select annotation tool" }).click();

  await page.getByRole("button", { name: "Toggle slide focus" }).click();
  await expect(page.locator(".slide-workspace")).toHaveClass(/is-fullscreen/);
  const fullscreenCanvas = await page.locator(".slide-canvas").boundingBox();
  expect(fullscreenCanvas.width).toBeGreaterThan(900);
  expect(fullscreenCanvas.height).toBeGreaterThan(500);
  await page.getByRole("button", { name: "Toggle slide focus" }).click();
  await expect(page.locator(".slide-workspace")).not.toHaveClass(/is-fullscreen/);

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
  await expect(page.getByText("Mock response · demo deck").last()).toBeVisible();
  await expect(page.getByRole("button", { name: /Slide 5/ })).toBeVisible();
  await page.getByRole("button", { name: /Slide 5/ }).click();
  await expect(page.locator(".slide-canvas").getByText("Practice bringing the idea back")).toBeVisible();

  await page.getByRole("button", { name: /Upload/ }).first().click();
  await expect(page.getByRole("heading", { name: "Upload a slide deck" })).toBeVisible();
  await page.getByRole("dialog").locator('input[type="file"]').setInputFiles("../../data/vlearn-pack/slides/d1-slide-hackathon.pdf");
  await expect(page.getByRole("heading", { name: "Upload a slide deck" })).toBeHidden();
  await expect(page.locator(".deck-switcher b")).toContainText("d1-slide-hackathon");
  await expect(page.locator(".slide-canvas .react-pdf__Page__canvas")).toBeVisible();
  await expect(page.locator(".slide-canvas .react-pdf__Page__textContent span").first()).toBeAttached();
  expect(uploadBody).toContain("00000000-0000-0000-0000-000000000010");

  await page.evaluate(() => {
    const spans = [...document.querySelectorAll(".slide-canvas .react-pdf__Page__textContent span")];
    const target = spans.find((item) => item.textContent.trim().length > 3);
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
  await expect(page.getByText("Selected from slide 1")).toBeVisible();
  await page.locator(".selection-attachment button").click();

  await composer.fill("What is this course about? @1");
  await composer.press("Enter");
  await expect(page.getByText("The course explains what happens inside modern AI and large language models.")).toBeVisible();
  await expect(page.getByRole("button", { name: /Slide 1 · AI & LLM Foundation/ })).toBeVisible();
  expect(chatPayload).toMatchObject({
    conversation_id: null,
    course_id: "00000000-0000-0000-0000-000000000010",
    deck_id: "10000000-0000-0000-0000-000000000001",
    current_slide_id: "30000000-0000-0000-0000-000000000001",
    question: "What is this course about? @1",
    language: "vi",
    references: [{ start: 1, end: 1 }],
  });

  await page.reload();
  await expect(page.locator(".deck-switcher b")).toContainText("d1-slide-hackathon");
  await expect(page.locator(".slide-canvas .react-pdf__Page__canvas")).toBeVisible();
  await expect(page.getByText("What is this course about? @1")).toBeVisible();
  await expect(page.getByText("The course explains what happens inside modern AI and large language models.")).toBeVisible();

  expect(errors).toEqual([]);
  await page.waitForTimeout(350);
  await page.screenshot({ path: "artifacts/folio-slide-tutor.png", fullPage: true });
});

test("upload explains when the backend is unavailable", async ({ page }) => {
  await page.route("**/api/decks", (route) => route.abort("connectionrefused"));
  await page.goto("/");
  await page.getByRole("button", { name: /Upload/ }).first().click();
  await page.getByRole("dialog").locator('input[type="file"]').setInputFiles("../../tham-khao/Strategyn_JTBD_Playbook.pdf");
  await expect(page.getByRole("alert")).toContainText("Cannot connect to the VLearn backend");
  await expect(page.getByRole("heading", { name: "Upload a slide deck" })).toBeVisible();
});
