<script lang="ts">
  import { onMount } from "svelte";
  import { api, type TrackLyrics } from "../api";
  import { player } from "./player.svelte";

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
  let viewMode = $state<"karaoke" | "synced" | "plain">("karaoke");
  let filterQuery = $state("");
  let copied = $state(false);
  let copyTimer: ReturnType<typeof setTimeout> | null = null;
  let activeLineElement = $state<HTMLElement | null>(null);

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
      } else {
        viewMode = "karaoke";
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

  // Calculate active line index based on player current time (in ms)
  let activeLineIndex = $derived(() => {
    if (!lyricsData?.lines || !lyricsData.synced) return -1;
    const currentMs = (player.currentTime || 0) * 1000;
    const lines = lyricsData.lines;
    let activeIdx = -1;
    for (let i = 0; i < lines.length; i++) {
      const lineTime = lines[i].time_ms;
      if (lineTime !== undefined && currentMs >= lineTime) {
        activeIdx = i;
      } else if (lineTime !== undefined && currentMs < lineTime) {
        break;
      }
    }
    return activeIdx;
  });

  // Auto-scroll to active line in Karaoke mode
  $effect(() => {
    const idx = activeLineIndex();
    if (viewMode === "karaoke" && idx >= 0) {
      const el = document.getElementById(`karaoke-line-${idx}`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
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
              onclick={() => (viewMode = "karaoke")}
              style="padding:4px 10px;border-radius:6px;font-size:11px;font-weight:600;border:none;cursor:pointer;transition:all .15s;
                {viewMode === 'karaoke' ? 'background:var(--accent);color:black;' : 'background:transparent;color:var(--text-muted);'}"
            >
              🎤 Karaoke
            </button>
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
        <div class="flex flex-col items-center justify-center h-60 gap-3 text-zinc-400">
          <span class="w-6 h-6 border-2 border-zinc-700 border-t-amber-400 rounded-full animate-spin"></span>
          <span class="text-xs">Reading synchronized lyrics…</span>
        </div>
      {:else if error}
        <div class="p-5 rounded-xl bg-red-950/20 border border-red-800/40 text-red-400 text-xs text-center">
          {error}
        </div>
      {:else if !lyricsData?.lyrics}
        <div class="flex flex-col items-center justify-center h-64 text-center text-zinc-400 gap-2">
          <span class="text-3xl">🎤</span>
          <div class="text-sm font-semibold text-zinc-200">No Lyrics Available</div>
          <div class="text-xs max-w-xs text-zinc-400">
            This track does not have an associated <span class="font-mono text-amber-400">.lrc</span> sidecar or embedded tags in the library archive.
          </div>
        </div>
      {:else if viewMode === "karaoke" && lyricsData.synced}
        <!-- Real-Time Karaoke Synchronized View -->
        <div class="flex flex-col gap-4 max-w-lg my-10 mx-auto text-center" role="list">
          {#each lyricsData.lines as line, idx}
            {@const isActive = idx === activeLineIndex()}
            {@const isPast = idx < activeLineIndex()}
            <div
              id={`karaoke-line-${idx}`}
              class="p-2.5 rounded-xl transition-all duration-200 ease-out {isActive ? 'text-amber-300 text-xl font-bold scale-105 drop-shadow-[0_0_20px_rgba(251,191,36,0.5)]' : isPast ? 'text-zinc-500 text-sm opacity-50' : 'text-zinc-300 text-sm opacity-80'}"
              role="listitem"
            >
              <div class="leading-relaxed">
                {line.text}
              </div>
            </div>
          {/each}
        </div>
      {:else if viewMode === "synced" && lyricsData.synced}
        <!-- Synced Table View -->
        <div class="flex flex-col gap-1.5 max-w-lg mx-auto" role="list">
          {#each filteredLines() as line, idx}
            <div class="flex items-baseline gap-3.5 px-2.5 py-1.5 rounded-lg hover:bg-white/[0.04] transition-colors" role="listitem">
              {#if line.timestamp}
                <span class="font-mono text-[11px] text-amber-400/90 tabular-nums min-w-[54px] flex-shrink-0">
                  {line.timestamp}
                </span>
              {:else}
                <span class="min-w-[54px] flex-shrink-0"></span>
              {/if}
              <span class="text-sm font-medium text-zinc-100 leading-snug">
                {line.text}
              </span>
            </div>
          {/each}
        </div>
      {:else}
        <!-- Plain Text / Raw View -->
        <div class="max-w-lg mx-auto">
          <pre class="font-sans text-sm leading-relaxed text-zinc-200 whitespace-pre-wrap m-0">{lyricsData.lyrics}</pre>
        </div>
      {/if}
    </div>
  </div>
</div>
