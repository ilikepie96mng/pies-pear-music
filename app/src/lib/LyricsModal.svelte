<script lang="ts">
  import { onMount } from "svelte";
  import { api, type TrackLyrics } from "../api";

  interface TrackInfo {
    track_id: string;
    title: string;
    artist: string;
    album: string;
    local_path?: string;
    artwork_url?: string | null;
  }

  interface Props {
    track: TrackInfo;
    onclose: () => void;
  }

  let { track, onclose }: Props = $props();

  let loading = $state(true);
  let error = $state<string | null>(null);
  let lyricsData = $state<TrackLyrics | null>(null);
  let viewMode = $state<"synced" | "plain">("synced");
  let filterQuery = $state("");
  let copied = $state(false);
  let copyTimer: ReturnType<typeof setTimeout> | null = null;

  function thumbUrl(url: string | null | undefined, size: string): string {
    if (!url) return "";
    return url.replace("{w}x{h}", size);
  }

  async function loadLyrics() {
    loading = true;
    error = null;
    try {
      lyricsData = await api.getTrackLyrics(track.track_id);
      if (!lyricsData.synced) {
        viewMode = "plain";
      }
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    loadLyrics();
  });

  async function copyLyrics() {
    if (!lyricsData?.lyrics) return;
    try {
      await navigator.clipboard.writeText(lyricsData.lyrics);
      copied = true;
      if (copyTimer) clearTimeout(copyTimer);
      copyTimer = setTimeout(() => {
        copied = false;
      }, 2500);
    } catch (e) {
      console.warn("Clipboard write failed:", e);
    }
  }

  let filteredLines = $derived(() => {
    if (!lyricsData?.lines) return [];
    if (!filterQuery.trim()) return lyricsData.lines;
    const q = filterQuery.toLowerCase();
    return lyricsData.lines.filter(l => l.text.toLowerCase().includes(q));
  });

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Escape") {
      onclose();
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<div
  class="fixed inset-0 z-50 flex items-center justify-center p-4"
  style="background:rgba(0,0,0,0.8);backdrop-filter:blur(8px);"
  role="dialog"
  aria-modal="true"
  aria-labelledby="lyrics-modal-title"
