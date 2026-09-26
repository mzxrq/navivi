# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: e2e\workflow.spec.ts >> Navivi UI Workflow >> should navigate to Map Editor on "New Project" flow
- Location: e2e\workflow.spec.ts:30:3

# Error details

```
Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
Call log:
  - navigating to "/", waiting until "load"

```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | 
  3  | test.describe('Navivi UI Workflow', () => {
  4  |   test.beforeEach(async ({ page }) => {
  5  |     // Intercept and Mock Tauri IPC so standard Chrome doesn't crash
  6  |     await page.addInitScript(() => {
  7  |         (window as any).__TAURI_INTERNALS__ = {
  8  |         invoke: async (cmd: string, args: any) => {
  9  |           console.log(`Mocked invoke: ${cmd}`, args);
  10 |           if (cmd === 'plugin:fs|read_dir') return [];
  11 |           if (cmd === 'plugin:dialog|open') return null;
  12 |           return null;
  13 |         },
  14 |         ipc: async (): Promise<void> => {},
  15 |       };
  16 |       
  17 |       // Mock the Tauri Http plugin to fake local Ollama being offline/empty
  18 |       const originalFetch = window.fetch;
  19 |       window.fetch = async (url, options) => {
  20 |         if (typeof url === 'string' && url.includes('11434')) {
  21 |           return new Response(JSON.stringify({ models: [] }));
  22 |         }
  23 |         return originalFetch(url, options);
  24 |       };
  25 |     });
  26 | 
> 27 |     await page.goto('/');
     |                ^ Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
  28 |   });
  29 | 
  30 |   test('should navigate to Map Editor on "New Project" flow', async ({ page }) => {
  31 |     // 1. Check Project Manager
  32 |     const newProjectBtn = page.getByRole('button', { name: /New Project/i });
  33 |     await expect(newProjectBtn).toBeVisible();
  34 | 
  35 |     // 2. Click "New Project"
  36 |     await newProjectBtn.click();
  37 | 
  38 |     // 3. NewProject Modal appears
  39 |     const startEditingBtn = page.locator('button').filter({ hasText: /Start Editing|start-editing/i });
  40 |     await expect(startEditingBtn).toBeVisible();
  41 | 
  42 |     // 4. Click "Start Editing"
  43 |     await startEditingBtn.click();
  44 | 
  45 |     // 5. Map Editor is loaded (aside represents the sidebar)
  46 |     await expect(page.locator('aside')).toBeVisible();
  47 |     await expect(page.locator('header')).toContainText(/Untitled/i);
  48 |   });
  49 | });
```