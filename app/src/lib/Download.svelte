<script lang="ts">
  import { onDestroy, onMount, tick } from "svelte";
  import {
    api,
    streamEvents,
    type SyncEvent,
    type CatalogSearchResult,
    type CatalogAlbum,
    type CatalogArtist,
    type CatalogSong,
    type CatalogTrack,
    type QueueSummary,
    type QueueJob,
  } from "../api";
  import {
    notifyDownloadStarted,
    notifyDownloadCompleted,
    notifyDownloadFailed,
  } from "./notifications";

  // Navigation & Subviews
  type MainTab = "search" | "progress" | "direct" | "queue";
  type SearchSubView = "results" | "artist" | "album";

  let mainTab = $state<MainTab>("search");
  let searchSubView = $state<SearchSubView>("results");

  // Search & Catalog State
  let searchQuery = $state("");
  let searchDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  let searchLoading = $state(false);
  let searchError = $state<string | null>(null);
  let searchResults = $state<CatalogSearchResult>({ songs: [], albums: [], artists: [] });
  let activeEntityFilter = $state<"all" | "albums" | "artists" | "songs">("all");

  // Global download format
  let format = $state("ALAC");

  // Artist Discography View State
  let selectedArtist = $state<CatalogArtist | null>(null);
  let artistLoading = $state(false);
  let artistError = $state<string | null>(null);
  let artistFilter = $state<"all" | "albums" | "singles">("all");
  let selectedAlbumIds = $state<Set<string>>(new Set());

  // Album Tracklist View State
  let selectedAlbum = $state<CatalogAlbum | null>(null);
  let albumLoading = $state(false);
  let albumError = $state<string | null>(null);

  // Direct URL input state
  let directUrl = $state("");

  // Download Session & Live Streaming Progress State
  type DownloadStatus = "idle" | "queued" | "running" | "done" | "error";
  type DownloadPhase = "preflight" | "downloading" | "organizing" | "done";

  interface DownloadItem {
    id: string;
    title: string;
    artist?: string;
    url: string;
    status: "queued" | "running" | "done" | "error";
    new?: number;
    skipped?: number;
    errors?: number;
    errorMessage?: string;
  }

  interface DownloadSession {
    type: "single" | "album" | "batch" | "direct";
    title: string;
    subtitle: string;
    artworkUrl?: string | null;
    items: DownloadItem[];
    format: string;
  }

  type LogLine = {
    id: number;
    text: string;
    kind: "info" | "add" | "skip" | "err" | "done";
  };

  const MAX_RENDERED_LOGS = 800;
  const LOG_FLUSH_MS = 60;

  let activeSession = $state<DownloadSession | null>(null);
  let currentItemIndex = $state(0);
  let sessionStatus = $state<DownloadStatus>("idle");
  let sessionPhase = $state<DownloadPhase>("preflight");
  let sessionQueuePos = $state(0);
  let logPath = $state<string | null>(null);
  let copiedLog = $state(false);
  let copiedLogPath = $state(false);
  let autoFollow = $state(true);
  let latestMessage = $state("Waiting for output…");

  // Live Metrics for session
  let liveNew = $state(0);
  let liveSkipped = $state(0);
  let liveErrors = $state(0);
  let progressCurrent = $state(0);
  let progressTotal = $state(0);
  let totalLogCount = $state(0);

  let logs = $state<LogLine[]>([]);
  let pendingLogs: LogLine[] = [];
  let flushTimer: ReturnType<typeof setTimeout> | null = null;
  let nextLogId = 0;
  let allLogText = "";
  let logEl = $state<HTMLElement | null>(null);
  let streamAbort: AbortController | null = null;
  let sessionErrorMessage = $state<string | null>(null);

  // Phase Timeline Definition
  const PHASES: { key: DownloadPhase; label: string }[] = [
    { key: "preflight",   label: "Checking" },
    { key: "downloading", label: "Downloading" },
    { key: "organizing",  label: "Organizing" },
    { key: "done",        label: "Complete" },
  ];

  const PHASE_ORDER: Record<DownloadPhase, number> = {
    preflight: 0,
    downloading: 1,
    organizing: 2,
    done: 3,
  };

  let phaseIndex = $derived(PHASE_ORDER[sessionPhase] ?? 0);

  let currentItem = $derived(
    activeSession && activeSession.items[currentItemIndex] ? activeSession.items[currentItemIndex] : null
  );

  let progressPct = $derived(() => {
    if (!activeSession) return 0;
    if (activeSession.items.length > 1) {
      // Multi-album batch: overall batch completion percentage
      const completedItems = activeSession.items.filter((i) => i.status === "done" || i.status === "error").length;
      if (progressTotal > 0 && currentItem?.status === "running") {
        const itemFraction = progressCurrent / Math.max(1, progressTotal);
        return Math.round(((completedItems + itemFraction) / activeSession.items.length) * 100);
      }
      return Math.round((completedItems / activeSession.items.length) * 100);
    }
    if (progressTotal > 0) {
      return Math.round((progressCurrent / progressTotal) * 100);
    }
    return sessionStatus === "done" ? 100 : 0;
  });

  function formatArtwork(url: string | null | undefined, size: number = 300): string {
    if (!url) return "";
    return url.replace("{w}", String(size)).replace("{h}", String(size));
  }

  function formatDuration(ms: number): string {
    if (!ms || ms <= 0) return "--:--";
    const totalSecs = Math.floor(ms / 1000);
    const mins = Math.floor(totalSecs / 60);
    const secs = totalSecs % 60;
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  }

  function classifyLine(text: string): LogLine["kind"] {
    if (text.includes("added:")) return "add";
    if (text.toLowerCase().includes("skipping") || text.includes("skipped")) return "skip";
    if (text.includes("error") || text.startsWith("[!")) return "err";
    if (text.startsWith("Sync complete") || text.startsWith("Download complete")) return "done";
    return "info";
  }

  function parseProgress(text: string) {
    const m = text.match(/\[(\d+)\/(\d+)\]\s*songs?/i) || text.match(/Track\s+(\d+)\s+of\s+(\d+)/i) || text.match(/^\[(\d+)\/(\d+)\]/);
    if (m) {
      progressCurrent = parseInt(m[1]);
      progressTotal = parseInt(m[2]);
    }
  }

  function classifyError(msg: string): { headline: string; detail: string } {
    const m = msg.toLowerCase();
    if (m.includes("no audio files") || m.includes("no .m4a files")) {
      return { headline: "No audio files found", detail: "Could not find matching lossless tracks for this target." };
    }
    if (m.includes("timed out") || m.includes("timeout")) {
      return { headline: "Connection timed out", detail: "Apple Music or CDN server timed out. Check your connection and retry." };
    }
    if (m.includes("not logged in") || m.includes("401")) {
      return { headline: "Apple Music session expired", detail: "Please verify your Apple Music login status in the sidebar." };
    }
    return { headline: "Download failed", detail: msg };
  }

  async function scrollToBottom() {
    await tick();
    if (logEl && autoFollow) logEl.scrollTop = logEl.scrollHeight;
  }

  async function flushPendingLogs() {
    if (flushTimer !== null) {
      clearTimeout(flushTimer);
      flushTimer = null;
    }
    if (pendingLogs.length === 0) return;
    logs = [...logs, ...pendingLogs].slice(-MAX_RENDERED_LOGS);
    pendingLogs = [];
    await scrollToBottom();
  }

  function scheduleLogFlush() {
    if (flushTimer !== null) return;
    flushTimer = setTimeout(() => {
      flushTimer = null;
      void flushPendingLogs();
    }, LOG_FLUSH_MS);
  }

  function appendLog(text: string, kind: LogLine["kind"]) {
    pendingLogs.push({ id: nextLogId++, text, kind });
    if (pendingLogs.length > MAX_RENDERED_LOGS) {
      pendingLogs = pendingLogs.slice(-MAX_RENDERED_LOGS);
    }
    totalLogCount += 1;
    scheduleLogFlush();
  }

  function handleLogScroll() {
    if (!logEl) return;
    const distanceFromBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight;
    autoFollow = distanceFromBottom < 24;
  }

  async function copyLog() {
    const text = logs.map((l) => l.text).join("\n");
    await navigator.clipboard.writeText(text);
    copiedLog = true;
    setTimeout(() => (copiedLog = false), 2000);
  }

  async function copyLogPath() {
    if (!logPath) return;
    await navigator.clipboard.writeText(logPath);
    copiedLogPath = true;
    setTimeout(() => (copiedLogPath = false), 2000);
  }

  // Live Catalog Search
  function handleSearchInput(e: Event) {
    const val = (e.target as HTMLInputElement).value;
    searchQuery = val;
    if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
    if (!val.trim()) {
      searchResults = { songs: [], albums: [], artists: [] };
      searchLoading = false;
      searchError = null;
      return;
    }
    searchLoading = true;
    searchError = null;
    searchDebounceTimer = setTimeout(async () => {
      try {
        const res = await api.searchCatalog(val.trim(), ["songs", "albums", "artists"], 12);
        searchResults = res;
      } catch (err) {
        searchError = err instanceof Error ? err.message : String(err);
      } finally {
        searchLoading = false;
      }
    }, 350);
  }

  // Open Artist Discography
  async function openArtist(artistIdOrUrl: string) {
    artistLoading = true;
    artistError = null;
    selectedAlbumIds = new Set();
    searchSubView = "artist";
    try {
      selectedArtist = await api.catalogArtist(artistIdOrUrl);
    } catch (err) {
      artistError = err instanceof Error ? err.message : String(err);
    } finally {
      artistLoading = false;
    }
  }

  // Open Album Inspector
  async function openAlbum(albumIdOrUrl: string) {
    albumLoading = true;
    albumError = null;
    searchSubView = "album";
    try {
      selectedAlbum = await api.catalogAlbum(albumIdOrUrl);
    } catch (err) {
      albumError = err instanceof Error ? err.message : String(err);
    } finally {
      albumLoading = false;
    }
  }

  // Filtered Discography Albums
  let filteredArtistAlbums = $derived(() => {
    if (!selectedArtist || !selectedArtist.albums) return [];
    if (artistFilter === "albums") {
      return selectedArtist.albums.filter((a) => !a.is_single);
    }
    if (artistFilter === "singles") {
      return selectedArtist.albums.filter((a) => a.is_single);
    }
    return selectedArtist.albums;
  });

  function toggleAlbumSelection(albumId: string) {
    const next = new Set(selectedAlbumIds);
    if (next.has(albumId)) {
      next.delete(albumId);
    } else {
      next.add(albumId);
    }
    selectedAlbumIds = next;
  }

  function selectAllAlbums() {
    const current = filteredArtistAlbums();
    selectedAlbumIds = new Set(current.map((a) => a.id));
  }

  function selectStudioAlbumsOnly() {
    if (!selectedArtist?.albums) return;
    const studio = selectedArtist.albums.filter((a) => !a.is_single && !a.is_compilation);
    selectedAlbumIds = new Set(studio.map((a) => a.id));
  }

  function deselectAllAlbums() {
    selectedAlbumIds = new Set();
  }

  let selectedAlbumsTrackCount = $derived(() => {
    if (!selectedArtist?.albums) return 0;
    return selectedArtist.albums
      .filter((a) => selectedAlbumIds.has(a.id))
      .reduce((sum, a) => sum + (a.track_count || 0), 0);
  });

  // =========================================================================
  // DOWNLOAD STREAM RUNNER (Single Track, Album, Artist Batch, Direct URL)
  // =========================================================================

  function startStreamSession(session: DownloadSession) {
    if (streamAbort) {
      streamAbort.abort();
      streamAbort = null;
    }

    activeSession = session;
    currentItemIndex = 0;
    sessionStatus = "queued";
    sessionPhase = "preflight";
    sessionQueuePos = 0;
    logPath = null;
    latestMessage = `Preparing lossless download for "${session.title}"…`;
    sessionErrorMessage = null;
    liveNew = 0;
    liveSkipped = 0;
    liveErrors = 0;
    progressCurrent = 0;
    progressTotal = 0;
    totalLogCount = 0;
    logs = [];
    pendingLogs = [];
    allLogText = "";
    autoFollow = true;

    // Switch view to dedicated live progress monitor page
    mainTab = "progress";

    void notifyDownloadStarted(session.title);
    void runCurrentItem();
  }

  async function runCurrentItem() {
    if (!activeSession || currentItemIndex >= activeSession.items.length) {
      // Entire session complete!
      sessionStatus = "done";
      sessionPhase = "done";
      await flushPendingLogs();
      void notifyDownloadCompleted(activeSession?.title || "Download", liveNew, liveSkipped);
      refreshQueue();
      return;
    }

    const item = activeSession.items[currentItemIndex];
    item.status = "running";
    sessionStatus = "running";
    sessionPhase = "downloading";
    progressCurrent = 0;
    progressTotal = 0;

    appendLog(`━━━ [${currentItemIndex + 1}/${activeSession.items.length}] Starting: ${item.title} (${activeSession.format}) ━━━`, "info");

    streamAbort = new AbortController();
    const downloadUrl = `/download/one-off?url=${encodeURIComponent(item.url)}&format=${encodeURIComponent(activeSession.format)}`;

    try {
      await streamEvents(
        downloadUrl,
        async (data: SyncEvent) => {
          if (data.log_path) logPath = data.log_path;

          if (data.status === "queued") {
            sessionStatus = "queued";
            sessionQueuePos = (data as any).position ?? 0;
            return;
          }

          if (data.status === "running") {
            sessionStatus = "running";
            if (data.phase) {
              if (data.phase === "organizing") sessionPhase = "organizing";
              else sessionPhase = "downloading";
            }
            if (data.message) {
              latestMessage = data.message;
              const kind = classifyLine(data.message);
              appendLog(data.message, kind);
              parseProgress(data.message);
              if (kind === "add") liveNew++;
              else if (kind === "skip") liveSkipped++;
              else if (kind === "err") liveErrors++;
            }
          } else if (data.status === "done") {
            await flushPendingLogs();
            item.status = "done";
            item.new = data.new ?? 0;
            item.skipped = data.skipped ?? 0;
            item.errors = data.errors ?? 0;
            appendLog(`✓ Finished: ${item.title} (${data.new ?? 0} new, ${data.skipped ?? 0} skipped, ${data.errors ?? 0} errors)`, "done");

            // Advance to next item in batch
            currentItemIndex++;
            void runCurrentItem();
          } else if (data.status === "error") {
            await flushPendingLogs();
            item.status = "error";
            item.errorMessage = data.message ?? "Failed to download item";
            appendLog(`✗ Error downloading ${item.title}: ${item.errorMessage}`, "err");

            // If it's a multi-item batch, proceed to next item; else fail session
            if (activeSession && activeSession.items.length > 1 && currentItemIndex < activeSession.items.length - 1) {
              currentItemIndex++;
              void runCurrentItem();
            } else {
              sessionStatus = "error";
              sessionErrorMessage = item.errorMessage;
              void notifyDownloadFailed(activeSession?.title || item.title, sessionErrorMessage);
            }
          }
        },
        streamAbort.signal
      );
    } catch (err: any) {
      if (err.name !== "AbortError" && (sessionStatus === "running" || sessionStatus === "queued")) {
        await flushPendingLogs();
        sessionStatus = "error";
        sessionErrorMessage = "Lost connection to backend download server.";
        item.status = "error";
        item.errorMessage = sessionErrorMessage;
        void notifyDownloadFailed(activeSession?.title || item.title, sessionErrorMessage);
      }
    }
  }

  function abortCurrentSession() {
    if (streamAbort) {
      streamAbort.abort();
      streamAbort = null;
    }
    sessionStatus = "error";
    sessionErrorMessage = "Download stopped by user.";
    appendLog("Download session cancelled by user.", "err");
  }

  // QUEUE MONITOR & DOWNLOAD ACTIONS
  // =========================================================================

  // Queue Monitor State
  let queueSummary = $state<QueueSummary>({
    active: null,
    pending: [],
    completed: [],
    counts: { pending: 0, running: 0, done: 0, error: 0, cancelled: 0, total: 0 }
  });
  let queuePollTimer: ReturnType<typeof setInterval> | null = null;

  // Quick Action: Download Selected Discography Albums
  async function downloadSelectedAlbums() {
    if (!selectedArtist?.albums || selectedAlbumIds.size === 0) return;
    const selected = selectedArtist.albums.filter((a) => selectedAlbumIds.has(a.id));
    const items = selected.map((alb) => ({
      url: alb.url || `https://music.apple.com/us/album/${alb.id}`,
      title: alb.title,
      artist: alb.artist || selectedArtist?.name,
      album: alb.title,
      artwork_url: alb.artwork_url || selectedArtist?.artwork_url,
      total_tracks: alb.track_count || alb.tracks?.length || 0,
      item_type: "album",
    }));

    try {
      await api.queue.add({
        items,
        format,
        batch_title: `${selectedArtist.name} — Discography Batch`,
      });
      selectedAlbumIds = new Set();
      mainTab = "queue";
      await refreshQueue();
    } catch (err: any) {
      console.error("Failed to enqueue discography:", err);
    }
  }

  // Quick Action: Download Current Album
  async function downloadCurrentAlbum() {
    if (!selectedAlbum) return;
    try {
      await api.queue.add({
        items: [{
          url: selectedAlbum.url || `https://music.apple.com/us/album/${selectedAlbum.id}`,
          title: selectedAlbum.title,
          artist: selectedAlbum.artist,
          album: selectedAlbum.title,
          artwork_url: selectedAlbum.artwork_url,
          total_tracks: selectedAlbum.tracks?.length || selectedAlbum.track_count || 0,
          item_type: "album",
        }],
        format,
        batch_title: selectedAlbum.title,
      });
      mainTab = "queue";
      await refreshQueue();
    } catch (err: any) {
      console.error("Failed to enqueue album:", err);
    }
  }

  // Quick Action: Download Single Track
  async function downloadSingleTrack(track: CatalogTrack | CatalogSong) {
    const url = track.url || `https://music.apple.com/us/song/${track.id}`;
    try {
      await api.queue.add({
        items: [{
          url,
          title: track.title,
          artist: track.artist,
          album: track.album || "",
          artwork_url: track.artwork_url,
          total_tracks: 1,
          item_type: "single",
        }],
        format,
        batch_title: track.title,
      });
      mainTab = "queue";
      await refreshQueue();
    } catch (err: any) {
      console.error("Failed to enqueue single track:", err);
    }
  }

  // Quick Action: Start Direct URL Download
  async function startDirectDownload() {
    if (!directUrl.trim()) return;
    const url = directUrl.trim();
    try {
      await api.queue.add({
        urls: [url],
        format,
      });
      directUrl = "";
      mainTab = "queue";
      await refreshQueue();
    } catch (err: any) {
      console.error("Failed to enqueue direct URL:", err);
    }
  }

  async function cancelQueueJob(jobId?: number | string, batchId?: string, cancelAll?: boolean) {
    try {
      await api.queue.cancel({
        jobId: typeof jobId === "number" ? jobId : undefined,
        batchId,
        cancelAll,
      });
      await refreshQueue();
    } catch (err) {
      console.error("Failed to cancel job:", err);
    }
  }

  async function retryFailedQueue() {
    try {
      await api.queue.retry();
      await refreshQueue();
    } catch (err) {
      console.error("Failed to retry queue:", err);
    }
  }

  async function clearCompletedQueue() {
    try {
      await api.queue.clear(0);
      await refreshQueue();
    } catch (err) {
      console.error("Failed to clear queue:", err);
    }
  }

  async function refreshQueue() {
    try {
      queueSummary = await api.queue.get();
    } catch {
      // ignore transient poll error
    }
  }

  onMount(() => {
    refreshQueue();
    queuePollTimer = setInterval(refreshQueue, 2000);
  });

  onDestroy(() => {
    if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
    if (flushTimer !== null) clearTimeout(flushTimer);
    if (queuePollTimer) clearInterval(queuePollTimer);
  });