>
  <div
    class="w-full max-w-2xl h-[85vh] max-h-[750px] rounded-2xl border shadow-2xl overflow-hidden flex flex-col"
    style="background:#121016;border-color:var(--border);color:var(--text-primary);box-shadow:0 24px 60px rgba(0,0,0,0.85);"
  >
    <!-- Modal Header -->
    <div style="padding:16px 20px;border-bottom:1px solid var(--border);background:#181520;display:flex;align-items:center;gap:14px;flex-shrink:0;">
      {#if track.artwork_url}
        <img
          src={thumbUrl(track.artwork_url, "96x96")}
          alt=""
          style="width:48px;height:48px;border-radius:8px;object-fit:cover;flex-shrink:0;box-shadow:0 4px 12px rgba(0,0,0,0.5);"
          onerror={e => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
        />
      {:else}
        <div style="width:48px;height:48px;border-radius:8px;background:#252030;display:flex;align-items:center;justify-content:center;font-size:20px;color:var(--text-muted);flex-shrink:0;">
          ♫
        </div>
      {/if}

      <div style="flex:1;min-width:0;">
        <div style="display:flex;align-items:center;gap:8px;">
          <h2 id="lyrics-modal-title" style="font-size:16px;font-weight:700;margin:0;color:var(--text-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
            {track.title}
          </h2>
          {#if lyricsData}
            {#if lyricsData.synced}
              <span style="font-size:10px;padding:2px 6px;border-radius:4px;background:rgba(252,211,77,0.15);color:var(--accent);border:1px solid rgba(252,211,77,0.3);font-weight:700;text-transform:uppercase;letter-spacing:.05em;flex-shrink:0;">
                Synced LRC
              </span>
            {:else if lyricsData.lyrics}
              <span style="font-size:10px;padding:2px 6px;border-radius:4px;background:rgba(255,255,255,0.08);color:var(--text-secondary);border:1px solid var(--border);font-weight:600;flex-shrink:0;">
                Plain Text
              </span>
            {/if}
          {/if}
        </div>
        <div style="font-size:12px;color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px;">
          {track.artist} <span style="color:var(--text-muted);">—</span> {track.album}
        </div>
      </div>

      <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">
        {#if lyricsData?.lyrics}
          <button
            onclick={copyLyrics}
            style="padding:6px 12px;border-radius:6px;font-size:11px;font-weight:600;background:rgba(255,255,255,0.06);border:1px solid var(--border);color:var(--text-secondary);cursor:pointer;display:flex;align-items:center;gap:6px;transition:all .15s;"
            title="Copy lyrics to clipboard"
          >
            {#if copied}
              <span style="color:#4ade80;">✓ Copied</span>
            {:else}
              <span>⧉ Copy</span>
            {/if}
          </button>
        {/if}
        <button
          onclick={onclose}
          style="width:30px;height:30px;border-radius:8px;background:rgba(255,255,255,0.05);border:1px solid var(--border);color:var(--text-secondary);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:14px;"
          aria-label="Close lyrics modal"
        >
          ✕
        </button>
      </div>
    </div>

    <!-- Toolbar / Search / View toggles -->
    {#if lyricsData?.lyrics}
      <div style="padding:10px 20px;border-bottom:1px solid var(--border);background:#15121b;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-shrink:0;">
        <div style="display:flex;align-items:center;gap:6px;">
          {#if lyricsData.synced}
            <button
              onclick={() => (viewMode = "synced")}
              style="padding:4px 10px;border-radius:6px;font-size:11px;font-weight:600;border:none;cursor:pointer;transition:all .15s;
                {viewMode === 'synced' ? 'background:var(--accent);color:black;' : 'background:transparent;color:var(--text-muted);'}"
            >
              Timed Lines
            </button>
          {/if}
          <button
            onclick={() => (viewMode = "plain")}
            style="padding:4px 10px;border-radius:6px;font-size:11px;font-weight:600;border:none;cursor:pointer;transition:all .15s;
              {viewMode === 'plain' ? 'background:var(--accent);color:black;' : 'background:transparent;color:var(--text-muted);'}"
          >
            Full Text
          </button>
        </div>

        {#if viewMode === "synced"}
          <div style="display:flex;align-items:center;gap:6px;">
            <input
              type="text"
              bind:value={filterQuery}
              placeholder="Filter lyrics…"
              style="background:rgba(0,0,0,0.3);border:1px solid var(--border);border-radius:6px;padding:4px 8px;font-size:11px;color:white;width:150px;outline:none;"
            />
            {#if filterQuery}
              <button
                onclick={() => (filterQuery = "")}
                style="font-size:10px;color:var(--text-muted);background:transparent;border:none;cursor:pointer;"
              >
                Clear
              </button>
            {/if}
          </div>
        {/if}

        <div style="font-size:11px;color:var(--text-muted);">
          Source: <span style="color:var(--accent-2);text-transform:capitalize;">{lyricsData.source}</span>
        </div>
      </div>
    {/if}

    <!-- Content Area -->
    <div style="flex:1;overflow-y:auto;padding:24px 28px;">
      {#if loading}
        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:240px;gap:12px;color:var(--text-muted);">
          <span style="width:24px;height:24px;border:2px solid #333;border-top-color:var(--accent);border-radius:50%;animation:spin 1s linear infinite;"></span>
          <span style="font-size:13px;">Reading synchronized lyrics…</span>
        </div>
      {:else if error}
        <div style="padding:20px;border-radius:12px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.25);color:#f87171;font-size:13px;text-align:center;">
          {error}
        </div>
      {:else if !lyricsData?.lyrics}
        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:260px;text-align:center;color:var(--text-muted);gap:8px;">
          <span style="font-size:28px;">🎤</span>
          <div style="font-size:14px;font-weight:600;color:var(--text-secondary);">No Lyrics Available</div>
          <div style="font-size:12px;max-width:320px;">
            This track does not have an associated <span style="font-family:monospace;color:var(--accent);">.lrc</span> sidecar or embedded tags in the library archive.
          </div>
        </div>
      {:else if viewMode === "synced" && lyricsData.synced}
        <!-- Synced View -->
        <div style="display:flex;flex-direction:column;gap:6px;max-width:540px;margin:0 auto;" role="list">
          {#each filteredLines() as line, idx}
            <div class="lyric-line" role="listitem">
              {#if line.timestamp}
                <span class="lyric-time">
                  {line.timestamp}
                </span>
              {:else}
                <span class="lyric-time-empty"></span>
              {/if}
              <span class="lyric-text">
                {line.text}
              </span>
            </div>
          {/each}
        </div>
      {:else}
        <!-- Plain Text / Raw View -->
        <div style="max-width:540px;margin:0 auto;">
          <pre style="font-family:inherit;font-size:14px;line-height:1.8;color:var(--text-primary);white-space:pre-wrap;margin:0;">{lyricsData.lyrics}</pre>
        </div>
      {/if}
    </div>
  </div>
</div>

<style>
  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  .lyric-line {
    display: flex;
    align-items: baseline;
    gap: 14px;
    padding: 6px 10px;
    border-radius: 8px;
    transition: background 0.15s ease;
  }

  .lyric-line:hover {
    background: rgba(255, 255, 255, 0.04);
  }

  .lyric-time {
    font-family: monospace;
    font-size: 11px;
    color: var(--accent);
    font-variant-numeric: tabular-nums;
    opacity: 0.8;
    min-width: 54px;
    flex-shrink: 0;
  }

  .lyric-time-empty {
    min-width: 54px;
    flex-shrink: 0;
  }

  .lyric-text {
    font-size: 15px;
    line-height: 1.5;
    color: var(--text-primary);
    font-weight: 500;
  }
</style>
