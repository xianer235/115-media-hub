import { chromium } from 'playwright';

function normalizeRequestedChannel(raw) {
  const value = String(raw || '').trim().toLowerCase();
  if (!value) return 'bundled';
  if (value === 'playwright' || value === 'chromium' || value === 'bundled') return 'bundled';
  return value;
}

function attemptListFor(requestedChannel) {
  if (requestedChannel === 'bundled') {
    return ['bundled', 'chrome'];
  }
  return [requestedChannel, 'bundled'];
}

function launchOptionsFor(channel, headless) {
  if (channel === 'bundled') {
    return { headless };
  }
  return { channel, headless };
}

export function getPreviewBrowserRequestedChannel() {
  return normalizeRequestedChannel(process.env.PREVIEW_BROWSER_CHANNEL || 'bundled');
}

export async function launchPreviewBrowser({ headless = true } = {}) {
  const requestedChannel = getPreviewBrowserRequestedChannel();
  const attempts = attemptListFor(requestedChannel);
  let lastError = null;

  for (const channel of attempts) {
    try {
      const browser = await chromium.launch(launchOptionsFor(channel, headless));
      const fallbackUsed = channel !== requestedChannel;
      if (fallbackUsed) {
        console.warn(
          `[preview-runtime] Browser fallback: requested "${requestedChannel}", using "${channel}".`
        );
      }
      return {
        browser,
        browserMeta: {
          requestedChannel,
          actualChannel: channel,
          fallbackUsed,
        },
      };
    } catch (error) {
      lastError = error;
    }
  }

  const detail = String(lastError?.message || lastError || 'unknown error');
  throw new Error(
    `[preview-runtime] Failed to launch browser. requested="${requestedChannel}", attempts="${attempts.join(' -> ')}". ${detail}`
  );
}