</script>

<div class="flex flex-col h-full overflow-hidden" style="background:var(--bg);color:var(--text-primary);">
  <!-- Header & Tab Navigation -->
  <div class="px-8 pt-6 pb-4 border-b flex-shrink-0" style="border-color:var(--border);background:rgba(20,18,26,0.5);">
    <div class="flex items-center justify-between gap-4 mb-4">
      <div>
        <div class="text-amber-500 text-[10px] font-bold uppercase tracking-widest mb-1 flex items-center gap-1.5">
          <span>Catalog Explorer & Lossless Downloader</span>
          {#if sessionStatus === "running" || sessionStatus === "queued"}
            <span class="flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] bg-amber-500/20 text-amber-300 border border-amber-500/40 animate-pulse font-semibold">
              <span class="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
              <span>Downloading Lossless</span>
            </span>
          {/if}
        </div>
        <h2 class="text-white text-2xl font-bold tracking-tight">Apple Music Lossless Downloader</h2>
      </div>

      <!-- Format Selector -->
      <div class="flex items-center gap-2 bg-[#12100e] border border-[#2a2a2a] rounded-xl px-3 py-1.5 shadow-sm">
        <span class="text-xs text-zinc-500 font-medium">Format:</span>
        <select
          bind:value={format}
          class="bg-transparent text-xs font-bold text-amber-400 outline-none cursor-pointer"
        >
          <option value="ALAC">ALAC (Lossless / Hi-Res)</option>
          <option value="AAC">AAC (256kbps)</option>
          <option value="ATMOS">Dolby Atmos (Spatial)</option>
        </select>
      </div>
    </div>

    <!-- Main Navigation Tabs -->
    <div class="flex items-center gap-2">
      <button
        onclick={() => { mainTab = "search"; }}
        class="px-4 py-2 rounded-xl text-xs font-semibold transition-all flex items-center gap-2 {mainTab === 'search' ? 'bg-amber-500 text-black font-bold shadow-md shadow-amber-500/10' : 'text-zinc-400 hover:text-white hover:bg-white/5'}"
      >
        <span>🔍 Live Catalog Search</span>
      </button>

      <button
        onclick={() => { mainTab = "progress"; }}
        class="px-4 py-2 rounded-xl text-xs font-semibold transition-all flex items-center gap-2 {mainTab === 'progress' ? 'bg-amber-500 text-black font-bold shadow-md shadow-amber-500/10' : 'text-zinc-400 hover:text-white hover:bg-white/5'}"
      >
        <span>⚡ Live Progress</span>
        {#if sessionStatus === "running" || sessionStatus === "queued"}
          <span class="w-2 h-2 rounded-full bg-amber-400 animate-pulse"></span>
        {:else if sessionStatus === "done"}
          <span class="text-[10px] text-emerald-400 font-bold">✓</span>
        {/if}
      </button>

      <button
        onclick={() => { mainTab = "direct"; }}
        class="px-4 py-2 rounded-xl text-xs font-semibold transition-all flex items-center gap-2 {mainTab === 'direct' ? 'bg-amber-500 text-black font-bold shadow-md shadow-amber-500/10' : 'text-zinc-400 hover:text-white hover:bg-white/5'}"
      >
        <span>🔗 Direct URL</span>
      </button>

      <button
        onclick={() => { mainTab = "queue"; refreshQueue(); }}
        class="px-4 py-2 rounded-xl text-xs font-semibold transition-all flex items-center gap-2 {mainTab === 'queue' ? 'bg-amber-500 text-black font-bold shadow-md shadow-amber-500/10' : 'text-zinc-400 hover:text-white hover:bg-white/5'}"
      >
        <span>📋 Queue & Activity</span>
        {#if (queueSummary.pending?.length || 0) + (queueSummary.active ? 1 : 0) > 0}
          <span class="w-2 h-2 rounded-full bg-amber-400 animate-pulse"></span>
        {/if}
      </button>
    </div>
  </div>

  <!-- Content Views -->
  <div class="flex-1 overflow-y-auto min-h-0">
    <!-- TAB 1: CATALOG SEARCH & EXPLORER -->
    {#if mainTab === "search"}
      <div class="p-8 max-w-6xl mx-auto flex flex-col min-h-full">
        <!-- Subview Header / Breadcrumbs -->
        {#if searchSubView === "artist" && selectedArtist}
          <div class="mb-6 flex items-center justify-between">
            <button
              onclick={() => { searchSubView = "results"; }}
              class="text-xs font-medium text-zinc-400 hover:text-white flex items-center gap-1.5 transition-colors group"
            >
              <span class="group-hover:-translate-x-0.5 transition-transform">←</span> Back to Search Results
            </button>
            <div class="text-xs text-zinc-500">
              Discography: <span class="text-white font-semibold">{selectedArtist.name}</span>
            </div>
          </div>
        {:else if searchSubView === "album" && selectedAlbum}
          <div class="mb-6 flex items-center justify-between">
            <button
              onclick={() => {
                if (selectedArtist) {
                  searchSubView = "artist";
                } else {
                  searchSubView = "results";
                }
              }}
              class="text-xs font-medium text-zinc-400 hover:text-white flex items-center gap-1.5 transition-colors group"
            >
              <span class="group-hover:-translate-x-0.5 transition-transform">←</span> Back
            </button>
            <div class="text-xs text-zinc-500">
              Album Inspector: <span class="text-white font-semibold">{selectedAlbum.title}</span>
            </div>
          </div>
        {:else}
          <!-- Search Bar -->
          <div class="mb-8">
            <div class="relative flex items-center">
              <span class="absolute left-4 text-zinc-500 text-sm">🔍</span>
              <input
                type="text"
                value={searchQuery}
                oninput={handleSearchInput}
                placeholder="Search artists, albums, or tracks (e.g. Daft Punk, Random Access Memories, Get Lucky)..."
                class="w-full bg-[#12100e] border border-[#2a2a2a] rounded-2xl pl-11 pr-10 py-3.5 text-sm text-white placeholder-zinc-600 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-500/20 shadow-lg transition-all"
              />
              {#if searchLoading}
                <div class="absolute right-4 w-4 h-4 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin"></div>
              {:else if searchQuery}
                <button
                  onclick={() => { searchQuery = ""; searchResults = { songs: [], albums: [], artists: [] }; }}
                  class="absolute right-4 text-zinc-500 hover:text-white text-xs font-bold"
                >
                  ✕
                </button>
              {/if}
            </div>

            <!-- Filter Pills -->
            <div class="flex items-center gap-2 mt-4">
              <button
                onclick={() => (activeEntityFilter = "all")}
                class="px-3 py-1 rounded-lg text-xs font-semibold transition-all {activeEntityFilter === 'all' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40' : 'bg-[#15131a] text-zinc-400 border border-[#262330] hover:text-white'}"
              >
                All
              </button>
              <button
                onclick={() => (activeEntityFilter = "artists")}
                class="px-3 py-1 rounded-lg text-xs font-semibold transition-all {activeEntityFilter === 'artists' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40' : 'bg-[#15131a] text-zinc-400 border border-[#262330] hover:text-white'}"
              >
                Artists ({searchResults.artists?.length || 0})
              </button>
              <button
                onclick={() => (activeEntityFilter = "albums")}
                class="px-3 py-1 rounded-lg text-xs font-semibold transition-all {activeEntityFilter === 'albums' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40' : 'bg-[#15131a] text-zinc-400 border border-[#262330] hover:text-white'}"
              >
                Albums ({searchResults.albums?.length || 0})
              </button>
              <button
                onclick={() => (activeEntityFilter = "songs")}
                class="px-3 py-1 rounded-lg text-xs font-semibold transition-all {activeEntityFilter === 'songs' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40' : 'bg-[#15131a] text-zinc-400 border border-[#262330] hover:text-white'}"
              >
                Tracks ({searchResults.songs?.length || 0})
              </button>
            </div>
          </div>
        {/if}

        <!-- 1A. SEARCH RESULTS OVERVIEW -->
        {#if searchSubView === "results"}
          {#if searchError}
            <div class="bg-red-950/30 border border-red-900/50 rounded-2xl p-5 mb-6 text-red-400 text-sm">
              {searchError}
            </div>
          {/if}

          {#if !searchQuery.trim()}
            <div class="flex flex-col items-center justify-center py-20 text-center text-zinc-600">
              <div class="text-4xl mb-3 opacity-60">💿</div>
              <div class="text-white text-base font-semibold">Explore the Apple Music Lossless Catalog</div>
              <div class="text-xs text-zinc-500 mt-1 max-w-md">
                Search for any artist to download their entire studio discography, inspect lossless albums with full tracklists, or rip individual tracks with real-time log feedback.
              </div>
            </div>
          {:else if searchResults.artists.length === 0 && searchResults.albums.length === 0 && searchResults.songs.length === 0 && !searchLoading}
            <div class="flex flex-col items-center justify-center py-16 text-center text-zinc-600">
              <div class="text-3xl mb-2">🔍</div>
              <div class="text-zinc-400 text-sm">No matches found for "{searchQuery}"</div>
            </div>
          {:else}
            <!-- ARTISTS SECTION -->
            {#if (activeEntityFilter === "all" || activeEntityFilter === "artists") && searchResults.artists.length > 0}
              <div class="mb-10">
                <div class="text-xs font-bold uppercase tracking-wider text-amber-500 mb-3 flex items-center gap-2">
                  <span>Artists</span>
                  <span class="text-zinc-600 text-[11px] font-normal">({searchResults.artists.length})</span>
                </div>
                <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                  {#each searchResults.artists as art (art.id)}
                    <button
                      onclick={() => openArtist(art.id)}
                      class="flex items-center gap-3.5 p-3 rounded-2xl bg-[#14121a] hover:bg-[#1c1924] border border-[#23202e] hover:border-amber-500/40 text-left transition-all group shadow-sm"
                    >
                      <div class="w-13 h-13 rounded-full bg-zinc-800 overflow-hidden flex-shrink-0 border border-white/5">
                        {#if art.artwork_url}
                          <img src={formatArtwork(art.artwork_url, 120)} alt={art.name} class="w-full h-full object-cover" />
                        {:else}
                          <div class="w-full h-full flex items-center justify-center text-zinc-500 text-sm">👤</div>
                        {/if}
                      </div>
                      <div class="flex-1 min-w-0">
                        <div class="text-white text-sm font-semibold truncate group-hover:text-amber-400 transition-colors">{art.name}</div>
                        <div class="text-zinc-500 text-xs truncate mt-0.5">
                          {art.genre_names?.join(", ") || art.genres?.join(", ") || "Artist"}
                        </div>
                      </div>
                      <span class="text-zinc-600 group-hover:text-amber-400 group-hover:translate-x-0.5 transition-all text-sm font-bold pr-1">→</span>
                    </button>
                  {/each}
                </div>
              </div>
            {/if}

            <!-- ALBUMS SECTION -->
            {#if (activeEntityFilter === "all" || activeEntityFilter === "albums") && searchResults.albums.length > 0}
              <div class="mb-10">
                <div class="text-xs font-bold uppercase tracking-wider text-amber-500 mb-3 flex items-center gap-2">
                  <span>Albums</span>
                  <span class="text-zinc-600 text-[11px] font-normal">({searchResults.albums.length})</span>
                </div>
                <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
                  {#each searchResults.albums as alb (alb.id)}
                    <div
                      class="group flex flex-col bg-[#14121a] rounded-2xl border border-[#23202e] hover:border-amber-500/40 overflow-hidden transition-all shadow-sm"
                    >
                      <button
                        onclick={() => openAlbum(alb.id)}
                        class="aspect-square bg-zinc-900 overflow-hidden relative text-left"
                      >
                        {#if alb.artwork_url}
                          <img src={formatArtwork(alb.artwork_url, 300)} alt={alb.title} class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
                        {:else}
                          <div class="w-full h-full flex items-center justify-center text-2xl text-zinc-600">💿</div>
                        {/if}
                        <div class="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                          <span class="px-3 py-1 rounded-full bg-amber-500 text-black text-xs font-bold shadow-lg">Inspect Tracks</span>
                        </div>
                      </button>
                      <div class="p-3 flex flex-col flex-1">
                        <button onclick={() => openAlbum(alb.id)} class="text-left">
                          <div class="text-white text-xs font-bold truncate group-hover:text-amber-400 transition-colors" title={alb.title}>
                            {alb.title}
                          </div>
                          <div class="text-zinc-400 text-[11px] truncate mt-0.5" title={alb.artist}>
                            {alb.artist}
                          </div>
                        </button>
                        <div class="mt-auto pt-2 flex items-center justify-between text-[10px] text-zinc-600">
                          <span>{alb.release_date ? alb.release_date.slice(0, 4) : ""}</span>
                          <span>{alb.track_count ? `${alb.track_count} tracks` : ""}</span>
                        </div>
                      </div>
                    </div>
                  {/each}
                </div>
              </div>
            {/if}

            <!-- SONGS / TRACKS SECTION -->
            {#if (activeEntityFilter === "all" || activeEntityFilter === "songs") && searchResults.songs.length > 0}
              <div class="mb-10">
                <div class="text-xs font-bold uppercase tracking-wider text-amber-500 mb-3 flex items-center gap-2">
                  <span>Songs</span>
                  <span class="text-zinc-600 text-[11px] font-normal">({searchResults.songs.length})</span>
                </div>
                <div class="divide-y divide-white/5 bg-[#14121a] rounded-2xl border border-[#23202e] overflow-hidden">
                  {#each searchResults.songs as s (s.id)}
                    <div class="flex items-center justify-between p-3 hover:bg-white/5 transition-colors gap-3">
                      <div class="w-10 h-10 rounded-xl bg-zinc-800 overflow-hidden flex-shrink-0">
                        {#if s.artwork_url}
                          <img src={formatArtwork(s.artwork_url, 80)} alt={s.title} class="w-full h-full object-cover" />
                        {:else}
                          <div class="w-full h-full flex items-center justify-center text-xs text-zinc-500">🎵</div>
                        {/if}
                      </div>
                      <div class="flex-1 min-w-0">
                        <div class="text-white text-xs font-bold truncate">{s.title}</div>
                        <div class="text-zinc-400 text-[11px] truncate mt-0.5">
                          {s.artist} <span class="text-zinc-600">•</span> {s.album}
                        </div>
                      </div>
                      <button
                        onclick={() => downloadSingleTrack(s)}
                        class="px-3 py-1.5 rounded-xl bg-white/5 hover:bg-amber-500 hover:text-black text-zinc-300 text-xs font-semibold transition-colors flex items-center gap-1.5 flex-shrink-0"
                      >
                        <span>↓</span>
                        <span>Download</span>
                      </button>
                    </div>
                  {/each}
                </div>
              </div>
            {/if}
          {/if}
        {/if}

        <!-- 1B. ARTIST DISCOGRAPHY SUBVIEW -->
        {#if searchSubView === "artist"}
          {#if artistLoading}
            <div class="flex flex-col items-center justify-center py-24 gap-3">
              <div class="w-8 h-8 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin"></div>
              <div class="text-zinc-500 text-xs font-medium">Fetching complete discography catalog…</div>
            </div>
          {:else if artistError}
            <div class="bg-red-950/30 border border-red-900/50 rounded-2xl p-5 text-red-400 text-sm">
              {artistError}
            </div>
          {:else if selectedArtist}
            <!-- Artist Hero Card -->
            <div class="p-6 rounded-3xl bg-gradient-to-r from-[#171420] via-[#14121a] to-[#121018] border border-[#282438] flex items-center justify-between gap-6 mb-8 shadow-xl">
              <div class="flex items-center gap-5">
                <div class="w-20 h-20 rounded-full bg-zinc-800 overflow-hidden flex-shrink-0 border-2 border-amber-500/30 shadow-lg">
                  {#if selectedArtist.artwork_url}
                    <img src={formatArtwork(selectedArtist.artwork_url, 200)} alt={selectedArtist.name} class="w-full h-full object-cover" />
                  {:else}
                    <div class="w-full h-full flex items-center justify-center text-2xl text-zinc-500">👤</div>
                  {/if}
                </div>
                <div>
                  <div class="text-[10px] uppercase tracking-widest text-amber-400 font-bold mb-1">Artist Discography</div>
                  <h1 class="text-white text-2xl font-bold">{selectedArtist.name}</h1>
                  <div class="flex items-center gap-3 text-xs text-zinc-400 mt-1">
                    <span>{selectedArtist.genres?.join(", ") || selectedArtist.genre_names?.join(", ") || "Artist"}</span>
                    <span>•</span>
                    <span class="text-amber-400 font-semibold">{selectedArtist.albums?.length || 0} Total Releases</span>
                  </div>
                </div>
              </div>

              <!-- Quick Selection Actions -->
              <div class="flex items-center gap-2 flex-wrap justify-end">
                <button
                  onclick={selectAllAlbums}
                  class="px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 text-xs font-semibold text-zinc-300 transition-colors"
                >
                  Select All
                </button>
                <button
                  onclick={selectStudioAlbumsOnly}
                  class="px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 text-xs font-semibold text-amber-400 transition-colors"
                >
                  Studio Albums Only
                </button>
                <button
                  onclick={deselectAllAlbums}
                  class="px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 text-xs font-semibold text-zinc-500 hover:text-zinc-300 transition-colors"
                >
                  Deselect All
                </button>
              </div>
            </div>

            <!-- Discography Filter Tabs -->
            <div class="flex items-center justify-between mb-4">
              <div class="flex items-center gap-2">
                <button
                  onclick={() => (artistFilter = "all")}
                  class="px-3 py-1.5 rounded-xl text-xs font-semibold transition-colors {artistFilter === 'all' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' : 'text-zinc-500 hover:text-zinc-300'}"
                >
                  All Releases ({selectedArtist.albums?.length || 0})
                </button>
                <button
                  onclick={() => (artistFilter = "albums")}
                  class="px-3 py-1.5 rounded-xl text-xs font-semibold transition-colors {artistFilter === 'albums' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' : 'text-zinc-500 hover:text-zinc-300'}"
                >
                  Studio Albums ({selectedArtist.albums?.filter(a => !a.is_single).length || 0})
                </button>
                <button
                  onclick={() => (artistFilter = "singles")}
                  class="px-3 py-1.5 rounded-xl text-xs font-semibold transition-colors {artistFilter === 'singles' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' : 'text-zinc-500 hover:text-zinc-300'}"
                >
                  Singles & EPs ({selectedArtist.albums?.filter(a => a.is_single).length || 0})
                </button>
              </div>

              <div class="text-xs text-zinc-500">
                {selectedAlbumIds.size} of {filteredArtistAlbums().length} selected
              </div>
            </div>

            <!-- Discography Grid -->
            <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4 pb-28">
              {#each filteredArtistAlbums() as alb (alb.id)}
                {@const isSelected = selectedAlbumIds.has(alb.id)}
                <div
                  class="group relative flex flex-col bg-[#14121a] rounded-2xl border transition-all overflow-hidden shadow-sm {isSelected ? 'border-amber-500 bg-amber-500/5 ring-2 ring-amber-500/20' : 'border-[#23202e] hover:border-amber-500/40'}"
                >
                  <!-- Checkbox Overlay -->
                  <div class="absolute top-2.5 left-2.5 z-10">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onchange={() => toggleAlbumSelection(alb.id)}
                      class="w-4 h-4 rounded text-amber-500 accent-amber-500 cursor-pointer"
                    />
                  </div>

                  <!-- Cover Art -->
                  <button
                    onclick={() => openAlbum(alb.id)}
                    class="aspect-square bg-zinc-900 overflow-hidden relative text-left"
                  >
                    {#if alb.artwork_url}
                      <img src={formatArtwork(alb.artwork_url, 300)} alt={alb.title} class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
                    {:else}
                      <div class="w-full h-full flex items-center justify-center text-2xl text-zinc-600">💿</div>
                    {/if}
                    {#if alb.is_single}
                      <div class="absolute top-2.5 right-2.5 px-1.5 py-0.5 rounded text-[9px] font-bold bg-black/70 text-zinc-300 border border-white/10">
                        SINGLE
                      </div>
                    {/if}
                  </button>

                  <!-- Details -->
                  <div class="p-3 flex flex-col flex-1">
                    <button onclick={() => openAlbum(alb.id)} class="text-left">
                      <div class="text-white text-xs font-bold truncate group-hover:text-amber-400 transition-colors" title={alb.title}>
                        {alb.title}
                      </div>
                      <div class="text-zinc-500 text-[11px] truncate mt-0.5">
                        {alb.release_date ? alb.release_date.slice(0, 4) : ""} • {alb.track_count} tracks
                      </div>
                    </button>

                    <div class="mt-3 pt-2 border-t border-white/5 flex items-center justify-between">
                      <button
                        onclick={() => toggleAlbumSelection(alb.id)}
                        class="text-[11px] font-semibold transition-colors {isSelected ? 'text-amber-400' : 'text-zinc-500 hover:text-white'}"
                      >
                        {isSelected ? '✓ Selected' : '+ Select'}
                      </button>
                      <button
                        onclick={() => openAlbum(alb.id)}
                        class="text-[11px] text-zinc-600 hover:text-amber-400 font-medium"
                      >
                        Tracks →
                      </button>
                    </div>
                  </div>
                </div>
              {/each}
            </div>

            <!-- Sticky Bottom Batch Action Bar -->
            {#if selectedAlbumIds.size > 0}
              <div class="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 bg-[#171422]/95 backdrop-blur-xl border border-amber-500/40 rounded-2xl px-6 py-3.5 shadow-2xl flex items-center gap-6 animate-in fade-in slide-in-from-bottom-4">
                <div class="flex items-center gap-3">
                  <div class="w-8 h-8 rounded-full bg-amber-500 text-black flex items-center justify-center font-bold text-xs">
                    {selectedAlbumIds.size}
                  </div>
                  <div>
                    <div class="text-white text-xs font-bold">
                      {selectedAlbumIds.size} Album{selectedAlbumIds.size === 1 ? "" : "s"} Selected
                    </div>
                    <div class="text-zinc-400 text-[11px]">
                      ~{selectedAlbumsTrackCount()} total tracks • {format} Lossless
                    </div>
                  </div>
                </div>

                <div class="h-6 w-px bg-white/10"></div>

                <div class="flex items-center gap-3">
                  <button
                    onclick={deselectAllAlbums}
                    class="text-xs text-zinc-400 hover:text-white font-medium"
                  >
                    Clear
                  </button>
                  <button
                    onclick={downloadSelectedAlbums}
                    class="px-5 py-2.5 rounded-xl font-bold text-xs text-black transition-all hover:bg-amber-400 flex items-center gap-2 shadow-lg shadow-amber-500/20"
                    style="background:var(--accent);"
                  >
                    <span>↓ Download Selected ({selectedAlbumIds.size} Albums)</span>
                  </button>
                </div>
              </div>
            {/if}
          {/if}
        {/if}

        <!-- 1C. FULL ALBUM TRACKLIST INSPECTOR SUBVIEW -->
        {#if searchSubView === "album"}
          {#if albumLoading}
            <div class="flex flex-col items-center justify-center py-24 gap-3">
              <div class="w-8 h-8 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin"></div>
              <div class="text-zinc-500 text-xs font-medium">Loading album tracklist & lossless details…</div>
            </div>
          {:else if albumError}
            <div class="bg-red-950/30 border border-red-900/50 rounded-2xl p-5 text-red-400 text-sm">
              {albumError}
            </div>
          {:else if selectedAlbum}
            <!-- Album Hero Header -->
            <div class="p-6 rounded-3xl bg-gradient-to-r from-[#171420] via-[#14121a] to-[#121018] border border-[#282438] flex flex-col md:flex-row items-start md:items-center justify-between gap-6 mb-8 shadow-xl">
              <div class="flex items-center gap-6">
                <div class="w-28 h-28 rounded-2xl bg-zinc-800 overflow-hidden flex-shrink-0 border border-white/10 shadow-lg">
                  {#if selectedAlbum.artwork_url}
                    <img src={formatArtwork(selectedAlbum.artwork_url, 400)} alt={selectedAlbum.title} class="w-full h-full object-cover" />
                  {:else}
                    <div class="w-full h-full flex items-center justify-center text-3xl text-zinc-500">💿</div>
                  {/if}
                </div>
                <div>
                  <div class="text-[10px] uppercase tracking-widest text-amber-400 font-bold mb-1">
                    {selectedAlbum.is_single ? "Single / EP" : "Album"}
                  </div>
                  <h1 class="text-white text-2xl font-bold">{selectedAlbum.title}</h1>
                  <div class="text-zinc-300 text-sm font-semibold mt-0.5">{selectedAlbum.artist}</div>
                  <div class="flex items-center gap-3 text-xs text-zinc-500 mt-2 flex-wrap">
                    <span>{selectedAlbum.release_date ? selectedAlbum.release_date.slice(0, 4) : ""}</span>
                    <span>•</span>
                    <span>{selectedAlbum.tracks?.length || selectedAlbum.track_count} Tracks</span>
                    {#if selectedAlbum.record_label}
                      <span>•</span>
                      <span class="truncate max-w-xs">{selectedAlbum.record_label}</span>
                    {/if}
                    {#if selectedAlbum.genre_names?.length}
                      <span>•</span>
                      <span>{selectedAlbum.genre_names.join(", ")}</span>
                    {/if}
                  </div>
                </div>
              </div>

              <!-- Download Album CTA -->
              <div class="flex items-center gap-3 w-full md:w-auto">
                <button
                  onclick={downloadCurrentAlbum}
                  class="w-full md:w-auto px-6 py-3 rounded-2xl font-bold text-xs text-black transition-all hover:bg-amber-400 flex items-center justify-center gap-2 shadow-xl shadow-amber-500/20"
                  style="background:var(--accent);"
                >
                  <span>↓ Download Full Album ({format})</span>
                </button>
              </div>
            </div>

            <!-- Tracklist Table -->
            <div class="bg-[#14121a] rounded-2xl border border-[#23202e] overflow-hidden mb-12">
              <div class="px-5 py-3 border-b border-white/5 text-[11px] font-bold text-zinc-500 uppercase tracking-wider flex items-center">
                <span class="w-8 text-center">#</span>
                <span class="flex-1">Title</span>
                <span class="w-24 text-right pr-4">Duration</span>
                <span class="w-28 text-right">Action</span>
              </div>
              <div class="divide-y divide-white/5">
                {#each (selectedAlbum.tracks || []) as trk (trk.id)}
                  <div class="px-5 py-3 hover:bg-white/5 transition-colors flex items-center text-xs group">
                    <span class="w-8 text-center text-zinc-500 font-mono font-medium">{trk.track_number || "—"}</span>
                    <div class="flex-1 min-w-0 pr-4">
                      <div class="text-white font-semibold truncate group-hover:text-amber-400 transition-colors">{trk.title}</div>
                      {#if trk.artist !== selectedAlbum.artist}
                        <div class="text-zinc-500 text-[11px] truncate mt-0.5">{trk.artist}</div>
                      {/if}
                    </div>
                    <span class="w-24 text-right pr-4 text-zinc-500 font-mono">{formatDuration(trk.duration_ms)}</span>
                    <div class="w-28 text-right">
                      <button
                        onclick={() => downloadSingleTrack(trk)}
                        class="px-2.5 py-1 rounded-lg bg-white/5 hover:bg-amber-500 hover:text-black text-zinc-400 text-[11px] font-semibold transition-colors inline-flex items-center gap-1"
                      >
                        <span>↓</span>
                        <span>Rip Track</span>
                      </button>
                    </div>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        {/if}
      </div>

    <!-- TAB 2: LIVE DOWNLOAD PROGRESS STATION (Dedicated Session Viewer) -->
    {:else if mainTab === "progress"}
      <div class="p-8 max-w-3xl mx-auto flex flex-col min-h-full">
        {#if !activeSession}
          <div class="flex flex-col items-center justify-center py-24 text-center text-zinc-600">
            <div class="text-4xl mb-3 opacity-60">⚡</div>
            <div class="text-white text-base font-semibold">No Download in Progress</div>
            <div class="text-xs text-zinc-500 mt-1 max-w-md">
              Start an album rip, artist discography download, or direct URL download to view real-time logs and progress here.
            </div>
            <button
              onclick={() => { mainTab = "search"; }}
              class="mt-6 px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-xs font-semibold text-amber-400 transition-colors"
            >
              ← Search Catalog
            </button>
          </div>
        {:else}
          <!-- Session Header Card -->
          <div class="p-6 rounded-3xl bg-gradient-to-r from-[#171420] via-[#14121a] to-[#121018] border border-[#282438] mb-6 shadow-xl flex items-center justify-between gap-6">
            <div class="flex items-center gap-5">
              <div class="w-16 h-16 rounded-2xl bg-zinc-800 overflow-hidden flex-shrink-0 border border-white/10 shadow-md">
                {#if activeSession.artworkUrl}
                  <img src={formatArtwork(activeSession.artworkUrl, 160)} alt={activeSession.title} class="w-full h-full object-cover" />
                {:else}
                  <div class="w-full h-full flex items-center justify-center text-2xl text-zinc-500">💿</div>
                {/if}
              </div>
              <div>
                <div class="flex items-center gap-2 mb-1">
                  <span class="text-[10px] uppercase tracking-widest text-amber-400 font-bold">
                    {activeSession.type === "batch" ? "Batch Discography Download" : activeSession.type === "album" ? "Lossless Album Download" : activeSession.type === "single" ? "Single Track Lossless Rip" : "Direct URL Download"}
                  </span>
                  <span class="px-2 py-0.2 rounded-full text-[9px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                    {activeSession.format}
                  </span>
                </div>
                <h1 class="text-white text-xl font-bold">{activeSession.title}</h1>
                <div class="text-zinc-400 text-xs mt-0.5">{activeSession.subtitle}</div>
              </div>
            </div>

            <!-- Cancel / Abort Button during active download -->
            {#if sessionStatus === "running" || sessionStatus === "queued"}
              <button
                onclick={abortCurrentSession}
                class="px-3.5 py-1.5 rounded-xl bg-red-950/40 hover:bg-red-900/60 border border-red-800/50 text-red-300 text-xs font-semibold transition-colors flex items-center gap-1.5"
              >
                <span>✕</span>
                <span>Cancel</span>
              </button>
            {/if}
          </div>

          <!-- Session Log Path banner -->
          {#if logPath}
            <div class="mb-5 flex items-center justify-between gap-3 rounded-2xl border border-[#1a1a1a] bg-[#12100e] px-4 py-2.5">
              <div class="min-w-0">
                <div class="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">Session Log Path</div>
                <div class="truncate font-mono text-xs text-zinc-400" title={logPath}>{logPath}</div>
              </div>
              <button
                onclick={copyLogPath}
                class="shrink-0 text-[10px] px-2.5 py-1 rounded-lg bg-[#1a1a1a] hover:bg-[#252525] text-zinc-400 hover:text-white transition-colors uppercase tracking-widest font-semibold"
              >
                {copiedLogPath ? "✓ Copied" : "Copy Path"}
              </button>
            </div>
          {/if}

          <!-- Phase Timeline -->
          <div class="flex items-center gap-0 mb-6">
            {#each PHASES as step, i}
              {@const done = sessionStatus === "done" ? true : phaseIndex > i}
              {@const active = phaseIndex === i && (sessionStatus === "running" || sessionStatus === "queued")}
              <div class="flex items-center gap-0">
                <div class="flex flex-col items-center gap-1">
                  <div class="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-colors
                    {done   ? 'bg-amber-900/60 text-amber-400 border border-amber-800/50' :
                     active  ? 'bg-amber-800/60 text-amber-300 border border-amber-700/50' :
                               'bg-[#1a1a1a] text-zinc-600 border border-[#2a2a2a]'}">
                    {#if done}✓{:else if active}
                      <span class="w-2.5 h-2.5 rounded-full bg-amber-400 animate-pulse"></span>
                    {:else}{i + 1}{/if}
                  </div>
                  <span class="text-[9px] uppercase tracking-widest font-semibold whitespace-nowrap
                    {done ? 'text-amber-500' : active ? 'text-amber-400' : 'text-zinc-700'}">
                    {step.label}
                  </span>
                </div>
                {#if i < PHASES.length - 1}
                  <div class="w-12 h-px mb-4 mx-1 transition-colors {done ? 'bg-amber-900/50' : 'bg-[#222]'}"></div>
                {/if}
              </div>
            {/each}
          </div>

          <!-- Multi-Item Batch Stepper (If batch discography download) -->
          {#if activeSession.items.length > 1}
            <div class="mb-6 bg-[#14121a] rounded-2xl border border-[#23202e] p-4">
              <div class="flex items-center justify-between mb-3 text-xs font-bold uppercase tracking-wider text-zinc-400">
                <span>Batch Queue ({activeSession.items.filter(i => i.status === "done").length} of {activeSession.items.length} Complete)</span>
                <span class="text-amber-400 font-mono">{progressPct()}%</span>
              </div>
              <div class="space-y-2 max-h-48 overflow-y-auto pr-1">
                {#each activeSession.items as item, idx (item.id)}
                  <div class="flex items-center justify-between p-2.5 rounded-xl transition-colors text-xs {idx === currentItemIndex && sessionStatus === 'running' ? 'bg-amber-500/10 border border-amber-500/30' : 'bg-white/[0.02] border border-white/5'}">
                    <div class="flex items-center gap-3 min-w-0 pr-2">
                      <span class="w-5 text-center font-mono text-zinc-500">{idx + 1}</span>
                      <div class="truncate font-semibold text-white">{item.title}</div>
                    </div>
                    <div class="flex items-center gap-2 flex-shrink-0 font-mono text-[11px]">
                      {#if item.status === "done"}
                        <span class="text-emerald-400 font-bold">✓ Done (+{item.new ?? 0})</span>
                      {:else if item.status === "running"}
                        <span class="text-amber-400 animate-pulse flex items-center gap-1.5">
                          <span class="w-2 h-2 rounded-full bg-amber-400 animate-ping"></span>
                          <span>Downloading…</span>
                        </span>
                      {:else if item.status === "error"}
                        <span class="text-red-400 font-bold">✕ Error</span>
                      {:else}
                        <span class="text-zinc-600">Queued</span>
                      {/if}
                    </div>
                  </div>
                {/each}
              </div>
            </div>
          {/if}

          <!-- Live Metrics & Counters -->
          {#if sessionStatus === "queued"}
            <div class="flex items-center gap-3 text-zinc-400 text-sm mb-6 bg-[#14121a] p-5 rounded-2xl border border-[#23202e]">
              <span class="w-4 h-4 border border-zinc-600 border-t-zinc-300 rounded-full animate-spin flex-shrink-0"></span>
              Waiting in download queue{sessionQueuePos > 0 ? ` — position ${sessionQueuePos}` : ""}…
            </div>
          {:else if sessionStatus === "running"}
            <div class="grid grid-cols-3 gap-3 mb-4">
              <div class="bg-[#12100e] border border-white/5 rounded-2xl p-3.5">
                <div class="text-amber-400 text-2xl font-bold tabular-nums">{liveNew}</div>
                <div class="text-zinc-500 text-xs mt-0.5">new tracks added</div>
              </div>
              <div class="bg-[#12100e] border border-white/5 rounded-2xl p-3.5">
                <div class="text-zinc-400 text-2xl font-bold tabular-nums">{liveSkipped}</div>
                <div class="text-zinc-500 text-xs mt-0.5">already owned</div>
              </div>
              <div class="bg-[#12100e] border border-white/5 rounded-2xl p-3.5">
                <div class="text-2xl font-bold tabular-nums {liveErrors > 0 ? 'text-red-400' : 'text-zinc-600'}">{liveErrors}</div>
                <div class="text-zinc-500 text-xs mt-0.5">errors</div>
              </div>
            </div>

            <!-- Progress Bar -->
            <div class="mb-3">
              <div class="flex justify-between text-xs text-zinc-500 mb-1.5">
                <span class="truncate pr-2">
                  {#if progressTotal > 0}
                    Scanning track {progressCurrent} of {progressTotal}
                    {#if liveNew > 0}
                      <span class="text-amber-400 font-medium ml-1">({liveNew} downloading)</span>
                    {/if}
                  {:else}
                    Working on {currentItem?.title || activeSession.title}…
                  {/if}
                </span>
                <span class="font-mono font-bold text-amber-400">{progressPct()}%</span>
              </div>
              <div class="h-1.5 bg-[#1a1a1a] rounded-full overflow-hidden">
                <div
                  class="h-full rounded-full transition-all duration-300"
                  style="width: {Math.max(3, progressPct())}%; background:linear-gradient(90deg,#b45309,#f59e0b,#fbbf24,#f59e0b,#b45309);background-size:300% 100%;animation:shimmer 2s linear infinite;"
                ></div>
              </div>
            </div>

            <div class="mb-3">
              <div class="text-xs text-zinc-400 truncate font-mono" title={latestMessage}>{latestMessage}</div>
            </div>

            <!-- Terminal Log Viewer -->
            <div
              bind:this={logEl}
              onscroll={handleLogScroll}
              class="flex-1 min-h-[300px] max-h-[420px] bg-[#080808] border border-[#1a1a1a] rounded-2xl p-4 overflow-y-auto font-mono text-xs leading-relaxed"
            >
              {#each logs as line (line.id)}
                <div class="
                  {line.kind === 'add'  ? 'text-amber-400' :
                   line.kind === 'skip' ? 'text-zinc-600' :
                   line.kind === 'err'  ? 'text-red-400' :
                   line.kind === 'done' ? 'text-emerald-400 font-semibold' :
                                          'text-zinc-500'}">
                  {line.text}
                </div>
              {/each}
              {#if logs.length === 0}
                <div class="text-zinc-700">Connecting to Apple Music lossless stream…</div>
              {/if}
            </div>

            {#if totalLogCount > logs.length}
              <div class="mt-2 text-[10px] text-zinc-600 uppercase tracking-widest">
                Showing latest {logs.length} of {totalLogCount} log lines
              </div>
            {/if}

            {#if !autoFollow}
              <div class="mt-3 flex justify-end">
                <button
                  onclick={() => { autoFollow = true; scrollToBottom(); }}
                  class="text-[10px] px-2.5 py-1 rounded-lg bg-[#1a1a1a] text-zinc-400 hover:text-white transition-colors uppercase tracking-widest font-semibold"
                >
                  Jump To Latest Output ↓
                </button>
              </div>
            {/if}

          <!-- Completion Card -->
          {:else if sessionStatus === "done"}
            <div class="bg-[#12100e] rounded-3xl p-6 border border-emerald-900/40 mb-6 shadow-xl">
              <div class="text-emerald-400 font-bold text-sm mb-4 flex items-center gap-2">
                <span>✓</span> Download session complete
              </div>
              <div class="flex gap-8">
                <div>
                  <div class="text-white text-3xl font-bold tabular-nums">{liveNew}</div>
                  <div class="text-zinc-500 text-xs mt-1">new tracks ripped</div>
                </div>
                <div>
                  <div class="text-zinc-400 text-3xl font-bold tabular-nums">{liveSkipped}</div>
                  <div class="text-zinc-500 text-xs mt-1">already in library</div>
                </div>
                <div>
                  <div class="text-3xl font-bold tabular-nums {liveErrors > 0 ? 'text-red-400' : 'text-zinc-700'}">{liveErrors}</div>
                  <div class="text-zinc-500 text-xs mt-1">errors</div>
                </div>
              </div>
            </div>

            {#if logs.length > 0}
              <details class="mb-6 group">
                <summary class="text-zinc-500 text-xs cursor-pointer hover:text-zinc-300 flex items-center gap-1.5 select-none font-semibold">
                  <span class="group-open:rotate-90 transition-transform inline-block">▶</span>
                  View Session Logs ({totalLogCount} lines)
                </summary>
                <div class="mt-2 relative">
                  <div class="bg-[#080808] border border-[#1a1a1a] rounded-2xl p-4 font-mono text-xs text-zinc-500 max-h-56 overflow-y-auto leading-relaxed">
                    {#each logs as line (line.id)}
                      <div class="{line.kind === 'add' ? 'text-amber-400/80' : line.kind === 'err' ? 'text-red-400/80' : ''}">{line.text}</div>
                    {/each}
                  </div>
                  <button
                    onclick={copyLog}
                    class="absolute top-3 right-3 text-[10px] px-2.5 py-1 rounded-lg bg-[#1a1a1a] hover:bg-[#252525] text-zinc-400 hover:text-white transition-colors"
                  >
                    {copiedLog ? "✓ Copied" : "Copy"}
                  </button>
                </div>
              </details>
            {/if}

            <div class="flex items-center gap-3">
              <button
                onclick={() => { mainTab = "search"; }}
                class="flex-1 py-3 rounded-2xl font-bold text-xs text-black transition-all hover:bg-amber-400 flex items-center justify-center gap-2 shadow-lg shadow-amber-500/20"
                style="background:var(--accent);"
              >
                ← Back to Catalog Explorer
              </button>
            </div>

          <!-- Error Card -->
          {:else if sessionStatus === "error"}
            {@const classified = classifyError(sessionErrorMessage ?? "")}
            <div class="bg-red-950/30 border border-red-900/50 rounded-3xl p-6 mb-6">
              <div class="text-red-400 font-bold mb-1">{classified.headline}</div>
              <div class="text-zinc-400 text-xs leading-relaxed">{classified.detail}</div>
            </div>

            {#if logs.length > 0}
              <details open class="mb-6 group">
                <summary class="text-zinc-500 text-xs cursor-pointer hover:text-zinc-300 flex items-center gap-1.5 select-none font-semibold">
                  <span class="group-open:rotate-90 transition-transform inline-block">▶</span>
                  Error Log Trace ({totalLogCount} lines)
                </summary>
                <div class="mt-2 relative">
                  <div class="bg-[#080808] border border-[#1a1a1a] rounded-2xl p-4 font-mono text-xs text-zinc-500 max-h-56 overflow-y-auto leading-relaxed">
                    {#each logs as line (line.id)}
                      <div class="{line.kind === 'err' ? 'text-red-400' : ''}">{line.text}</div>
                    {/each}
                  </div>
                  <button
                    onclick={copyLog}
                    class="absolute top-3 right-3 text-[10px] px-2.5 py-1 rounded-lg bg-[#1a1a1a] hover:bg-[#252525] text-zinc-400 hover:text-white transition-colors"
                  >
                    {copiedLog ? "✓ Copied" : "Copy"}
                  </button>
                </div>
              </details>
            {/if}

            <div class="flex items-center gap-3">
              <button
                onclick={() => { void runCurrentItem(); }}
                class="px-5 py-2.5 rounded-xl bg-amber-500 text-black text-xs font-bold hover:bg-amber-400 transition-colors"
              >
                ↻ Retry Download
              </button>
              <button
                onclick={() => { mainTab = "search"; }}
                class="px-5 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white text-xs font-semibold transition-colors"
              >
                ← Back to Catalog
              </button>
            </div>
          {/if}
        {/if}
      </div>

    <!-- TAB 3: DIRECT URL DOWNLOAD -->
    {:else if mainTab === "direct"}
      <div class="flex flex-col h-full overflow-y-auto p-8 max-w-2xl mx-auto">
        <div class="mb-6">
          <div class="text-amber-500 text-[10px] font-semibold uppercase tracking-widest mb-1">Direct Lossless Rip</div>
          <h2 class="text-white text-2xl font-bold tracking-tight">Paste Apple Music URL</h2>
          <p class="text-zinc-500 text-xs mt-1">Paste any Apple Music album, song, or playlist link to download bit-perfect lossless audio with live log streaming.</p>
        </div>

        <div class="flex gap-2 mb-6">
          <input
            bind:value={directUrl}
            placeholder="https://music.apple.com/us/album/..."
            disabled={sessionStatus === "running" || sessionStatus === "queued"}
            class="flex-1 bg-[#12100e] border border-[#2a2a2a] rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-zinc-700 outline-none focus:border-amber-500 disabled:opacity-50"
          />
          <button
            onclick={startDirectDownload}
            disabled={sessionStatus === "running" || sessionStatus === "queued" || !directUrl.trim()}
            class="text-xs font-bold px-5 rounded-xl hover:bg-amber-400 transition-colors disabled:opacity-50 flex items-center gap-2"
            style="background:var(--accent);color:black;"
          >
            <span>↓ Start Download</span>
          </button>
        </div>

        <div class="bg-[#14121a] rounded-2xl border border-[#23202e] p-6 text-zinc-500 text-xs leading-relaxed">
          <div class="text-white font-semibold text-sm mb-2">Supported Apple Music Links:</div>
          <ul class="list-disc list-inside space-y-1.5">
            <li>Album: <code class="text-amber-400 font-mono">https://music.apple.com/us/album/random-access-memories/617154241</code></li>
            <li>Song: <code class="text-amber-400 font-mono">https://music.apple.com/us/album/get-lucky/617154241?i=617154366</code></li>
            <li>Playlist: <code class="text-amber-400 font-mono">https://music.apple.com/us/playlist/...</code></li>
          </ul>
        </div>
      </div>

    <!-- TAB 4: QUEUE & ACTIVITY -->
    {:else if mainTab === "queue"}
      <div class="p-8 max-w-4xl mx-auto overflow-y-auto h-full">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
          <div>
            <div class="text-amber-500 text-[10px] font-semibold uppercase tracking-widest mb-1">Persistent SQLite Queue</div>
            <h2 class="text-white text-2xl font-bold tracking-tight">Background Download Engine</h2>
          </div>
          <div class="flex items-center gap-2">
            {#if queueSummary.counts.error > 0 || queueSummary.counts.cancelled > 0}
              <button
                onclick={retryFailedQueue}
                class="px-3 py-1.5 rounded-xl bg-amber-500/10 border border-amber-500/30 hover:bg-amber-500/20 text-xs font-semibold text-amber-300 transition-colors flex items-center gap-1.5"
              >
                <span>↻</span>
                <span>Retry Failed</span>
              </button>
            {/if}
            {#if queueSummary.counts.done > 0 || queueSummary.counts.error > 0}
              <button
                onclick={clearCompletedQueue}
                class="px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 text-xs font-semibold text-zinc-400 hover:text-white transition-colors"
              >
                <span>Clear History</span>
              </button>
            {/if}
            {#if queueSummary.counts.pending > 0}
              <button
                onclick={() => cancelQueueJob(undefined, undefined, true)}
                class="px-3 py-1.5 rounded-xl bg-red-950/40 border border-red-900/50 hover:bg-red-900/50 text-xs font-semibold text-red-300 transition-colors"
              >
                <span>Cancel All</span>
              </button>
            {/if}
            <button
              onclick={refreshQueue}
              class="px-3.5 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 text-xs font-semibold text-zinc-300 transition-colors flex items-center gap-1.5"
            >
              <span>↻</span>
              <span>Refresh</span>
            </button>
          </div>
        </div>

        <!-- Metric Counter Cards -->
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
          <div class="bg-[#14121a] border border-[#23202e] rounded-2xl p-4">
            <div class="text-zinc-500 text-[11px] font-semibold uppercase tracking-wider">Pending</div>
            <div class="text-white text-2xl font-bold mt-1 tabular-nums">{queueSummary.counts.pending}</div>
          </div>
          <div class="bg-[#14121a] border border-[#23202e] rounded-2xl p-4">
            <div class="text-zinc-500 text-[11px] font-semibold uppercase tracking-wider">In Progress</div>
            <div class="text-amber-400 text-2xl font-bold mt-1 tabular-nums">{queueSummary.counts.running}</div>
          </div>
          <div class="bg-[#14121a] border border-[#23202e] rounded-2xl p-4">
            <div class="text-zinc-500 text-[11px] font-semibold uppercase tracking-wider">Completed</div>
            <div class="text-emerald-400 text-2xl font-bold mt-1 tabular-nums">{queueSummary.counts.done}</div>
          </div>
          <div class="bg-[#14121a] border border-[#23202e] rounded-2xl p-4">
            <div class="text-zinc-500 text-[11px] font-semibold uppercase tracking-wider">Failed / Cancelled</div>
            <div class="text-2xl font-bold mt-1 tabular-nums {queueSummary.counts.error + queueSummary.counts.cancelled > 0 ? 'text-red-400' : 'text-zinc-600'}">
              {queueSummary.counts.error + queueSummary.counts.cancelled}
            </div>
          </div>
        </div>

        <!-- Active Running Job -->
        <div class="mb-8">
          <div class="text-xs font-bold uppercase tracking-wider text-amber-500 mb-3 flex items-center gap-2">
            <span>In-Flight Download</span>
            {#if queueSummary.active}
              <span class="w-2 h-2 rounded-full bg-amber-400 animate-ping"></span>
            {/if}
          </div>
          {#if queueSummary.active}
            <div class="p-5 rounded-2xl bg-[#14121a] border border-amber-500/40 flex items-center justify-between gap-4 shadow-xl">
              <div class="flex items-center gap-4 min-w-0">
                {#if queueSummary.active.artwork_url}
                  <img
                    src={formatArtwork(queueSummary.active.artwork_url, 120)}
                    alt=""
                    class="w-12 h-12 rounded-xl object-cover border border-white/10 flex-shrink-0"
                  />
                {:else}
                  <div class="w-12 h-12 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400 font-bold flex-shrink-0">
                    ♪
                  </div>
                {/if}
                <div class="min-w-0">
                  <div class="text-white text-sm font-bold truncate">
                    {queueSummary.active.title || queueSummary.active.album || queueSummary.active.url}
                  </div>
                  <div class="text-zinc-400 text-xs mt-0.5 truncate">
                    {#if queueSummary.active.artist}
                      <span>{queueSummary.active.artist} • </span>
                    {/if}
                    <span class="text-amber-400 font-mono text-[11px]">Ripping & Decrypting Lossless...</span>
                  </div>
                </div>
              </div>
              <div class="flex items-center gap-3 flex-shrink-0">
                <span class="px-2.5 py-1 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                  {queueSummary.active.format || "ALAC"}
                </span>
                <button
                  onclick={() => cancelQueueJob(queueSummary.active?.id)}
                  class="px-3 py-1.5 rounded-xl bg-red-950/40 hover:bg-red-900/60 text-red-300 text-xs font-semibold border border-red-900/40 transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          {:else}
            <div class="p-6 rounded-2xl bg-[#14121a] border border-[#23202e] text-center text-zinc-500 text-xs">
              No jobs currently executing.
            </div>
          {/if}
        </div>

        <!-- Pending Queue -->
        <div class="mb-8">
          <div class="text-xs font-bold uppercase tracking-wider text-zinc-400 mb-3 flex items-center justify-between">
            <span>Pending Queue ({queueSummary.pending.length})</span>
            {#if queueSummary.pending.length > 0}
              <span class="text-[10px] text-zinc-500 font-normal">Auto-advances autonomously</span>
            {/if}
          </div>
          {#if queueSummary.pending.length > 0}
            <div class="divide-y divide-white/5 bg-[#14121a] rounded-2xl border border-[#23202e] overflow-hidden">
              {#each queueSummary.pending as job, idx (job.id)}
                <div class="p-4 flex items-center justify-between gap-4 hover:bg-white/[0.02] transition-colors">
                  <div class="flex items-center gap-3.5 min-w-0">
                    <span class="w-6 h-6 rounded-full bg-zinc-800 text-zinc-400 text-xs flex items-center justify-center font-mono flex-shrink-0">
                      {idx + 1}
                    </span>
                    {#if job.artwork_url}
                      <img
                        src={formatArtwork(job.artwork_url, 80)}
                        alt=""
                        class="w-9 h-9 rounded-lg object-cover border border-white/10 flex-shrink-0"
                      />
                    {/if}
                    <div class="min-w-0">
                      <div class="text-white text-xs font-semibold truncate">
                        {job.title || job.album || job.url}
                      </div>
                      <div class="text-zinc-500 text-[11px] mt-0.5 truncate flex items-center gap-2">
                        {#if job.artist}
                          <span>{job.artist}</span>
                        {/if}
                        {#if job.batch_title}
                          <span class="text-zinc-600">• Batch: {job.batch_title}</span>
                        {/if}
                        {#if job.total_tracks && job.total_tracks > 0}
                          <span class="text-zinc-600">• {job.total_tracks} tracks</span>
                        {/if}
                      </div>
                    </div>
                  </div>
                  <div class="flex items-center gap-2.5 flex-shrink-0">
                    <span class="px-2 py-0.5 rounded text-[10px] font-mono bg-white/5 text-zinc-400">
                      {job.format || "ALAC"}
                    </span>
                    <button
                      onclick={() => cancelQueueJob(job.id)}
                      class="p-1.5 rounded-lg hover:bg-red-950/50 text-zinc-600 hover:text-red-400 transition-colors"
                      title="Cancel job"
                    >
                      ✕
                    </button>
                  </div>
                </div>
              {/each}
            </div>
          {:else}
            <div class="p-6 rounded-2xl bg-[#14121a] border border-[#23202e] text-center text-zinc-500 text-xs">
              Queue is empty. Select albums or discographies in the <button onclick={() => (mainTab = 'search')} class="text-amber-400 hover:underline">Catalog Explorer</button>.
            </div>
          {/if}
        </div>

        <!-- Completed / History -->
        {#if queueSummary.completed.length > 0}
          <div>
            <div class="text-xs font-bold uppercase tracking-wider text-zinc-400 mb-3 flex items-center justify-between">
              <span>Completed / History ({queueSummary.completed.length})</span>
            </div>
            <div class="divide-y divide-white/5 bg-[#14121a] rounded-2xl border border-[#23202e] overflow-hidden">
              {#each queueSummary.completed as job (job.id)}
                <div class="p-4 flex items-center justify-between gap-4">
                  <div class="flex items-center gap-3.5 min-w-0">
                    <div class="w-6 h-6 rounded-full flex items-center justify-center text-xs flex-shrink-0 font-bold {job.status === 'done' ? 'bg-emerald-950 text-emerald-400' : 'bg-red-950 text-red-400'}">
                      {job.status === "done" ? "✓" : "!"}
                    </div>
                    {#if job.artwork_url}
                      <img
                        src={formatArtwork(job.artwork_url, 80)}
                        alt=""
                        class="w-9 h-9 rounded-lg object-cover border border-white/10 flex-shrink-0"
                      />
                    {/if}
                    <div class="min-w-0">
                      <div class="text-white text-xs font-semibold truncate">
                        {job.title || job.album || job.url}
                      </div>
                      <div class="text-zinc-500 text-[11px] mt-0.5 truncate flex items-center gap-2">
                        {#if job.artist}
                          <span>{job.artist}</span>
                        {/if}
                        {#if job.status === "done"}
                          <span class="text-emerald-400/80">+{job.new_tracks ?? 0} new, {job.skipped_tracks ?? 0} skipped</span>
                        {:else if job.error_message}
                          <span class="text-red-400 truncate">{job.error_message}</span>
                        {/if}
                      </div>
                    </div>
                  </div>
                  <div class="flex items-center gap-2 flex-shrink-0">
                    {#if job.status === "error" || job.status === "cancelled"}
                      <button
                        onclick={() => api.queue.retry([Number(job.id)]).then(refreshQueue)}
                        class="px-2.5 py-1 rounded-lg bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 text-xs font-semibold border border-amber-500/30 transition-colors"
                      >
                        ↻ Retry
                      </button>
                    {/if}
                    <span class="text-[10px] font-mono uppercase px-2 py-0.5 rounded {job.status === 'done' ? 'text-emerald-400 bg-emerald-950/50' : 'text-red-400 bg-red-950/50'}">
                      {job.status}
                    </span>
                  </div>
                </div>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    {/if}
  </div>
</div>
