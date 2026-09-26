# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: e2e\app.spec.ts >> Navivi Tauri App >> should load the main application UI without crashing
- Location: e2e\app.spec.ts:4:3

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
  3  | test.describe('Navivi Tauri App', () => {
  4  |   test('should load the main application UI without crashing', async ({ page }) => {
  5  |     // We mock Tauri's core internals so it doesn't immediately crash when run in standard Chrome
  6  |     await page.addInitScript(() => {
  7  |         (window as any).__TAURI_INTERNALS__ = {
  8  |         invoke: async (cmd: string, args: any): Promise<unknown> => {
  9  |           console.log(`Mocked invoke: ${cmd}`, args);
  10 |           if (cmd === 'plugin:fs|read_dir') return [];
  11 |           if (cmd === 'plugin:dialog|open') return null;
  12 |           return null;
  13 |         },
  14 |         ipc: async (): Promise<void> => {},
  15 |       };
  16 |       
  17 |       // Mock plugin-http fetch
  18 |       window.fetch = async (url, options) => {
  19 |         if (typeof url === 'string' && url.includes('11434')) {
  20 |           return new Response(JSON.stringify({ models: [] }));
  21 |         }
  22 |         return window.fetch(url, options);
  23 |       };
  24 |     });
  25 | 
> 26 |     await page.goto('/');
     |                ^ Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
  27 | 
  28 |     // Check if there is a main container or title
  29 |     await expect(page).toHaveTitle(/Vite \+ React|Navivi/);
  30 |     
  31 |     // We'll just assert that the page loads by checking for a known text string
  32 |     // E.g., "Navivi" or "Project"
  33 |     await expect(page.locator('body')).toContainText(/Navivi|Project/i);
  34 |     
  35 |     // Take a screenshot to verify what it actually looks like in standard Chrome
  36 |     await page.screenshot({ path: 'e2e/screenshot.png' });
  37 |   });
  38 | });
  39 | 
  40 | 
```