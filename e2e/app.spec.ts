import { test, expect } from '@playwright/test';

test.describe('Navivi Tauri App', () => {
  test('should load the main application UI without crashing', async ({ page }) => {
    // We mock Tauri's core internals so it doesn't immediately crash when run in standard Chrome
    await page.addInitScript(() => {
        (window as any).__TAURI_INTERNALS__ = {
        invoke: async (cmd: string, args: any): Promise<unknown> => {
          console.log(`Mocked invoke: ${cmd}`, args);
          if (cmd === 'plugin:fs|read_dir') return [];
          if (cmd === 'plugin:dialog|open') return null;
          return null;
        },
        ipc: async (): Promise<void> => {},
      };
      
      // Mock plugin-http fetch
      window.fetch = async (url, options) => {
        if (typeof url === 'string' && url.includes('11434')) {
          return new Response(JSON.stringify({ models: [] }));
        }
        return window.fetch(url, options);
      };
    });

    await page.goto('/');

    // Check if there is a main container or title
    await expect(page).toHaveTitle(/Vite \+ React|Navivi/);
    
    // We'll just assert that the page loads by checking for a known text string
    // E.g., "Navivi" or "Project"
    await expect(page.locator('body')).toContainText(/Navivi|Project/i);
    
    // Take a screenshot to verify what it actually looks like in standard Chrome
    await page.screenshot({ path: 'e2e/screenshot.png' });
  });
});

