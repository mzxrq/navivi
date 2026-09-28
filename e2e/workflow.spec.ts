import { test, expect } from '@playwright/test';

test.describe('Navivi UI Workflow', () => {
  test.beforeEach(async ({ page }) => {
    // Intercept and Mock Tauri IPC so standard Chrome doesn't crash
    await page.addInitScript(() => {
        (window as any).__TAURI_INTERNALS__ = {
        invoke: async (cmd: string, args: any) => {
          console.log(`Mocked invoke: ${cmd}`, args);
          if (cmd === 'plugin:fs|read_dir') return [];
          if (cmd === 'plugin:dialog|open') return null;
          return null;
        },
        ipc: async (): Promise<void> => {},
      };
      
      // Mock the Tauri Http plugin to fake local Ollama being offline/empty
      const originalFetch = window.fetch;
      window.fetch = async (url, options) => {
        if (typeof url === 'string' && url.includes('11434')) {
          return new Response(JSON.stringify({ models: [] }));
        }
        return originalFetch(url, options);
      };
    });

    await page.goto('/');
  });

  test('should navigate to Map Editor on "New Project" flow', async ({ page }) => {
    // 1. Check Project Manager
    const newProjectBtn = page.getByRole('button', { name: /New Project/i });
    await expect(newProjectBtn).toBeVisible();

    // 2. Click "New Project"
    await newProjectBtn.click();

    // 3. NewProject Modal appears
    const startEditingBtn = page.locator('button').filter({ hasText: /Start Editing|start-editing/i });
    await expect(startEditingBtn).toBeVisible();

    // 4. Click "Start Editing"
    await startEditingBtn.click();

    // 5. Map Editor is loaded (aside represents the sidebar)
    await expect(page.locator('aside')).toBeVisible();
    await expect(page.locator('header')).toContainText(/Untitled/i);
  });
});