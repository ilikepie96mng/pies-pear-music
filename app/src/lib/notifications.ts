import {
  isPermissionGranted,
  requestPermission,
  sendNotification
} from '@tauri-apps/plugin-notification';

/**
 * Ensures notification permissions are granted before sending.
 * Returns false silently if notifications are unsupported, denied, or in a web browser context.
 */
async function ensurePermission(): Promise<boolean> {
  try {
    let granted = await isPermissionGranted();
    if (!granted) {
      const permission = await requestPermission();
      granted = permission === 'granted';
    }
    return granted;
  } catch (err) {
    // Non-Tauri environment or notification plugin unavailable
    console.debug('Notification permission check skipped/unavailable:', err);
    return false;
  }
}

/**
 * Dispatches a desktop system notification safely.
 */
export async function sendDesktopNotification(title: string, body: string): Promise<void> {
  try {
    const allowed = await ensurePermission();
    if (!allowed) return;

    sendNotification({
      title,
      body
    });
  } catch (err) {
    console.debug('Failed to send desktop notification:', err);
  }
}

/**
 * Notifies when a playlist sync begins.
 */
export async function notifySyncStarted(playlistName: string): Promise<void> {
  const name = playlistName.trim() || 'Library';
  await sendDesktopNotification(
    'Sync Started',
    `Beginning sync for "${name}"...`
  );
}

/**
 * Notifies when a playlist sync completes successfully.
 */
export async function notifySyncCompleted(
  playlistName: string,
  newCount: number = 0,
  skippedCount: number = 0
): Promise<void> {
  const name = playlistName.trim() || 'Library';
  let details = '';
  if (newCount > 0 && skippedCount > 0) {
    details = `Added ${newCount} new track${newCount === 1 ? '' : 's'}, ${skippedCount} up to date.`;
  } else if (newCount > 0) {
    details = `Added ${newCount} new track${newCount === 1 ? '' : 's'}.`;
  } else if (skippedCount > 0) {
    details = `All ${skippedCount} track${skippedCount === 1 ? '' : 's'} up to date.`;
  } else {
    details = 'Sync finished successfully.';
  }

  await sendDesktopNotification(
    'Sync Complete',
    `"${name}": ${details}`
  );
}

/**
 * Notifies when a playlist sync encounters a failure.
 */
export async function notifySyncFailed(
  playlistName: string,
  errorMessage: string
): Promise<void> {
  const name = playlistName.trim() || 'Library';
  const cleanMsg = errorMessage.trim() || 'Unknown error occurred.';
  await sendDesktopNotification(
    'Sync Failed',
    `"${name}": ${cleanMsg}`
  );
}

/**
 * Notifies when audio stream FLAC integrity scanning completes.
 */
export async function notifyIntegrityCompleted(corruptedCount: number): Promise<void> {
  if (corruptedCount === 0) {
    await sendDesktopNotification(
      'Integrity Scan Passed',
      'All scanned audio files verified with valid FLAC stream frames.'
    );
  } else {
    await sendDesktopNotification(
      'Integrity Issues Detected',
      `Found ${corruptedCount} corrupted audio file${corruptedCount === 1 ? '' : 's'} with invalid stream headers.`
    );
  }
}

/**
 * Notifies when a DAP player export job finishes.
 */
export async function notifyDapExportCompleted(
  playlistName: string,
  exportedCount: number
): Promise<void> {
  const name = playlistName.trim() || 'Playlist';
  await sendDesktopNotification(
    'DAP Export Complete',
    `Exported ${exportedCount} track${exportedCount === 1 ? '' : 's'} for "${name}" to DAP storage.`
  );
}
