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
    type CatalogPlaylist,
    type GenreInfo,
    type GenreChartsResult,
    type Playlist,
    type QueueSummary,
    type QueueJob,
    type SubscribedArtist,
    type PendingRelease,
    type ArtistCheckResult,
  } from "../api";
  import {
    notifyDownloadStarted,
    notifyDownloadCompleted,
    notifyDownloadFailed,
  } from "./notifications";

  // Navigation & Subviews
  type MainTab = "search" | "progress" | "direct" | "queue";
  type SearchSubView = "results" | "artist" | "album" | "playlist";

  let mainTab = $state<MainTab>("search");
  let searchSubView = $state<SearchSubView>("results");

  // Search & Catalog State
  let searchQuery = $state("");
  let searchDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  let searchLoading = $state(false);
  let searchError = $state<string | null>(null);
  let searchResults = $state<CatalogSearchResult>({ songs: [], albums: [], artists: [], playlists: [] });
  let activeEntityFilter = $state<"all" | "albums" | "artists" | "playlists" | "genres" | "songs" | "subscribed">("all");
  let activeProvider = $state<"all" | "apple" | "tidal">("all");

  // Subscribed Artists & Releases State
  let subscribedArtists = $state<SubscribedArtist[]>([]);
  let pendingReleases = $state<PendingRelease[]>([]);
  let checkingReleases = $state(false);
  let subscribingArtistId = $state<string | null>(null);
  let downloadingPendingId = $state<number | null>(null);
  let checkResultMessage = $state<string | null>(null);

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

  // Playlist Inspector View State
  let selectedPlaylist = $state<CatalogPlaylist | null>(null);
  let playlistLoading = $state(false);
  let playlistError = $state<string | null>(null);
  let selectedPlaylistTrackIds = $state<Set<string>>(new Set());

  // Genre Hub State
  let catalogGenresList = $state<GenreInfo[]>([]);
  let selectedGenre = $state<GenreInfo | null>(null);
  let genreCharts = $state<GenreChartsResult | null>(null);
  let genreLoading = $state(false);
  let genreError = $state<string | null>(null);

  // Add to Custom/Local Playlist Modal State
  let localPlaylists = $state<Playlist[]>([]);
  let showAddToPlaylistModal = $state(false);
  let modalTargetTracks = $state<Array<CatalogTrack | CatalogSong>>([]);
  let modalDestinationMode = $state<"existing" | "new">("new");
  let modalSelectedPlaylistName = $state("");
  let modalNewPlaylistName = $state("");
  let modalNewPlaylistDescription = $state("");
  let modalNewPlaylistCoverUrl = $state("");
  let modalDownloadMissing = $state(true);
  let modalSubmitting = $state(false);
  let modalFeedback = $state<string | null>(null);
  let modalError = $state<string | null>(null);

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
    let formatted = url.replace("{w}", String(size)).replace("{h}", String(size));
    if (formatted.includes("resources.tidal.com")) {
      const target = size <= 160 ? "160x160" : size <= 320 ? "320x320" : size <= 640 ? "640x640" : "1280x1280";
      formatted = formatted.replace(/\d+x\d+\.jpg$/, `${target}.jpg`);
    }
    return formatted;
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
    executeSearch(val);
  }

  function executeSearch(query: string) {
    if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
    if (!query.trim()) {
      searchResults = { songs: [], albums: [], artists: [], playlists: [] };
      searchLoading = false;
      searchError = null;
      return;
    }
    searchLoading = true;
    searchError = null;
    searchDebounceTimer = setTimeout(async () => {
      try {
        const res = await api.searchCatalog(query.trim(), ["songs", "albums", "artists", "playlists"], 16, activeProvider);
        searchResults = res;
      } catch (err) {
        searchError = err instanceof Error ? err.message : String(err);
      } finally {
        searchLoading = false;
      }
    }, 350);
  }

  function setProvider(provider: "all" | "apple" | "tidal") {
    activeProvider = provider;
    try {
      localStorage.setItem("preferred_catalog_provider", provider);
    } catch {}
    if (searchQuery.trim()) {
      executeSearch(searchQuery.trim());
    }
  }

  // Open Artist Discography
  async function openArtist(artistIdOrUrl: string, provider?: "apple" | "tidal") {
    artistLoading = true;
    artistError = null;
    selectedAlbumIds = new Set();
    searchSubView = "artist";
    try {
      selectedArtist = await api.catalogArtist(artistIdOrUrl, provider);
    } catch (err) {
      artistError = err instanceof Error ? err.message : String(err);
    } finally {
      artistLoading = false;
    }
  }

  // Open Album Inspector
  async function openAlbum(albumIdOrUrl: string, provider?: "apple" | "tidal") {
    albumLoading = true;
    albumError = null;
    searchSubView = "album";
    try {
      selectedAlbum = await api.catalogAlbum(albumIdOrUrl, provider);
    } catch (err) {
      albumError = err instanceof Error ? err.message : String(err);
    } finally {
      albumLoading = false;
    }
  }

  // Open Playlist Inspector
  async function openPlaylist(playlistIdOrUrl: string, provider?: "apple" | "tidal") {
    playlistLoading = true;
    playlistError = null;
    selectedPlaylistTrackIds = new Set();
    searchSubView = "playlist";
    try {
      selectedPlaylist = await api.catalogPlaylist(playlistIdOrUrl, provider);
      if (selectedPlaylist.tracks && selectedPlaylist.tracks.length > 0) {
        selectedPlaylistTrackIds = new Set(selectedPlaylist.tracks.map((t) => t.id));
      }
    } catch (err) {
      playlistError = err instanceof Error ? err.message : String(err);
    } finally {
      playlistLoading = false;
    }
  }

  function togglePlaylistTrackSelection(trackId: string) {
    const next = new Set(selectedPlaylistTrackIds);
    if (next.has(trackId)) {
      next.delete(trackId);
    } else {
      next.add(trackId);
    }
    selectedPlaylistTrackIds = next;
  }

  function selectAllPlaylistTracks() {
    if (!selectedPlaylist?.tracks) return;
    selectedPlaylistTrackIds = new Set(selectedPlaylist.tracks.map((t) => t.id));
  }

  function deselectAllPlaylistTracks() {
    selectedPlaylistTrackIds = new Set();
  }

  async function selectGenre(genre: GenreInfo) {
    selectedGenre = genre;
    genreLoading = true;
    genreError = null;
    try {
      genreCharts = await api.catalogGenreCharts(genre.id);
    } catch (err) {
      genreError = err instanceof Error ? err.message : String(err);
    } finally {
      genreLoading = false;
    }
  }

  async function loadGenresAndPlaylists() {
    try {
      const [genres, pls] = await Promise.all([
        api.catalogGenres(),
        api.playlists(),
      ]);
      catalogGenresList = genres;
      localPlaylists = pls;
      if (pls.length > 0 && !modalSelectedPlaylistName) {
        modalSelectedPlaylistName = pls[0].name;
      }
    } catch {}
  }

  function openAddToPlaylistModal(
    tracks: Array<CatalogTrack | CatalogSong>,
    suggestedName?: string,
    suggestedDescription?: string,
    suggestedCoverUrl?: string | null,
  ) {
    modalTargetTracks = tracks;
    modalError = null;
    modalFeedback = null;
    if (suggestedName) {
      modalNewPlaylistName = suggestedName;
      modalNewPlaylistDescription = suggestedDescription || "";
      modalNewPlaylistCoverUrl = suggestedCoverUrl || "";
      modalDestinationMode = "new";
    } else if (localPlaylists.length > 0) {
      modalDestinationMode = "existing";
      if (!modalSelectedPlaylistName) modalSelectedPlaylistName = localPlaylists[0].name;
    } else {
      modalDestinationMode = "new";
      modalNewPlaylistName = "My Custom Playlist";
    }
    showAddToPlaylistModal = true;
    api.playlists().then((pls) => {
      localPlaylists = pls;
      if (pls.length > 0 && !modalSelectedPlaylistName) {
        modalSelectedPlaylistName = pls[0].name;
      }
    }).catch(() => {});
  }

  async function submitAddToPlaylist() {
    if (modalTargetTracks.length === 0) return;
    modalSubmitting = true;
    modalError = null;
    modalFeedback = null;
    try {
      let targetName = modalSelectedPlaylistName;
      if (modalDestinationMode === "new") {
        if (!modalNewPlaylistName.trim()) {
          throw new Error("Please enter a playlist name.");
        }
        targetName = modalNewPlaylistName.trim();
        await api.createCustomPlaylist(
          targetName,
          modalNewPlaylistDescription.trim(),
          modalNewPlaylistCoverUrl,
          [],
        );
      }
      if (!targetName) {
        throw new Error("Please select or create a destination playlist.");
      }

      const res = await api.addTracksToPlaylist(
        targetName,
        modalTargetTracks,
        modalDownloadMissing,
        format,
      );
      modalFeedback = `✓ Added to "${res.playlist_name}" (${res.linked_existing} linked from library, ${res.queued_downloads} queued for lossless download)!`;
      await refreshQueue();
      localPlaylists = await api.playlists().catch(() => localPlaylists);
      setTimeout(() => {
        showAddToPlaylistModal = false;
        modalFeedback = null;
      }, 1600);
    } catch (err) {
      modalError = err instanceof Error ? err.message : String(err);
    } finally {
      modalSubmitting = false;
    }
  }

  async function downloadSelectedPlaylistTracks() {
    if (!selectedPlaylist?.tracks || selectedPlaylistTrackIds.size === 0) return;
    const tracksToDownload = selectedPlaylist.tracks.filter((t) => selectedPlaylistTrackIds.has(t.id));
    const isTidal = selectedPlaylist.provider === "tidal";
    const items = tracksToDownload.map((trk) => {
      const trkIsTidal = isTidal || trk.provider === "tidal" || String(trk.id).startsWith("tidal:");
      const cleanId = String(trk.id).replace(/^tidal:(?:track:)?/, "");
      const defaultUrl = trkIsTidal ? `https://tidal.com/browse/track/${cleanId}` : `https://music.apple.com/us/song/${trk.id}`;
      return {
        url: trk.url || defaultUrl,
        title: trk.title,
        artist: trk.artist,
        album: trk.album || selectedPlaylist?.title || "",
        artwork_url: trk.artwork_url || selectedPlaylist?.artwork_url,
        total_tracks: 1,
        item_type: "single",
      };
    });
    try {
      await api.queue.add({
        items,
        format: isTidal ? "FLAC" : format,
        batch_title: `${selectedPlaylist.title} (${items.length} tracks)`,
      });
      mainTab = "queue";
      await refreshQueue();
    } catch (err: any) {
      const msg = err instanceof Error ? err.message : String(err);
      playlistError = `Enqueue failed: ${msg}`;
      notifyDownloadFailed(selectedPlaylist.title, msg);
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
  // SUBSCRIBED ARTISTS & RELEASE CHECKER ACTIONS
  // =========================================================================

  function getSubscribedArtist(artistId?: string | null, service?: string): SubscribedArtist | undefined {
    if (!artistId) return undefined;
    const cleanId = String(artistId).replace(/^tidal:(?:artist:)?/, "");
    return subscribedArtists.find((a) => {
      const aClean = a.artist_id.replace(/^tidal:(?:artist:)?/, "");
      const idMatch = a.artist_id === String(artistId) || aClean === cleanId;
      if (!idMatch) return false;
      return service ? a.service === service : true;
    });
  }

  function isArtistSubscribed(artistId?: string | null, service?: string): boolean {
    return !!getSubscribedArtist(artistId, service);
  }

  async function refreshSubscriptions() {
    try {
      const [subs, pending] = await Promise.all([
        api.artists.getSubscriptions(),
        api.artists.getPendingReleases("available"),
      ]);
      subscribedArtists = subs;
      pendingReleases = pending;
    } catch (err) {
      console.error("Failed to refresh artist subscriptions:", err);
    }
  }

  async function toggleArtistSubscription(artist: { id: string; name: string; url?: string; artwork_url?: string | null; service?: string; provider?: string }) {
    const isTidal = artist.service === "tidal" || artist.provider === "tidal" || artist.id.startsWith("tidal:") || (artist.url?.includes("tidal.com") ?? false);
    const service = isTidal ? "tidal" : "apple_music";
    const existing = getSubscribedArtist(artist.id, service);
    subscribingArtistId = artist.id;
    try {
      if (existing) {
        await api.artists.unsubscribe(artist.id, existing.service || service);
        subscribedArtists = subscribedArtists.filter((a) => !(a.artist_id === artist.id && a.service === service));
      } else {
        const res = await api.artists.subscribe({
          artist_id: artist.id,
          name: artist.name,
          service,
          url: artist.url,
          artwork_url: artist.artwork_url,
          auto_download: false,
        });
        if (res.artist) {
          subscribedArtists = [...subscribedArtists.filter((a) => !(a.artist_id === artist.id && a.service === service)), res.artist];
        }
        await refreshSubscriptions();
      }
    } catch (err) {
      console.error("Failed to toggle artist subscription:", err);
    } finally {
      subscribingArtistId = null;
    }
  }

  async function updateArtistAutoDownload(artistId: string, autoDownload: boolean) {
    try {
      const existing = getSubscribedArtist(artistId);
      const service = existing?.service || (artistId.startsWith("tidal:") ? "tidal" : "apple_music");
      await api.artists.updateSubscription(artistId, autoDownload, service);
      subscribedArtists = subscribedArtists.map((a) => (a.artist_id === artistId ? { ...a, auto_download: autoDownload } : a));
    } catch (err) {
      console.error("Failed to update auto_download:", err);
    }
  }

  async function checkReleasesNow(artistId?: string) {
    checkingReleases = true;
    checkResultMessage = null;
    try {
      let res: ArtistCheckResult;
      if (artistId) {
        const existing = getSubscribedArtist(artistId);
        const service = existing?.service || (artistId.startsWith("tidal:") ? "tidal" : "apple_music");
        res = await api.artists.checkReleases(artistId, service);
      } else {
        res = await api.artists.checkReleases(undefined, "all");
      }
      await refreshSubscriptions();
      if (res.total_new_releases && res.total_new_releases > 0) {
        checkResultMessage = `Found ${res.total_new_releases} new ${res.total_new_releases === 1 ? 'release' : 'releases'}! (${res.total_enqueued || 0} queued)`;
      } else {
        checkResultMessage = "All subscribed artists are up to date.";
      }
      setTimeout(() => { checkResultMessage = null; }, 5000);
    } catch (err) {
      checkResultMessage = err instanceof Error ? err.message : String(err);
      setTimeout(() => { checkResultMessage = null; }, 5000);
    } finally {
      checkingReleases = false;
    }
  }


  async function downloadPendingRelease(relId: number) {
    downloadingPendingId = relId;
    try {
      await api.artists.downloadPendingRelease(relId);
      pendingReleases = pendingReleases.filter((r) => r.id !== relId);
      refreshQueue();
    } catch (err) {
      console.error("Failed to download release:", err);
    } finally {
      downloadingPendingId = null;
    }
  }

  async function downloadAllPending() {
    try {
      await api.artists.downloadAllPendingReleases();
      pendingReleases = [];
      refreshQueue();
    } catch (err) {
      console.error("Failed to download all releases:", err);
    }
  }

  async function dismissPending(relId: number) {
    try {
      await api.artists.dismissPendingRelease(relId);
      pendingReleases = pendingReleases.filter((r) => r.id !== relId);
    } catch (err) {
      console.error("Failed to dismiss release:", err);
    }
  }

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
    const isTidal = selectedArtist.provider === "tidal";
    const items = selected.map((alb) => {
      const albIsTidal = isTidal || alb.provider === "tidal" || alb.id.startsWith("tidal:");
      const cleanId = alb.id.replace(/^tidal:(?:album:)?/, "");
      const defaultUrl = albIsTidal ? `https://tidal.com/browse/album/${cleanId}` : `https://music.apple.com/us/album/${alb.id}`;
      return {
        url: alb.url || defaultUrl,
        title: alb.title,
        artist: alb.artist || selectedArtist?.name,
        album: alb.title,
        artwork_url: alb.artwork_url || selectedArtist?.artwork_url,
        total_tracks: alb.track_count || alb.tracks?.length || 0,
        item_type: "album",
      };
    });

    try {
      await api.queue.add({
        items,
        format: isTidal ? "FLAC" : format,
        batch_title: `${selectedArtist.name} — Discography Batch`,
      });
      selectedAlbumIds = new Set();
      mainTab = "queue";
      await refreshQueue();
    } catch (err: any) {
      console.error("Failed to enqueue discography:", err);
      const msg = err instanceof Error ? err.message : String(err);
      artistError = `Enqueue failed: ${msg}`;
      notifyDownloadFailed(selectedArtist.name, msg);
    }
  }

  // Quick Action: Download Current Album
  async function downloadCurrentAlbum() {
    if (!selectedAlbum) return;
    const isTidal = selectedAlbum.provider === "tidal" || selectedAlbum.id.startsWith("tidal:") || (selectedAlbum.url?.includes("tidal.com") ?? false);
    const cleanId = selectedAlbum.id.replace(/^tidal:(?:album:)?/, "");
    const defaultUrl = isTidal ? `https://tidal.com/browse/album/${cleanId}` : `https://music.apple.com/us/album/${selectedAlbum.id}`;
    try {
      await api.queue.add({
        items: [{
          url: selectedAlbum.url || defaultUrl,
          title: selectedAlbum.title,
          artist: selectedAlbum.artist,
          album: selectedAlbum.title,
          artwork_url: selectedAlbum.artwork_url,
          total_tracks: selectedAlbum.tracks?.length || selectedAlbum.track_count || 0,
          item_type: "album",
        }],
        format: isTidal ? "FLAC" : format,
        batch_title: selectedAlbum.title,
      });
      mainTab = "queue";
      await refreshQueue();
    } catch (err: any) {
      console.error("Failed to enqueue album:", err);
      const msg = err instanceof Error ? err.message : String(err);
      albumError = `Enqueue failed: ${msg}`;
      notifyDownloadFailed(selectedAlbum.title, msg);
    }
  }

  // Quick Action: Download Single Track
  async function downloadSingleTrack(track: CatalogTrack | CatalogSong) {
    const isTidal = track.provider === "tidal" || track.id.startsWith("tidal:") || (track.url?.includes("tidal.com") ?? false);
    const cleanId = track.id.replace(/^tidal:(?:track:)?/, "");
    const defaultUrl = isTidal ? `https://tidal.com/browse/track/${cleanId}` : `https://music.apple.com/us/song/${track.id}`;
    const url = track.url || defaultUrl;
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
        format: isTidal ? "FLAC" : format,
        batch_title: track.title,
      });
      mainTab = "queue";
      await refreshQueue();
    } catch (err: any) {
      console.error("Failed to enqueue single track:", err);
      const msg = err instanceof Error ? err.message : String(err);
      notifyDownloadFailed(track.title, msg);
    }
  }

  // Quick Action: Start Direct URL Download
  async function startDirectDownload() {
    if (!directUrl.trim()) return;
    const url = directUrl.trim();
    const isTidal = url.includes("tidal.com") || url.startsWith("tidal:");
    try {
      await api.queue.add({
        urls: [url],
        format: isTidal ? "FLAC" : format,
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
    try {
      const saved = localStorage.getItem("preferred_catalog_provider");
      if (saved === "all" || saved === "apple" || saved === "tidal") {
        activeProvider = saved;
      }
    } catch {}
    refreshQueue();
    refreshSubscriptions();
    loadGenresAndPlaylists();
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
        <h2 class="text-white text-2xl font-bold tracking-tight">Lossless Music Downloader</h2>
      </div>

      <!-- Format Selector -->
      <div class="flex items-center gap-2 bg-[#12100e] border border-[#2a2a2a] rounded-xl px-3 py-1.5 shadow-sm">
        <span class="text-xs text-zinc-500 font-medium">Format:</span>
        <select
          bind:value={format}
          class="bg-transparent text-xs font-bold text-amber-400 outline-none cursor-pointer"
        >
          <option value="ALAC">ALAC / FLAC (Lossless)</option>
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
        <!-- Subview Header / Breadcrumbs & Navigation Pills -->
        {#if searchSubView === "artist" && selectedArtist}
          <div class="mb-6 flex items-center justify-between gap-4 flex-wrap">
            <div class="flex items-center gap-2 flex-wrap">
              <button
                onclick={() => { searchSubView = "results"; }}
                class="px-3 py-1.5 rounded-xl bg-[#12100e] border border-[#2a2a2a] text-xs font-semibold text-zinc-400 hover:text-white hover:border-amber-500/40 flex items-center gap-1.5 transition-all shadow-sm group"
              >
                <span class="group-hover:-translate-x-0.5 transition-transform">←</span>
                <span>Search Results</span>
              </button>
              <span class="text-zinc-600 text-xs font-bold">/</span>
              <div class="px-3 py-1.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-xs font-bold text-amber-300 flex items-center gap-1.5 shadow-sm">
                <span>👤</span>
                <span class="truncate max-w-[200px] sm:max-w-[320px]">{selectedArtist.name}</span>
              </div>
            </div>

            <div class="flex items-center gap-2">
              <span class="px-2.5 py-1 rounded-lg text-[11px] font-bold uppercase tracking-wider flex items-center gap-1.5 {selectedArtist.provider === 'tidal' ? 'bg-cyan-950/80 text-cyan-400 border border-cyan-800/50' : 'bg-pink-950/80 text-pink-400 border border-pink-800/50'}">
                {selectedArtist.provider === 'tidal' ? '🌊 Tidal Lossless' : '🍎 Apple Music'}
              </span>
              <button
                onclick={() => { searchSubView = "results"; searchQuery = ""; }}
                class="px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white text-xs transition-colors"
                title="Start a new search"
              >
                New Search
              </button>
            </div>
          </div>
        {:else if searchSubView === "album" && selectedAlbum}
          <div class="mb-6 flex items-center justify-between gap-4 flex-wrap">
            <div class="flex items-center gap-2 flex-wrap">
              <button
                onclick={() => { searchSubView = "results"; }}
                class="px-3 py-1.5 rounded-xl bg-[#12100e] border border-[#2a2a2a] text-xs font-semibold text-zinc-400 hover:text-white hover:border-amber-500/40 flex items-center gap-1.5 transition-all shadow-sm group"
              >
                <span class="group-hover:-translate-x-0.5 transition-transform">←</span>
                <span>Search</span>
              </button>
              <span class="text-zinc-600 text-xs font-bold">/</span>
              {#if selectedArtist}
                <button
                  onclick={() => { searchSubView = "artist"; }}
                  class="px-3 py-1.5 rounded-xl bg-[#12100e] border border-[#2a2a2a] text-xs font-semibold text-zinc-400 hover:text-white hover:border-amber-500/40 flex items-center gap-1.5 transition-all shadow-sm group"
                >
                  <span>👤</span>
                  <span class="truncate max-w-[150px] sm:max-w-[220px]">{selectedArtist.name}</span>
                </button>
                <span class="text-zinc-600 text-xs font-bold">/</span>
              {/if}
              <div class="px-3 py-1.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-xs font-bold text-amber-300 flex items-center gap-1.5 shadow-sm">
                <span>💿</span>
                <span class="truncate max-w-[200px] sm:max-w-[320px]">{selectedAlbum.title}</span>
              </div>
            </div>

            <div class="flex items-center gap-2">
              <span class="px-2.5 py-1 rounded-lg text-[11px] font-bold uppercase tracking-wider flex items-center gap-1.5 {selectedAlbum.provider === 'tidal' ? 'bg-cyan-950/80 text-cyan-400 border border-cyan-800/50' : 'bg-pink-950/80 text-pink-400 border border-pink-800/50'}">
                {selectedAlbum.provider === 'tidal' ? '🌊 Tidal Lossless' : '🍎 Apple Music'}
              </span>
              <button
                onclick={() => { searchSubView = "results"; searchQuery = ""; }}
                class="px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white text-xs transition-colors"
                title="Start a new search"
              >
                New Search
              </button>
            </div>
          </div>
        {:else if searchSubView === "playlist" && selectedPlaylist}
          <div class="mb-6 flex items-center justify-between gap-4 flex-wrap">
            <div class="flex items-center gap-2 flex-wrap">
              <button
                onclick={() => { searchSubView = "results"; }}
                class="px-3 py-1.5 rounded-xl bg-[#12100e] border border-[#2a2a2a] text-xs font-semibold text-zinc-400 hover:text-white hover:border-amber-500/40 flex items-center gap-1.5 transition-all shadow-sm group"
              >
                <span class="group-hover:-translate-x-0.5 transition-transform">←</span>
                <span>🔍 Search Results</span>
              </button>
              <span class="text-zinc-600 text-xs font-bold">/</span>
              <div class="px-3 py-1.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-xs font-bold text-amber-300 flex items-center gap-1.5 shadow-sm">
                <span>📑</span>
                <span class="truncate max-w-[200px] sm:max-w-[320px]">{selectedPlaylist.title}</span>
              </div>
            </div>

            <div class="flex items-center gap-2">
              <span class="px-2.5 py-1 rounded-lg text-[11px] font-bold uppercase tracking-wider flex items-center gap-1.5 {selectedPlaylist.provider === 'tidal' ? 'bg-cyan-950/80 text-cyan-400 border border-cyan-800/50' : 'bg-pink-950/80 text-pink-400 border border-pink-800/50'}">
                {selectedPlaylist.provider === 'tidal' ? '🌊 Tidal Lossless' : '🍎 Apple Music'}
              </span>
              <button
                onclick={() => { searchSubView = "results"; searchQuery = ""; }}
                class="px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white text-xs transition-colors"
                title="Start a new search"
              >
                New Search
              </button>
            </div>
          </div>
        {:else}
          <!-- Search Bar & Provider Toggle -->
          <div class="mb-8">
            <!-- Provider Selector Tabs -->
            <div class="flex items-center justify-between gap-4 flex-wrap mb-4">
              <div class="flex items-center gap-1.5 p-1 bg-[#12100e] border border-[#2a2a2a] rounded-xl shadow-inner">
                <button
                  onclick={() => setProvider("all")}
                  class="px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 {activeProvider === 'all' ? 'bg-amber-500 text-black shadow-md shadow-amber-500/20' : 'text-zinc-400 hover:text-white'}"
                >
                  <span>🌐</span>
                  <span>All Sources</span>
                </button>
                <button
                  onclick={() => setProvider("apple")}
                  class="px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 {activeProvider === 'apple' ? 'bg-pink-600 text-white shadow-md shadow-pink-600/20' : 'text-zinc-400 hover:text-white'}"
                >
                  <span>🍎</span>
                  <span>Apple Music</span>
                </button>
                <button
                  onclick={() => setProvider("tidal")}
                  class="px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 {activeProvider === 'tidal' ? 'bg-cyan-500 text-black shadow-md shadow-cyan-500/20' : 'text-zinc-400 hover:text-white'}"
                >
                  <span>🌊</span>
                  <span>Tidal</span>
                </button>
              </div>

              <div class="text-xs text-zinc-500 flex items-center gap-2">
                <span>Active Provider:</span>
                <span class="px-2.5 py-1 rounded-lg bg-white/5 border border-white/10 text-zinc-300 font-semibold text-[11px] flex items-center gap-1.5">
                  {#if activeProvider === "apple"}
                    <span class="text-pink-400 font-bold">🍎 Apple Music (ALAC)</span>
                  {:else if activeProvider === "tidal"}
                    <span class="text-cyan-400 font-bold">🌊 Tidal (Hi-Res FLAC)</span>
                  {:else}
                    <span class="text-amber-400 font-bold">🌐 Multi-Source Search</span>
                  {/if}
                </span>
              </div>
            </div>

            <!-- Search Input -->
            <div class="relative flex items-center">
              <span class="absolute left-4 text-zinc-500 text-sm">🔍</span>
              <input
                type="text"
                value={searchQuery}
                oninput={handleSearchInput}
                placeholder="Search artists, albums, playlists, or tracks (e.g. Daft Punk, Synthwave, Get Lucky)..."
                class="w-full bg-[#12100e] border border-[#2a2a2a] rounded-2xl pl-11 pr-10 py-3.5 text-sm text-white placeholder-zinc-600 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-500/20 shadow-lg transition-all"
              />
              {#if searchLoading}
                <div class="absolute right-4 w-4 h-4 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin"></div>
              {:else if searchQuery}
                <button
                  onclick={() => { searchQuery = ""; searchResults = { songs: [], albums: [], artists: [], playlists: [] }; }}
                  class="absolute right-4 text-zinc-500 hover:text-white text-xs font-bold"
                >
                  ✕
                </button>
              {/if}
            </div>

            <!-- Filter Pills -->
            <div class="flex items-center gap-2 mt-4 flex-wrap">
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
                onclick={() => (activeEntityFilter = "playlists")}
                class="px-3 py-1 rounded-lg text-xs font-semibold transition-all flex items-center gap-1 {activeEntityFilter === 'playlists' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40' : 'bg-[#15131a] text-zinc-400 border border-[#262330] hover:text-white'}"
              >
                <span>📑 Playlists ({searchResults.playlists?.length || 0})</span>
              </button>
              <button
                onclick={() => { activeEntityFilter = "genres"; if (catalogGenresList.length === 0) loadGenresAndPlaylists(); }}
                class="px-3 py-1 rounded-lg text-xs font-semibold transition-all flex items-center gap-1 {activeEntityFilter === 'genres' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40' : 'bg-[#15131a] text-zinc-400 border border-[#262330] hover:text-white'}"
              >
                <span>🎸 Genres</span>
              </button>
              <button
                onclick={() => (activeEntityFilter = "songs")}
                class="px-3 py-1 rounded-lg text-xs font-semibold transition-all {activeEntityFilter === 'songs' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40' : 'bg-[#15131a] text-zinc-400 border border-[#262330] hover:text-white'}"
              >
                Tracks ({searchResults.songs?.length || 0})
              </button>
              <button
                onclick={() => (activeEntityFilter = "subscribed")}
                class="px-3 py-1 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 {activeEntityFilter === 'subscribed' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40' : 'bg-[#15131a] text-zinc-400 border border-[#262330] hover:text-white'}"
              >
                <span>★ Followed</span>
                <span class="text-[11px] opacity-80">({subscribedArtists.length})</span>
              </button>

              <div class="ml-auto flex items-center gap-2">
                {#if checkResultMessage}
                  <span class="text-xs text-amber-400 font-medium">{checkResultMessage}</span>
                {/if}
                <button
                  onclick={() => checkReleasesNow()}
                  disabled={checkingReleases}
                  class="px-3 py-1 rounded-lg text-xs font-semibold bg-white/5 hover:bg-white/10 text-zinc-300 border border-white/10 transition-all flex items-center gap-1.5 disabled:opacity-50"
                  title="Check discographies for new releases from all subscribed artists"
                >
                  <span class={checkingReleases ? 'animate-spin' : ''}>⚡</span>
                  <span>{checkingReleases ? 'Checking…' : 'Check New Releases'}</span>
                </button>
              </div>
            </div>
          </div>
        {/if}

        {#if pendingReleases.length > 0}
          <div class="mb-6 p-4 rounded-2xl bg-gradient-to-r from-amber-950/40 via-[#1e1915] to-[#14121a] border border-amber-500/30 flex items-center justify-between gap-4 shadow-lg">
            <div class="flex items-center gap-3">
              <span class="text-2xl">💿</span>
              <div>
                <div class="text-xs font-bold text-amber-400 flex items-center gap-2">
                  <span>New Releases from Subscribed Artists</span>
                  <span class="px-2 py-0.5 rounded-full text-[10px] bg-amber-500/20 text-amber-300 border border-amber-500/40 font-semibold">
                    {pendingReleases.length} {pendingReleases.length === 1 ? 'Release' : 'Releases'}
                  </span>
                </div>
                <div class="text-[11px] text-zinc-400 mt-0.5">
                  New music detected from artists you follow. Ready to download into your library.
                </div>
              </div>
            </div>
            <div class="flex items-center gap-2 flex-shrink-0">
              <button
                onclick={downloadAllPending}
                class="px-3 py-1.5 rounded-xl bg-amber-500 hover:bg-amber-400 text-black text-xs font-bold transition-all shadow flex items-center gap-1.5"
              >
                <span>⚡ Download All ({pendingReleases.length})</span>
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

          {#if activeEntityFilter === "subscribed"}
            <div class="mb-10">
              <div class="flex items-center justify-between mb-4">
                <div class="text-xs font-bold uppercase tracking-wider text-amber-500 flex items-center gap-2">
                  <span>Followed Artists</span>
                  <span class="text-zinc-600 text-[11px] font-normal">({subscribedArtists.length})</span>
                </div>
                <div class="text-xs text-zinc-500">
                  Pear Music monitors discographies and detects new releases automatically.
                </div>
              </div>

              {#if subscribedArtists.length === 0}
                <div class="p-12 text-center rounded-2xl bg-[#14121a] border border-[#23202e]">
                  <div class="text-3xl mb-2">⭐</div>
                  <div class="text-white text-sm font-semibold mb-1">No followed artists yet</div>
                  <div class="text-zinc-500 text-xs max-w-md mx-auto">
                    Search for any artist and click the star button to follow them. Pear Music will quickly check their discography and download or surface new music as soon as it's released!
                  </div>
                </div>
              {:else}
                <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                  {#each subscribedArtists as sub (sub.id)}
                    <div class="p-3.5 rounded-2xl bg-[#14121a] border border-[#23202e] hover:border-amber-500/30 flex flex-col justify-between gap-3 shadow-sm transition-all group">
                      <div class="flex items-center gap-3">
                        <div class="w-12 h-12 min-w-[48px] min-h-[48px] max-w-[48px] max-h-[48px] rounded-full bg-zinc-800 overflow-hidden flex-shrink-0 border border-white/5" style="width: 48px; height: 48px; min-width: 48px; min-height: 48px;">
                          {#if sub.artwork_url}
                            <img src={formatArtwork(sub.artwork_url, 120)} alt={sub.name} width="48" height="48" class="w-12 h-12 min-w-[48px] min-h-[48px] max-w-[48px] max-h-[48px] rounded-full object-cover flex-shrink-0" style="width: 48px; height: 48px;" />
                          {:else}
                            <div class="w-full h-full flex items-center justify-center text-zinc-500 text-sm">👤</div>
                          {/if}
                        </div>
                        <div class="flex-1 min-w-0">
                          <button
                            onclick={() => openArtist(sub.artist_id, sub.service === 'tidal' || sub.artist_id.startsWith('tidal:') ? 'tidal' : 'apple')}
                            class="text-white text-sm font-semibold truncate hover:text-amber-400 transition-colors text-left block w-full"
                          >
                            {sub.name}
                          </button>
                          <div class="text-zinc-500 text-[11px] flex items-center gap-2 mt-0.5">
                            <span>{sub.service === 'apple_music' ? 'Apple Music' : 'Tidal'}</span>
                            <span>•</span>
                            <span>{sub.known_releases_count || 0} tracked</span>
                          </div>
                        </div>
                      </div>

                      <div class="flex items-center justify-between pt-2 border-t border-white/5 text-xs">
                        <label class="flex items-center gap-1.5 cursor-pointer text-[11px] text-zinc-400 hover:text-zinc-200">
                          <input
                            type="checkbox"
                            checked={sub.auto_download}
                            onchange={(e) => updateArtistAutoDownload(sub.artist_id, (e.target as HTMLInputElement).checked)}
                            class="rounded bg-zinc-900 border-zinc-700 text-amber-500 focus:ring-0 focus:ring-offset-0 w-3.5 h-3.5 cursor-pointer"
                          />
                          <span>Auto-download</span>
                        </label>

                        <div class="flex items-center gap-1">
                          <button
                            onclick={() => checkReleasesNow(sub.artist_id)}
                            disabled={checkingReleases}
                            title="Check now for new releases"
                            class="px-2 py-0.5 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white text-[11px] transition-colors disabled:opacity-50"
                          >
                            Check
                          </button>
                          <button
                            onclick={() => toggleArtistSubscription({ id: sub.artist_id, name: sub.name, url: sub.url, artwork_url: sub.artwork_url })}
                            title="Unsubscribe"
                            class="px-2 py-0.5 rounded-lg bg-red-950/20 hover:bg-red-950/40 text-red-400 text-[11px] transition-colors"
                          >
                            Remove
                          </button>
                        </div>
                      </div>
                    </div>
                  {/each}
                </div>
              {/if}
            </div>
          {:else if activeEntityFilter === "genres"}
            <!-- GENRES SHOWCASE HUB -->
            <div class="mb-10">
              <div class="flex items-center justify-between mb-4">
                <div class="text-xs font-bold uppercase tracking-wider text-amber-500 flex items-center gap-2">
                  <span>🎸 Browse Catalog by Genre</span>
                  <span class="text-zinc-600 text-[11px] font-normal">({catalogGenresList.length} Genres)</span>
                </div>
                {#if selectedGenre}
                  <button
                    onclick={() => { selectedGenre = null; genreCharts = null; }}
                    class="px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-xs text-zinc-400 hover:text-white transition-colors"
                  >
                    ← All Genres
                  </button>
                {/if}
              </div>

              <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-8">
                {#each catalogGenresList as g (g.id)}
                  {@const isSelected = selectedGenre?.id === g.id}
                  <button
                    onclick={() => selectGenre(g)}
                    class="p-4 rounded-2xl border text-left transition-all flex items-center gap-3 group {isSelected ? 'border-amber-500 bg-amber-500/15 ring-2 ring-amber-500/20' : 'border-[#23202e] bg-[#14121a] hover:border-amber-500/40 hover:bg-[#1c1924]'}"
                  >
                    <span class="text-2xl flex-shrink-0">{g.icon}</span>
                    <div class="min-w-0">
                      <div class="text-white text-xs font-bold truncate group-hover:text-amber-400 transition-colors">{g.name}</div>
                      <div class="text-[10px] text-zinc-500 mt-0.5">Charts & Playlists</div>
                    </div>
                  </button>
                {/each}
              </div>

              {#if genreLoading}
                <div class="flex flex-col items-center justify-center py-16 gap-3">
                  <div class="w-7 h-7 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin"></div>
                  <div class="text-zinc-500 text-xs">Loading {selectedGenre?.name || "genre"} charts & curated playlists…</div>
                </div>
              {:else if genreError}
                <div class="bg-red-950/30 border border-red-900/50 rounded-2xl p-4 text-red-400 text-xs">
                  {genreError}
                </div>
              {:else if selectedGenre && genreCharts}
                <div class="space-y-8">
                  <!-- Genre Playlists -->
                  {#if genreCharts.playlists && genreCharts.playlists.length > 0}
                    <div>
                      <div class="text-xs font-bold uppercase tracking-wider text-amber-400 mb-3 flex items-center gap-2">
                        <span>{selectedGenre.icon} Featured {selectedGenre.name} Playlists</span>
                        <span class="text-zinc-600 text-[11px] font-normal">({genreCharts.playlists.length})</span>
                      </div>
                      <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                        {#each genreCharts.playlists as pl (pl.id)}
                          <div class="flex items-center justify-between gap-3 p-3 rounded-2xl bg-[#14121a] hover:bg-[#1c1924] border border-[#23202e] hover:border-amber-500/40 transition-all group shadow-sm">
                            <button
                              onclick={() => openPlaylist(pl.id, pl.provider)}
                              class="flex items-center gap-3 flex-1 min-w-0 text-left"
                            >
                              <div class="w-12 h-12 min-w-[48px] min-h-[48px] max-w-[48px] max-h-[48px] rounded-xl bg-zinc-800 overflow-hidden shrink-0 border border-white/5" style="width: 48px; height: 48px; min-width: 48px; min-height: 48px;">
                                {#if pl.artwork_url}
                                  <img src={formatArtwork(pl.artwork_url, 160)} alt={pl.title} width="48" height="48" class="w-12 h-12 min-w-[48px] min-h-[48px] max-w-[48px] max-h-[48px] rounded-xl object-cover shrink-0" style="width: 48px; height: 48px;" />
                                {:else}
                                  <div class="w-full h-full flex items-center justify-center text-zinc-500 text-sm">📑</div>
                                {/if}
                              </div>
                              <div class="flex-1 min-w-0">
                                <div class="text-white text-xs font-bold truncate group-hover:text-amber-400 transition-colors" title={pl.title}>{pl.title}</div>
                                <div class="text-zinc-400 text-[11px] truncate mt-0.5">{pl.curator || "Apple Music"}</div>
                              </div>
                            </button>
                            <button
                              onclick={() => openPlaylist(pl.id, pl.provider)}
                              class="px-2.5 py-1 rounded-lg bg-white/5 hover:bg-amber-500 hover:text-black text-zinc-300 text-[11px] font-semibold transition-colors shrink-0"
                            >
                              Inspect →
                            </button>
                          </div>
                        {/each}
                      </div>
                    </div>
                  {/if}

                  <!-- Genre Top Albums -->
                  {#if genreCharts.albums && genreCharts.albums.length > 0}
                    <div>
                      <div class="text-xs font-bold uppercase tracking-wider text-amber-400 mb-3 flex items-center gap-2">
                        <span>💿 Top {selectedGenre.name} Albums</span>
                        <span class="text-zinc-600 text-[11px] font-normal">({genreCharts.albums.length})</span>
                      </div>
                      <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
                        {#each genreCharts.albums as alb (alb.id)}
                          <div class="group flex flex-col bg-[#14121a] rounded-2xl border border-[#23202e] hover:border-amber-500/40 overflow-hidden transition-all shadow-sm">
                            <button onclick={() => openAlbum(alb.id, alb.provider || 'apple')} class="aspect-square bg-zinc-900 overflow-hidden relative text-left">
                              {#if alb.artwork_url}
                                <img src={formatArtwork(alb.artwork_url, 300)} alt={alb.title} class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
                              {:else}
                                <div class="w-full h-full flex items-center justify-center text-2xl text-zinc-600">💿</div>
                              {/if}
                            </button>
                            <div class="p-3 flex flex-col flex-1">
                              <button onclick={() => openAlbum(alb.id, alb.provider || 'apple')} class="text-left">
                                <div class="text-white text-xs font-bold truncate group-hover:text-amber-400 transition-colors" title={alb.title}>{alb.title}</div>
                                <div class="text-zinc-400 text-[11px] truncate mt-0.5" title={alb.artist}>{alb.artist}</div>
                              </button>
                            </div>
                          </div>
                        {/each}
                      </div>
                    </div>
                  {/if}

                  <!-- Genre Top Songs -->
                  {#if genreCharts.songs && genreCharts.songs.length > 0}
                    <div>
                      <div class="text-xs font-bold uppercase tracking-wider text-amber-400 mb-3 flex items-center gap-2">
                        <span>🎵 Top {selectedGenre.name} Tracks</span>
                        <span class="text-zinc-600 text-[11px] font-normal">({genreCharts.songs.length})</span>
                      </div>
                      <div class="divide-y divide-white/5 bg-[#14121a] rounded-2xl border border-[#23202e] overflow-hidden">
                        {#each genreCharts.songs as s (s.id)}
                          <div class="flex items-center justify-between p-3 hover:bg-white/5 transition-colors gap-3">
                            <div class="w-10 h-10 min-w-[40px] min-h-[40px] max-w-[40px] max-h-[40px] rounded-xl bg-zinc-800 overflow-hidden shrink-0" style="width: 40px; height: 40px; min-width: 40px; min-height: 40px;">
                              {#if s.artwork_url}
                                <img src={formatArtwork(s.artwork_url, 80)} alt={s.title} width="40" height="40" class="w-10 h-10 min-w-[40px] min-h-[40px] max-w-[40px] max-h-[40px] rounded-xl object-cover shrink-0" style="width: 40px; height: 40px;" />
                              {:else}
                                <div class="w-full h-full flex items-center justify-center text-xs text-zinc-500">🎵</div>
                              {/if}
                            </div>
                            <div class="flex-1 min-w-0">
                              <div class="text-white text-xs font-bold truncate">{s.title}</div>
                              <div class="text-zinc-400 text-[11px] truncate mt-0.5">{s.artist} {s.album ? `• ${s.album}` : ""}</div>
                            </div>
                            <div class="flex items-center gap-1.5 shrink-0">
                              <button
                                onclick={() => openAddToPlaylistModal([s])}
                                class="px-2.5 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 text-amber-300 text-xs font-semibold transition-colors"
                                title="Add track to a custom or local playlist"
                              >
                                + Playlist
                              </button>
                              <button
                                onclick={() => downloadSingleTrack(s)}
                                class="px-3 py-1.5 rounded-xl bg-white/5 hover:bg-amber-500 hover:text-black text-zinc-300 text-xs font-semibold transition-colors flex items-center gap-1.5"
                              >
                                <span>↓</span>
                                <span>Download</span>
                              </button>
                            </div>
                          </div>
                        {/each}
                      </div>
                    </div>
                  {/if}
                </div>
              {/if}
            </div>
          {:else if !searchQuery.trim()}
            <div class="flex flex-col items-center justify-center py-12 text-center text-zinc-600">
              <div class="text-4xl mb-3 opacity-60">💿</div>
              <div class="text-white text-base font-semibold">Explore Lossless Music Catalog</div>
              <div class="text-xs text-zinc-500 mt-1 max-w-md mb-8">
                Search Apple Music and Tidal for artists, albums, curated playlists, or genres to download lossless tracks or build custom local playlists.
              </div>

              {#if catalogGenresList.length > 0}
                <div class="w-full max-w-4xl text-left">
                  <div class="text-xs font-bold uppercase tracking-wider text-amber-500 mb-3 flex items-center gap-2">
                    <span>🎸 Quick Genre Discovery</span>
                  </div>
                  <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2.5">
                    {#each catalogGenresList as g (g.id)}
                      <button
                        onclick={() => { activeEntityFilter = "genres"; selectGenre(g); }}
                        class="p-3 rounded-2xl border border-[#23202e] bg-[#14121a] hover:border-amber-500/40 hover:bg-[#1c1924] text-left transition-all flex items-center gap-2.5 group"
                      >
                        <span class="text-xl shrink-0">{g.icon}</span>
                        <span class="text-white text-xs font-semibold truncate group-hover:text-amber-400 transition-colors">{g.name}</span>
                      </button>
                    {/each}
                  </div>
                </div>
              {/if}
            </div>
          {:else if searchResults.artists.length === 0 && searchResults.albums.length === 0 && searchResults.songs.length === 0 && (!searchResults.playlists || searchResults.playlists.length === 0) && !searchLoading}
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
                    {@const isSub = isArtistSubscribed(art.id)}
                    <div
                      class="flex items-center gap-3 p-3 rounded-2xl bg-[#14121a] hover:bg-[#1c1924] border border-[#23202e] hover:border-amber-500/40 text-left transition-all group shadow-sm"
                    >
                      <button
                        onclick={() => openArtist(art.id, art.provider)}
                        class="flex items-center gap-3 flex-1 min-w-0 text-left"
                      >
                        <div class="w-12 h-12 min-w-[48px] min-h-[48px] max-w-[48px] max-h-[48px] rounded-full bg-zinc-800 overflow-hidden flex-shrink-0 border border-white/5 relative" style="width: 48px; height: 48px; min-width: 48px; min-height: 48px;">
                          {#if art.artwork_url}
                            <img src={formatArtwork(art.artwork_url, 120)} alt={art.name} width="48" height="48" class="w-12 h-12 min-w-[48px] min-h-[48px] max-w-[48px] max-h-[48px] rounded-full object-cover flex-shrink-0" style="width: 48px; height: 48px;" />
                          {:else}
                            <div class="w-full h-full flex items-center justify-center text-zinc-500 text-sm">👤</div>
                          {/if}
                        </div>
                        <div class="flex-1 min-w-0">
                          <div class="flex items-center gap-2">
                            <span class="text-white text-sm font-semibold truncate group-hover:text-amber-400 transition-colors">{art.name}</span>
                            <span class="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider {art.provider === 'tidal' ? 'bg-cyan-950/80 text-cyan-400 border border-cyan-800/40' : 'bg-pink-950/80 text-pink-400 border border-pink-800/40'}">
                              {art.provider === 'tidal' ? '🌊 Tidal' : '🍎 Apple'}
                            </span>
                          </div>
                          <div class="text-zinc-500 text-xs truncate mt-0.5">
                            {art.genre_names?.join(", ") || art.genres?.join(", ") || "Artist"}
                          </div>
                        </div>
                      </button>

                      <div class="flex items-center gap-1 flex-shrink-0">
                        <button
                          onclick={(e) => { e.stopPropagation(); toggleArtistSubscription(art); }}
                          disabled={subscribingArtistId === art.id}
                          title={isSub ? "Followed (Click to unfollow)" : "Follow artist for new releases"}
                          class="p-1.5 rounded-xl transition-all {isSub ? 'text-amber-400 bg-amber-500/10 hover:bg-amber-500/20' : 'text-zinc-600 hover:text-zinc-300 hover:bg-white/5'}"
                        >
                          {#if subscribingArtistId === art.id}
                            <span class="inline-block w-4 h-4 border-2 border-amber-500/40 border-t-amber-400 rounded-full animate-spin"></span>
                          {:else}
                            <span class="text-sm">{isSub ? "★" : "☆"}</span>
                          {/if}
                        </button>
                        <button
                          onclick={() => openArtist(art.id, art.provider)}
                          class="text-zinc-600 group-hover:text-amber-400 group-hover:translate-x-0.5 transition-all text-sm font-bold px-1"
                        >
                          →
                        </button>
                      </div>
                    </div>
                  {/each}
                </div>
              </div>
            {/if}

            <!-- PLAYLISTS SECTION -->
            {#if (activeEntityFilter === "all" || activeEntityFilter === "playlists") && searchResults.playlists && searchResults.playlists.length > 0}
              <div class="mb-10">
                <div class="text-xs font-bold uppercase tracking-wider text-amber-500 mb-3 flex items-center gap-2">
                  <span>📑 Curated Playlists</span>
                  <span class="text-zinc-600 text-[11px] font-normal">({searchResults.playlists.length})</span>
                </div>
                <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                  {#each searchResults.playlists as pl (pl.id)}
                    <div class="flex items-center justify-between gap-3 p-3 rounded-2xl bg-[#14121a] hover:bg-[#1c1924] border border-[#23202e] hover:border-amber-500/40 transition-all group shadow-sm">
                      <button
                        onclick={() => openPlaylist(pl.id, pl.provider)}
                        class="flex items-center gap-3 flex-1 min-w-0 text-left"
                      >
                        <div class="w-12 h-12 min-w-[48px] min-h-[48px] max-w-[48px] max-h-[48px] rounded-xl bg-zinc-800 overflow-hidden shrink-0 border border-white/5" style="width: 48px; height: 48px; min-width: 48px; min-height: 48px;">
                          {#if pl.artwork_url}
                            <img src={formatArtwork(pl.artwork_url, 160)} alt={pl.title} width="48" height="48" class="w-12 h-12 min-w-[48px] min-h-[48px] max-w-[48px] max-h-[48px] rounded-xl object-cover shrink-0" style="width: 48px; height: 48px;" />
                          {:else}
                            <div class="w-full h-full flex items-center justify-center text-zinc-500 text-sm">📑</div>
                          {/if}
                        </div>
                        <div class="flex-1 min-w-0">
                          <div class="flex items-center gap-2">
                            <span class="text-white text-xs font-bold truncate group-hover:text-amber-400 transition-colors" title={pl.title}>{pl.title}</span>
                            <span class="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider shrink-0 {pl.provider === 'tidal' ? 'bg-cyan-950/80 text-cyan-400 border border-cyan-800/40' : 'bg-pink-950/80 text-pink-400 border border-pink-800/40'}">
                              {pl.provider === 'tidal' ? '🌊 Tidal' : '🍎 Apple'}
                            </span>
                          </div>
                          <div class="text-zinc-500 text-[11px] truncate mt-0.5">
                            {pl.curator || "Curated Playlist"}{pl.track_count ? ` • ${pl.track_count} tracks` : ""}
                          </div>
                        </div>
                      </button>
                      <button
                        onclick={() => openPlaylist(pl.id, pl.provider)}
                        class="px-2.5 py-1 rounded-lg bg-white/5 hover:bg-amber-500 hover:text-black text-zinc-300 text-[11px] font-semibold transition-colors shrink-0"
                      >
                        Inspect →
                      </button>
                    </div>
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
                        onclick={() => openAlbum(alb.id, alb.provider)}
                        class="aspect-square bg-zinc-900 overflow-hidden relative text-left"
                      >
                        {#if alb.artwork_url}
                          <img src={formatArtwork(alb.artwork_url, 300)} alt={alb.title} class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
                        {:else}
                          <div class="w-full h-full flex items-center justify-center text-2xl text-zinc-600">💿</div>
                        {/if}
                        <div class="absolute top-2.5 right-2.5 px-1.5 py-0.5 rounded text-[9px] font-bold backdrop-blur-md {alb.provider === 'tidal' ? 'bg-cyan-950/80 text-cyan-300 border border-cyan-500/30' : 'bg-pink-950/80 text-pink-300 border border-pink-500/30'}">
                          {alb.provider === 'tidal' ? '🌊 Tidal' : (alb.is_single ? 'SINGLE' : '🍎 Apple')}
                        </div>
                        <div class="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                          <span class="px-3 py-1 rounded-full bg-amber-500 text-black text-xs font-bold shadow-lg">Inspect Tracks</span>
                        </div>
                      </button>
                      <div class="p-3 flex flex-col flex-1">
                        <button onclick={() => openAlbum(alb.id, alb.provider)} class="text-left">
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
                      <div class="w-10 h-10 min-w-[40px] min-h-[40px] max-w-[40px] max-h-[40px] rounded-xl bg-zinc-800 overflow-hidden flex-shrink-0 relative" style="width: 40px; height: 40px; min-width: 40px; min-height: 40px;">
                        {#if s.artwork_url}
                          <img src={formatArtwork(s.artwork_url, 80)} alt={s.title} width="40" height="40" class="w-10 h-10 min-w-[40px] min-h-[40px] max-w-[40px] max-h-[40px] rounded-xl object-cover flex-shrink-0" style="width: 40px; height: 40px;" />
                        {:else}
                          <div class="w-full h-full flex items-center justify-center text-xs text-zinc-500">🎵</div>
                        {/if}
                      </div>
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2">
                          <span class="text-white text-xs font-bold truncate">{s.title}</span>
                          <span class="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider {s.provider === 'tidal' ? 'bg-cyan-950/80 text-cyan-400 border border-cyan-800/40' : 'bg-pink-950/80 text-pink-400 border border-pink-800/40'}">
                            {s.provider === 'tidal' ? '🌊 Tidal' : '🍎 Apple'}
                          </span>
                        </div>
                        <div class="text-zinc-400 text-[11px] truncate mt-0.5">
                          {#if s.artist && s.album}
                            {s.artist} <span class="text-zinc-600">•</span> {s.album}
                          {:else}
                            {s.artist || s.album || "Track"}
                          {/if}
                        </div>
                      </div>
                      <div class="flex items-center gap-1.5 flex-shrink-0">
                        <button
                          onclick={() => openAddToPlaylistModal([s])}
                          class="px-2.5 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 text-amber-300 text-xs font-semibold transition-colors"
                          title="Add track to a custom or local playlist"
                        >
                          + Playlist
                        </button>
                        <button
                          onclick={() => downloadSingleTrack(s)}
                          class="px-3 py-1.5 rounded-xl bg-white/5 hover:bg-amber-500 hover:text-black text-zinc-300 text-xs font-semibold transition-colors flex items-center gap-1.5"
                        >
                          <span>↓</span>
                          <span>Download</span>
                        </button>
                      </div>
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
            {@const sub = getSubscribedArtist(selectedArtist.id)}
            <div class="p-6 rounded-3xl bg-gradient-to-r from-[#171420] via-[#14121a] to-[#121018] border border-[#282438] flex items-center justify-between gap-6 mb-8 shadow-xl">
              <div class="flex items-center gap-5">
                <div class="w-20 h-20 min-w-[80px] min-h-[80px] max-w-[80px] max-h-[80px] rounded-full bg-zinc-800 overflow-hidden flex-shrink-0 border-2 border-amber-500/30 shadow-lg" style="width: 80px; height: 80px; min-width: 80px; min-height: 80px;">
                  {#if selectedArtist.artwork_url}
                    <img src={formatArtwork(selectedArtist.artwork_url, 200)} alt={selectedArtist.name} width="80" height="80" class="w-20 h-20 min-w-[80px] min-h-[80px] max-w-[80px] max-h-[80px] rounded-full object-cover flex-shrink-0" style="width: 80px; height: 80px;" />
                  {:else}
                    <div class="w-full h-full flex items-center justify-center text-2xl text-zinc-500">👤</div>
                  {/if}
                </div>
                <div>
                  <div class="flex items-center gap-2 mb-1">
                    <span class="text-[10px] uppercase tracking-widest text-amber-400 font-bold">Artist Discography</span>
                    <span class="px-2 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider {selectedArtist.provider === 'tidal' ? 'bg-cyan-950/80 text-cyan-400 border border-cyan-800/50' : 'bg-pink-950/80 text-pink-400 border border-pink-800/50'}">
                      {selectedArtist.provider === 'tidal' ? '🌊 Tidal' : '🍎 Apple Music'}
                    </span>
                    {#if sub}
                      <span class="px-2 py-0.5 rounded-full text-[9px] bg-amber-500/20 text-amber-300 border border-amber-500/40 font-semibold">
                        ★ Subscribed
                      </span>
                    {/if}
                  </div>
                  <h1 class="text-white text-2xl font-bold">{selectedArtist.name}</h1>
                  <div class="flex items-center gap-3 text-xs text-zinc-400 mt-1">
                    <span>{selectedArtist.genres?.join(", ") || selectedArtist.genre_names?.join(", ") || "Artist"}</span>
                    <span>•</span>
                    <span class="text-amber-400 font-semibold">{selectedArtist.albums?.length || 0} Total Releases</span>
                  </div>
                </div>
              </div>

              <!-- Quick Selection Actions & Subscription Controls -->
              <div class="flex items-center gap-2 flex-wrap justify-end">
                {#if sub}
                  <div class="flex items-center gap-1.5 p-1 rounded-xl bg-amber-500/10 border border-amber-500/30">
                    <button
                      onclick={() => toggleArtistSubscription({ id: selectedArtist.id, name: selectedArtist.name, url: selectedArtist.url, artwork_url: selectedArtist.artwork_url })}
                      class="px-2.5 py-1 rounded-lg text-xs font-semibold text-amber-300 hover:text-white transition-colors"
                      title="Click to unsubscribe"
                    >
                      ★ Subscribed
                    </button>
                    <label class="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-black/40 text-[11px] text-zinc-300 cursor-pointer" title="Auto-download new music directly or notify first">
                      <input
                        type="checkbox"
                        checked={sub.auto_download}
                        onchange={(e) => updateArtistAutoDownload(sub.artist_id, (e.target as HTMLInputElement).checked)}
                        class="rounded bg-zinc-900 border-zinc-700 text-amber-500 focus:ring-0 focus:ring-offset-0 w-3 h-3 cursor-pointer"
                      />
                      <span>Auto-DL</span>
                    </label>
                  </div>
                {:else}
                  <button
                    onclick={() => toggleArtistSubscription({ id: selectedArtist.id, name: selectedArtist.name, url: selectedArtist.url, artwork_url: selectedArtist.artwork_url })}
                    disabled={subscribingArtistId === selectedArtist.id}
                    class="px-3 py-1.5 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-xs font-semibold text-amber-300 transition-all flex items-center gap-1.5"
                  >
                    <span>{subscribingArtistId === selectedArtist.id ? 'Subscribing…' : '☆ Subscribe'}</span>
                  </button>
                {/if}

                <div class="h-4 w-px bg-white/10 mx-1"></div>

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
                    onclick={() => openAlbum(alb.id, alb.provider || selectedArtist?.provider || (alb.id.startsWith('tidal:') ? 'tidal' : 'apple'))}
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
                    <button onclick={() => openAlbum(alb.id, alb.provider || selectedArtist?.provider || (alb.id.startsWith('tidal:') ? 'tidal' : 'apple'))} class="text-left">
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
                        onclick={() => openAlbum(alb.id, alb.provider || selectedArtist?.provider || (alb.id.startsWith('tidal:') ? 'tidal' : 'apple'))}
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
                  <div class="flex items-center gap-2 mb-1">
                    <span class="text-[10px] uppercase tracking-widest text-amber-400 font-bold">
                      {selectedAlbum.is_single ? "Single / EP" : "Album"}
                    </span>
                    <span class="px-2 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider {selectedAlbum.provider === 'tidal' ? 'bg-cyan-950/80 text-cyan-400 border border-cyan-800/50' : 'bg-pink-950/80 text-pink-400 border border-pink-800/50'}">
                      {selectedAlbum.provider === 'tidal' ? '🌊 Tidal Lossless' : '🍎 Apple Music ALAC'}
                    </span>
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

              <!-- Download Album & Add to Playlist CTA -->
              <div class="flex items-center gap-2.5 flex-wrap w-full md:w-auto">
                {#if selectedAlbum.tracks && selectedAlbum.tracks.length > 0}
                  <button
                    onclick={() => openAddToPlaylistModal(selectedAlbum?.tracks || [], selectedAlbum?.title, `${selectedAlbum?.artist} — ${selectedAlbum?.title}`, selectedAlbum?.artwork_url)}
                    class="w-full md:w-auto px-4 py-3 rounded-2xl font-bold text-xs text-amber-300 bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/30 transition-all flex items-center justify-center gap-2"
                  >
                    <span>+ Add Album to Playlist</span>
                  </button>
                {/if}
                <button
                  onclick={downloadCurrentAlbum}
                  class="w-full md:w-auto px-6 py-3 rounded-2xl font-bold text-xs text-black transition-all hover:bg-amber-400 flex items-center justify-center gap-2 shadow-xl shadow-amber-500/20"
                  style="background:var(--accent);"
                >
                  <span>↓ Download Full Album ({selectedAlbum.provider === 'tidal' ? 'FLAC' : format})</span>
                </button>
              </div>
            </div>

            <!-- Tracklist Table -->
            <div class="bg-[#14121a] rounded-2xl border border-[#23202e] overflow-hidden mb-12">
              <div class="px-5 py-3 border-b border-white/5 text-[11px] font-bold text-zinc-500 uppercase tracking-wider flex items-center">
                <span class="w-8 text-center">#</span>
                <span class="flex-1">Title</span>
                <span class="w-24 text-right pr-4">Duration</span>
                <span class="w-44 text-right">Action</span>
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
                    <div class="w-44 text-right flex items-center justify-end gap-1.5">
                      <button
                        onclick={() => openAddToPlaylistModal([trk])}
                        class="px-2 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-amber-300 text-[11px] font-semibold transition-colors"
                        title="Add track to custom/local playlist"
                      >
                        + Playlist
                      </button>
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

        <!-- 1D. FULL PLAYLIST INSPECTOR SUBVIEW -->
        {#if searchSubView === "playlist"}
          {#if playlistLoading}
            <div class="flex flex-col items-center justify-center py-24 gap-3">
              <div class="w-8 h-8 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin"></div>
              <div class="text-zinc-500 text-xs font-medium">Loading curated playlist & checking local library…</div>
            </div>
          {:else if playlistError}
            <div class="bg-red-950/30 border border-red-900/50 rounded-2xl p-5 text-red-400 text-sm">
              {playlistError}
            </div>
          {:else if selectedPlaylist}
            <!-- Playlist Hero Header -->
            <div class="p-6 rounded-3xl bg-gradient-to-r from-[#171420] via-[#14121a] to-[#121018] border border-[#282438] flex flex-col md:flex-row items-start md:items-center justify-between gap-6 mb-6 shadow-xl">
              <div class="flex items-center gap-6 min-w-0">
                <div class="w-28 h-28 min-w-[112px] min-h-[112px] max-w-[112px] max-h-[112px] rounded-2xl bg-zinc-800 overflow-hidden shrink-0 border border-white/10 shadow-lg" style="width: 112px; height: 112px; min-width: 112px; min-height: 112px;">
                  {#if selectedPlaylist.artwork_url}
                    <img src={formatArtwork(selectedPlaylist.artwork_url, 400)} alt={selectedPlaylist.title} width="112" height="112" class="w-28 h-28 min-w-[112px] min-h-[112px] max-w-[112px] max-h-[112px] object-cover shrink-0" style="width: 112px; height: 112px;" />
                  {:else}
                    <div class="w-full h-full flex items-center justify-center text-3xl text-zinc-500">📑</div>
                  {/if}
                </div>
                <div class="min-w-0">
                  <div class="flex items-center gap-2 mb-1 flex-wrap">
                    <span class="text-[10px] uppercase tracking-widest text-amber-400 font-bold">Curated Playlist</span>
                    <span class="px-2 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider {selectedPlaylist.provider === 'tidal' ? 'bg-cyan-950/80 text-cyan-400 border border-cyan-800/50' : 'bg-pink-950/80 text-pink-400 border border-pink-800/50'}">
                      {selectedPlaylist.provider === 'tidal' ? '🌊 Tidal Lossless' : '🍎 Apple Music ALAC'}
                    </span>
                  </div>
                  <h1 class="text-white text-2xl font-bold truncate" title={selectedPlaylist.title}>{selectedPlaylist.title}</h1>
                  <div class="text-zinc-300 text-sm font-semibold mt-0.5">{selectedPlaylist.curator || "Curated"}</div>
                  {#if selectedPlaylist.description}
                    <p class="text-zinc-400 text-xs mt-1.5 line-clamp-2 max-w-xl">{selectedPlaylist.description}</p>
                  {/if}
                  <div class="flex items-center gap-3 text-xs text-zinc-500 mt-2 flex-wrap">
                    <span>{selectedPlaylist.tracks?.length || selectedPlaylist.track_count} Tracks</span>
                    {#if selectedPlaylist.tracks}
                      {@const inLibCount = selectedPlaylist.tracks.filter(t => t.in_library).length}
                      {#if inLibCount > 0}
                        <span>•</span>
                        <span class="text-emerald-400 font-semibold">✓ {inLibCount} already in library</span>
                      {/if}
                    {/if}
                  </div>
                </div>
              </div>

              <!-- Playlist Primary CTAs -->
              <div class="flex flex-col sm:flex-row items-stretch sm:items-center gap-2.5 w-full md:w-auto shrink-0">
                <button
                  onclick={() => {
                    const chosen = (selectedPlaylist?.tracks || []).filter((t) => selectedPlaylistTrackIds.has(t.id));
                    openAddToPlaylistModal(
                      chosen.length > 0 ? chosen : (selectedPlaylist?.tracks || []),
                      selectedPlaylist?.title,
                      selectedPlaylist?.description || `Curated by ${selectedPlaylist?.curator || 'Catalog'}`,
                      selectedPlaylist?.artwork_url,
                    );
                  }}
                  class="px-4 py-3 rounded-2xl font-bold text-xs text-amber-300 bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/30 transition-all flex items-center justify-center gap-2"
                >
                  <span>+ Save / Add to Custom Playlist ({selectedPlaylistTrackIds.size || selectedPlaylist.tracks?.length || 0})</span>
                </button>
                <button
                  onclick={downloadSelectedPlaylistTracks}
                  disabled={selectedPlaylistTrackIds.size === 0}
                  class="px-5 py-3 rounded-2xl font-bold text-xs text-black transition-all hover:bg-amber-400 disabled:opacity-50 flex items-center justify-center gap-2 shadow-xl shadow-amber-500/20"
                  style="background:var(--accent);"
                >
                  <span>↓ Download Selected Lossless ({selectedPlaylistTrackIds.size})</span>
                </button>
              </div>
            </div>

            <!-- Selection Controls Bar -->
            <div class="flex items-center justify-between mb-3 px-1">
              <div class="flex items-center gap-2">
                <button
                  onclick={selectAllPlaylistTracks}
                  class="px-3 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-xs font-semibold text-zinc-300 transition-colors"
                >
                  Select All ({selectedPlaylist.tracks?.length || 0})
                </button>
                <button
                  onclick={deselectAllPlaylistTracks}
                  class="px-3 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-xs font-semibold text-zinc-500 hover:text-zinc-300 transition-colors"
                >
                  Deselect All
                </button>
              </div>
              <div class="text-xs text-zinc-500">
                {selectedPlaylistTrackIds.size} of {selectedPlaylist.tracks?.length || 0} tracks selected
              </div>
            </div>

            <!-- Playlist Tracklist Table -->
            <div class="bg-[#14121a] rounded-2xl border border-[#23202e] overflow-hidden mb-12">
              <div class="px-5 py-3 border-b border-white/5 text-[11px] font-bold text-zinc-500 uppercase tracking-wider flex items-center gap-3">
                <span class="w-5 text-center">✓</span>
                <span class="w-8 text-center">#</span>
                <span class="flex-1">Track / Artist / Album</span>
                <span class="w-24 text-right">Status</span>
                <span class="w-20 text-right">Duration</span>
                <span class="w-40 text-right">Action</span>
              </div>
              <div class="divide-y divide-white/5">
                {#each (selectedPlaylist.tracks || []) as trk, idx (trk.id)}
                  {@const isChecked = selectedPlaylistTrackIds.has(trk.id)}
                  <div class="px-5 py-2.5 hover:bg-white/5 transition-colors flex items-center gap-3 text-xs group">
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onchange={() => togglePlaylistTrackSelection(trk.id)}
                      class="w-4 h-4 rounded text-amber-500 accent-amber-500 cursor-pointer shrink-0"
                    />
                    <span class="w-8 text-center text-zinc-500 font-mono font-medium shrink-0">{trk.track_number || idx + 1}</span>
                    <div class="w-10 h-10 min-w-[40px] min-h-[40px] max-w-[40px] max-h-[40px] rounded-lg bg-zinc-800 overflow-hidden shrink-0 border border-white/5" style="width: 40px; height: 40px; min-width: 40px; min-height: 40px;">
                      {#if trk.artwork_url}
                        <img src={formatArtwork(trk.artwork_url, 80)} alt={trk.title} width="40" height="40" class="w-10 h-10 min-w-[40px] min-h-[40px] max-w-[40px] max-h-[40px] object-cover shrink-0" style="width: 40px; height: 40px;" />
                      {:else}
                        <div class="w-full h-full flex items-center justify-center text-xs text-zinc-500">🎵</div>
                      {/if}
                    </div>
                    <div class="flex-1 min-w-0 pr-2">
                      <div class="text-white font-semibold truncate group-hover:text-amber-400 transition-colors">{trk.title}</div>
                      <div class="text-zinc-500 text-[11px] truncate mt-0.5">
                        {trk.artist}{trk.album ? ` • ${trk.album}` : ""}
                      </div>
                    </div>
                    <div class="w-24 text-right shrink-0">
                      {#if trk.in_library}
                        <span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-950/80 text-emerald-400 border border-emerald-500/30">
                          ✓ In Library
                        </span>
                      {:else}
                        <span class="text-[10px] text-zinc-600">Catalog</span>
                      {/if}
                    </div>
                    <span class="w-20 text-right text-zinc-500 font-mono shrink-0">{formatDuration(trk.duration_ms)}</span>
                    <div class="w-40 text-right flex items-center justify-end gap-1.5 shrink-0">
                      <button
                        onclick={() => openAddToPlaylistModal([trk])}
                        class="px-2 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-amber-300 text-[11px] font-semibold transition-colors"
                        title="Add track to custom/local playlist"
                      >
                        + Playlist
                      </button>
                      <button
                        onclick={() => downloadSingleTrack(trk)}
                        class="px-2.5 py-1 rounded-lg bg-white/5 hover:bg-amber-500 hover:text-black text-zinc-400 text-[11px] font-semibold transition-colors inline-flex items-center gap-1"
                      >
                        <span>↓</span>
                        <span>Rip</span>
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

  <!-- ADD TO CUSTOM / LOCAL PLAYLIST MODAL -->
  {#if showAddToPlaylistModal}
    <div
      class="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
    >
      <div class="w-full max-w-md rounded-3xl bg-[#14121a] border border-amber-500/30 shadow-2xl p-6 space-y-5">
        <div class="flex items-start justify-between gap-4">
          <div>
            <div class="text-[10px] uppercase tracking-widest text-amber-400 font-bold">Custom Playlist Curation</div>
            <h3 class="text-white text-lg font-bold mt-0.5">
              Add {modalTargetTracks.length} {modalTargetTracks.length === 1 ? "Track" : "Tracks"} to Playlist
            </h3>
            <p class="text-zinc-500 text-xs mt-1">
              Build a custom local M3U8 / Navidrome playlist without needing an Apple Music playlist URL.
            </p>
          </div>
          <button
            onclick={() => { showAddToPlaylistModal = false; }}
            class="text-zinc-500 hover:text-white text-sm font-bold px-2 py-1"
          >
            ✕
          </button>
        </div>

        <!-- Mode Selector -->
        <div class="grid grid-cols-2 gap-2 p-1 rounded-xl bg-[#0d0c12] border border-white/5">
          <button
            type="button"
            onclick={() => (modalDestinationMode = "new")}
            class="py-2 rounded-lg text-xs font-bold transition-colors {modalDestinationMode === 'new' ? 'bg-amber-500 text-black' : 'text-zinc-400 hover:text-white'}"
          >
            + Create New Playlist
          </button>
          <button
            type="button"
            onclick={() => (modalDestinationMode = "existing")}
            disabled={localPlaylists.length === 0}
            class="py-2 rounded-lg text-xs font-bold transition-colors disabled:opacity-40 {modalDestinationMode === 'existing' ? 'bg-amber-500 text-black' : 'text-zinc-400 hover:text-white'}"
          >
            Existing Playlist ({localPlaylists.length})
          </button>
        </div>

        {#if modalDestinationMode === "new"}
          <div class="space-y-3">
            <div>
              <label for="new-pl-name" class="block text-[10px] uppercase tracking-wider text-zinc-400 font-semibold mb-1">
                Playlist Name
              </label>
              <input
                id="new-pl-name"
                bind:value={modalNewPlaylistName}
                placeholder="e.g. Late Night Synthwave"
                class="w-full bg-[#0d0c12] border border-[#2a2a2a] focus:border-amber-500 rounded-xl px-3.5 py-2.5 text-xs text-white outline-none"
              />
            </div>
            <div>
              <label for="new-pl-desc" class="block text-[10px] uppercase tracking-wider text-zinc-400 font-semibold mb-1">
                Description (Optional)
              </label>
              <input
                id="new-pl-desc"
                bind:value={modalNewPlaylistDescription}
                placeholder="Custom local playlist synced to M3U8 & Navidrome"
                class="w-full bg-[#0d0c12] border border-[#2a2a2a] focus:border-amber-500 rounded-xl px-3.5 py-2 text-xs text-white outline-none"
              />
            </div>
          </div>
        {:else}
          <div>
            <label for="existing-pl-select" class="block text-[10px] uppercase tracking-wider text-zinc-400 font-semibold mb-1">
              Select Destination Playlist
            </label>
            <select
              id="existing-pl-select"
              bind:value={modalSelectedPlaylistName}
              class="w-full bg-[#0d0c12] border border-[#2a2a2a] focus:border-amber-500 rounded-xl px-3.5 py-2.5 text-xs text-white outline-none"
            >
              {#each localPlaylists as pl (pl.name)}
                <option value={pl.name}>
                  {pl.name} {pl.is_custom ? "(Custom)" : ""}
                </option>
              {/each}
            </select>
          </div>
        {/if}

        <!-- Auto-download missing toggle -->
        <label class="flex items-start gap-2.5 p-3 rounded-xl bg-black/40 border border-white/5 cursor-pointer">
          <input
            type="checkbox"
            bind:checked={modalDownloadMissing}
            class="mt-0.5 rounded bg-zinc-900 border-zinc-700 text-amber-500 accent-amber-500 cursor-pointer"
          />
          <div class="text-xs">
            <div class="text-white font-semibold">Auto-download missing tracks in lossless ({format})</div>
            <div class="text-zinc-500 text-[11px] mt-0.5">
              Tracks already in your library are linked immediately. Missing tracks are queued in the background and automatically added to the playlist &amp; M3U8 when finished.
            </div>
          </div>
        </label>

        {#if modalError}
          <div class="p-3 rounded-xl bg-red-950/40 border border-red-800/50 text-red-300 text-xs">
            {modalError}
          </div>
        {/if}

        {#if modalFeedback}
          <div class="p-3 rounded-xl bg-emerald-950/40 border border-emerald-800/50 text-emerald-300 text-xs font-semibold">
            {modalFeedback}
          </div>
        {/if}

        <div class="flex items-center justify-end gap-2.5 pt-2">
          <button
            type="button"
            onclick={() => { showAddToPlaylistModal = false; }}
            class="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white text-xs font-semibold transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onclick={submitAddToPlaylist}
            disabled={modalSubmitting}
            class="px-5 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-black text-xs font-bold transition-colors disabled:opacity-50"
          >
            {modalSubmitting ? "Saving…" : "Save to Playlist"}
          </button>
        </div>
      </div>
    </div>
  {/if}
</div>
