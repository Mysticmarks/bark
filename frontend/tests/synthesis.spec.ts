import { test, expect, type Page } from '@playwright/test';

const healthPayload = { status: 'ok', time: '2024-01-01T00:00:00Z', version: '0.1.0' };
const capabilitiesPayload = {
  modalities: ['audio', 'video'],
  video_presets: { fhd: [1920, 1080] },
  audio_bitrates: ['160k', '320k'],
  codecs: { video: 'libx264', audio: 'aac' },
  notes: ['Tests are mocked']
};

function wireMocks(page: Page) {
  page.route('**/api/health', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(healthPayload) }));
  page.route('**/api/capabilities', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(capabilitiesPayload) })
  );
  page.route('**/api/bark/synthesize', async (route, request) => {
    const body = JSON.parse(request.postData() || '{}');
    const response = {
      job_id: 'job-playwright',
      status: body.dry_run ? 'planned' : 'completed',
      plan: {
        prompt_length: (body.prompt as string | undefined)?.length ?? 0,
        modalities: body.modalities ?? ['audio'],
        render_video: Boolean(body.render_video),
        dry_run: Boolean(body.dry_run),
        video_overrides: body.video ?? null,
        routing_priorities: {}
      },
      artifacts: { audio: '/audio/mock.wav' }
    };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(response) });
  });
  page.route('**/audio/mock.wav', (route) =>
    route.fulfill({ status: 200, headers: { 'content-type': 'audio/wav' }, body: 'mock' })
  );
}

// eslint-disable-next-line @typescript-eslint/no-misused-promises
 test.beforeEach(async ({ page }) => {
  wireMocks(page);
  await page.goto('/');
});

test('submits a synthesis job and renders lifecycle data', async ({ page }) => {
  await page.getByLabel('Prompt').fill('A calm voice counting to five.');
  await page.getByText('Synthesize').click();

  await expect(page.getByText('Synthesis started')).toBeVisible();
  await expect(page.getByText('job-playwright')).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText('Status: planned')).toBeVisible();
  await expect(page.getByText('Backend response')).toBeVisible();
});

test('shows validation errors when prompt missing', async ({ page }) => {
  await page.getByText('Synthesize').click();
  const errors = page.locator('#formErrors');
  await expect(errors).toContainText('Prompt cannot be empty.');
});
