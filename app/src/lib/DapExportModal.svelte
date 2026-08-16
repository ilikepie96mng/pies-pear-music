<script lang="ts">
  import { open as openDialog } from "@tauri-apps/plugin-dialog";
  import { openPath } from "@tauri-apps/plugin-opener";
  import { api, type DapExportResult } from "../api";

  interface Props {
    playlistName: string;
    trackCount: number;
    onclose: () => void;
  }

  let { playlistName, trackCount, onclose }: Props = $props();

  let targetDir = $state("");
  let format = $state<"opus" | "aac">("opus");
  let bitrate = $state<string>("160k");
  let exporting = $state(false);
  let error = $state<string | null>(null);
  let result = $state<DapExportResult | null>(null);

  function onFormatChange(newFmt: "opus" | "aac") {
    format = newFmt;
    if (newFmt === "opus" && (bitrate === "256k" || !bitrate)) {
      bitrate = "160k";
    } else if (newFmt === "aac" && (bitrate === "160k" || !bitrate)) {
      bitrate = "256k";
    }
  }

  async function browseFolder() {
    try {
      const selected = await openDialog({
        directory: true,
        multiple: false,
        title: "Select Portable Player / MicroSD Mount Path",
      });
      if (selected && typeof selected === "string") {
        targetDir = selected;
      }
    } catch (e) {
      console.warn("Folder dialog fallback:", e);
    }
  }

  async function handleExport() {
    if (!targetDir.trim()) {
      error = "Please specify a target export directory or SD card path.";
      return;
    }
    exporting = true;
    error = null;
    result = null;

    try {
      const res = await api.exportDap(playlistName, targetDir.trim(), format, bitrate || undefined);
      result = res;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      exporting = false;
    }
  }

  async function openExportFolder() {
    if (!result?.export_dir) return;
    try {
      await openPath(result.export_dir);
    } catch (e) {
      console.error("Failed to open path:", e);
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Escape" && !exporting) {
      onclose();
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<div
  class="fixed inset-0 z-50 flex items-center justify-center p-4"
  style="background:rgba(0,0,0,0.75);backdrop-filter:blur(6px);"
  role="dialog"
  aria-modal="true"
  aria-labelledby="dap-export-title"
>
  <div
    class="w-full max-w-lg rounded-2xl border shadow-2xl overflow-hidden flex flex-col"
    style="background:#131118;border-color:var(--border);color:var(--text-primary);box-shadow:0 20px 50px rgba(0,0,0,0.8);"
  >
    <!-- Modal Header -->
    <div style="padding:18px 22px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;">
      <div>
        <div style="font-size:10px;color:var(--accent);text-transform:uppercase;letter-spacing:.12em;font-weight:700;">
          Portable Audio Workstation
        </div>
        <h2 id="dap-export-title" style="font-size:18px;font-weight:700;margin:2px 0 0;color:var(--text-primary);">
          Export to DAP / MicroSD
        </h2>
      </div>
      <button
        onclick={onclose}
        disabled={exporting}
        style="margin-left:auto;width:30px;height:30px;border-radius:8px;background:rgba(255,255,255,0.05);border:1px solid var(--border);color:var(--text-secondary);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:14px;transition:all .15s;"
        aria-label="Close export modal"
      >
        ✕
      </button>
    </div>

    <!-- Modal Body -->
    <div style="padding:22px;display:flex;flex-direction:column;gap:18px;max-height:75vh;overflow-y:auto;">
      <!-- Playlist Summary Card -->
      <div style="padding:12px 14px;border-radius:10px;background:var(--surface);border:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;">
        <div>
          <div style="font-size:14px;font-weight:600;color:var(--text-primary);">{playlistName}</div>
          <div style="font-size:12px;color:var(--text-muted);">{trackCount} tracks queued for transcode</div>
        </div>
        <span style="font-size:11px;padding:3px 8px;border-radius:6px;background:rgba(196,181,253,0.1);color:var(--accent-2);border:1px solid rgba(196,181,253,0.2);font-weight:600;">
          DAP Profile
        </span>
      </div>

      {#if result}
        <!-- Success State -->
        <div style="padding:16px;border-radius:12px;background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.25);display:flex;flex-direction:column;gap:12px;">
          <div style="display:flex;align-items:center;gap:10px;">
            <div style="width:24px;height:24px;border-radius:50%;background:#22c55e;color:black;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:14px;">
              ✓
            </div>
            <div>
              <div style="font-weight:700;font-size:14px;color:#4ade80;">Export Completed Successfully</div>
              <div style="font-size:12px;color:var(--text-secondary);">Transcoded and generated portable M3U structure</div>
            </div>
          </div>

          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;text-align:center;">
            <div style="padding:8px;border-radius:8px;background:rgba(0,0,0,0.3);">
              <div style="font-size:18px;font-weight:700;color:var(--text-primary);">{result.exported_count}</div>
              <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;">Transcoded</div>
            </div>
            <div style="padding:8px;border-radius:8px;background:rgba(0,0,0,0.3);">
              <div style="font-size:18px;font-weight:700;color:var(--text-primary);">{result.skipped_count}</div>
              <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;">Skipped</div>
            </div>
            <div style="padding:8px;border-radius:8px;background:rgba(0,0,0,0.3);">
              <div style="font-size:18px;font-weight:700;color:{result.error_count > 0 ? '#f87171' : 'var(--text-primary)'};">{result.error_count}</div>
              <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;">Errors</div>
            </div>
          </div>

          <div style="font-size:11px;color:var(--text-muted);word-break:break-all;font-family:monospace;background:rgba(0,0,0,0.25);padding:8px 10px;border-radius:6px;">
            <div>Export Folder: {result.export_dir}</div>
            <div>Playlist: {result.playlist_file}</div>
          </div>

          <div style="display:flex;gap:8px;margin-top:4px;">
            <button
              onclick={openExportFolder}
              style="flex:1;padding:8px 12px;border-radius:8px;background:rgba(255,255,255,0.08);border:1px solid var(--border);color:white;font-size:12px;font-weight:600;cursor:pointer;"
            >
              Open Destination Folder
            </button>
            <button
              onclick={onclose}
              style="flex:1;padding:8px 12px;border-radius:8px;background:var(--accent);border:none;color:black;font-size:12px;font-weight:700;cursor:pointer;"
            >
              Done
            </button>
          </div>
        </div>
      {:else}
        <!-- Form State -->
        <!-- Destination Directory -->
        <div>
          <label for="target-dir-input" style="display:block;font-size:12px;font-weight:600;margin-bottom:6px;color:var(--text-secondary);">
            Destination Root / Mount Path (e.g., SD Card or DAP drive)
          </label>
          <div style="display:flex;gap:6px;">
            <input
              id="target-dir-input"
              type="text"
              bind:value={targetDir}
              placeholder="/run/media/username/DAP_SD or /media/music"
              disabled={exporting}
              style="flex:1;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:8px 12px;font-size:13px;color:white;outline:none;"
            />
            <button
              type="button"
              onclick={browseFolder}
              disabled={exporting}
              style="padding:8px 14px;border-radius:8px;background:rgba(255,255,255,0.08);border:1px solid var(--border);color:var(--text-primary);font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap;"
            >
              Browse…
            </button>
          </div>
          <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">
            A subfolder named <span style="color:var(--accent-2);">{playlistName}</span> and relative .m3u files will be created inside this folder.
          </div>
        </div>

        <!-- Format Selector -->
        <div>
          <span style="display:block;font-size:12px;font-weight:600;margin-bottom:8px;color:var(--text-secondary);">
            Audio Transcode Codec
          </span>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
            <button
              type="button"
              onclick={() => onFormatChange("opus")}
              disabled={exporting}
              style="padding:12px;border-radius:10px;text-align:left;border:1px solid {format === 'opus' ? 'var(--accent)' : 'var(--border)'};background:{format === 'opus' ? 'rgba(252,211,77,0.08)' : 'var(--surface)'};cursor:pointer;"
            >
              <div style="display:flex;align-items:center;justify-content:space-between;">
                <span style="font-size:13px;font-weight:700;color:{format === 'opus' ? 'var(--accent)' : 'var(--text-primary)'};">
                  Opus (.opus)
                </span>
                {#if format === 'opus'}
                  <span style="font-size:12px;color:var(--accent);">●</span>
                {/if}
              </div>
              <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">
                State of the art quality at lower bitrates. Best for modern DAPs (Hiby, Sony, FiiO).
              </div>
            </button>

            <button
              type="button"
              onclick={() => onFormatChange("aac")}
              disabled={exporting}
              style="padding:12px;border-radius:10px;text-align:left;border:1px solid {format === 'aac' ? 'var(--accent)' : 'var(--border)'};background:{format === 'aac' ? 'rgba(252,211,77,0.08)' : 'var(--surface)'};cursor:pointer;"
            >
              <div style="display:flex;align-items:center;justify-content:space-between;">
                <span style="font-size:13px;font-weight:700;color:{format === 'aac' ? 'var(--accent)' : 'var(--text-primary)'};">
                  AAC (.m4a)
                </span>
                {#if format === 'aac'}
                  <span style="font-size:12px;color:var(--accent);">●</span>
                {/if}
              </div>
              <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">
                Maximum compatibility with Apple devices, legacy car stereos, and standard players.
              </div>
            </button>
          </div>
        </div>

        <!-- Bitrate Selector -->
        <div>
          <label for="bitrate-select" style="display:block;font-size:12px;font-weight:600;margin-bottom:6px;color:var(--text-secondary);">
            Target Bitrate
          </label>
          <select
            id="bitrate-select"
            bind:value={bitrate}
            disabled={exporting}
            style="width:100%;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:8px 12px;font-size:13px;color:white;outline:none;"
          >
            {#if format === "opus"}
              <option value="96k">96 kbps (Compact)</option>
              <option value="128k">128 kbps (Standard)</option>
              <option value="160k">160 kbps (Recommended / Transparent)</option>
              <option value="192k">192 kbps (High Fidelity)</option>
              <option value="256k">256 kbps (Ultra)</option>
              <option value="320k">320 kbps (Maximum)</option>
            {:else}
              <option value="128k">128 kbps (Standard)</option>
              <option value="192k">192 kbps (High Quality)</option>
              <option value="256k">256 kbps (Recommended / iTunes Plus)</option>
              <option value="320k">320 kbps (Maximum)</option>
            {/if}
          </select>
        </div>

        <!-- Features Info -->
        <div style="padding:10px 12px;border-radius:8px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);font-size:11px;color:var(--text-secondary);display:flex;flex-direction:column;gap:4px;">
          <div>✓ Copies time-synchronized <span style="color:var(--accent-2);font-family:monospace;">.lrc</span> sidecars automatically.</div>
          <div>✓ Preserves artist, album, title, and track number metadata tags.</div>
          <div>✓ Builds root-relative and playlist-relative <span style="color:var(--accent-2);font-family:monospace;">.m3u</span> playlists.</div>
        </div>

        {#if error}
          <div style="padding:10px 12px;border-radius:8px;background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.3);color:#f87171;font-size:12px;">
            {error}
          </div>
        {/if}

        <!-- Actions -->
        <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:6px;">
          <button
            type="button"
            onclick={onclose}
            disabled={exporting}
            style="padding:8px 16px;border-radius:8px;background:transparent;border:1px solid var(--border);color:var(--text-secondary);font-size:12px;font-weight:600;cursor:pointer;"
          >
            Cancel
          </button>
          <button
            type="button"
            onclick={handleExport}
            disabled={exporting || !targetDir.trim()}
            style="padding:8px 20px;border-radius:8px;background:var(--accent);border:none;color:black;font-size:12px;font-weight:700;cursor:pointer;opacity:{exporting || !targetDir.trim() ? '.5' : '1'};display:flex;align-items:center;gap:8px;"
          >
            {#if exporting}
              <span style="width:14px;height:14px;border:2px solid black;border-top-color:transparent;border-radius:50%;animation:spin 1s linear infinite;"></span>
              Transcoding & Exporting…
            {:else}
              Start DAP Export
            {/if}
          </button>
        </div>
      {/if}
    </div>
  </div>
</div>

<style>
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
</style>
