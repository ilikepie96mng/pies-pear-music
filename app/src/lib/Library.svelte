<script lang="ts">
  import { onMount } from "svelte";
  import {
    api,
    type LibraryTrack,
    type LibraryStats,
    type LibraryAuditReport,
    type LibraryIntegrityReport,
    type LibraryDuplicatesReport,
    type DuplicateGroup,
    type DuplicateTrackItem,
    type LibraryRepairResult,
    type SmartPlaylist,
  } from "../api";
  import LyricsModal from "./LyricsModal.svelte";
  import DapExportModal from "./DapExportModal.svelte";
  import VirtualTrackTable from "./VirtualTrackTable.svelte";
  import PlaylistImportModal from "./PlaylistImportModal.svelte";
  import SmartPlaylistModal from "./SmartPlaylistModal.svelte";
  import BatchTagModal from "./BatchTagModal.svelte";
  import { notifyIntegrityCompleted } from "./notifications";

  interface Props {
    onselectPlaylist?: (name: string) => void;
    onstartSync?: (name: string) => void;
  }

  let { onselectPlaylist, onstartSync }: Props = $props();

  type Tab = "tracks" | "albums" | "artists" | "smart" | "health";
  let activeTab = $state<Tab>("tracks");

  // State
  let loading = $state(true);
  let error = $state<string | null>(null);
  let tracks = $state<LibraryTrack[]>([]);
  let stats = $state<LibraryStats | null>(null);
  let smartPlaylists = $state<SmartPlaylist[]>([]);
  let selectedSmartPlaylist = $state<SmartPlaylist | null>(null);
  let smartPlaylistTracks = $state<LibraryTrack[]>([]);
  let smartLoading = $state(false);

  // Multi-Selection for Batch Operations
  let selectedTrackIds = $state<Set<string>>(new Set());
  let lastSelectedTrackId = $state<string | null>(null);
  let showBatchTagModal = $state(false);
  let batchTagCoverFocus = $state(false);

  // Search & Filters
  let searchQuery = $state("");
  let selectedPlaylistFilter = $state<string>("all");
  let selectedFormatFilter = $state<string>("all");
  let selectedLyricsFilter = $state<string>("all");
  let selectedStatusFilter = $state<string>("all");
  type SortKey = "downloaded_at" | "title" | "artist" | "album" | "file_size";
  let sortKey = $state<SortKey>("downloaded_at");
  let sortAsc = $state(false);

  // Modals
  let activeLyricsTrack = $state<LibraryTrack | null>(null);
  let dapExportPlaylist = $state<string | null>(null);
  let dapExportTrackCount = $state<number>(0);
  let showPlaylistImportModal = $state(false);
  let showSmartPlaylistModal = $state(false);
  let editingSmartPlaylist = $state<SmartPlaylist | null>(null);

  // Health Audit & Repair State
  let auditLoading = $state(false);
  let auditReport = $state<LibraryAuditReport | null>(null);
  let auditError = $state<string | null>(null);

  let integrityLoading = $state(false);
  let integrityReport = $state<LibraryIntegrityReport | null>(null);
  let integrityError = $state<string | null>(null);

  // Duplicate Songs & Sweep State
  let duplicatesLoading = $state(false);
  let duplicatesReport = $state<LibraryDuplicatesReport | null>(null);
  let duplicatesError = $state<string | null>(null);
  let sweepLoading = $state(false);
  let sweepCriteria = $state("recommended"); // "recommended" | "album_over_single" | "highest_quality" | "oldest" | "newest"
  let sweepDeleteFiles = $state(true);
  let sweepRemapPlaylists = $state(true);
  let expandedDuplicateGroups = $state<Record<string, boolean>>({});

  let repairLoading = $state(false);
  let repairMessage = $state<{ type: "success" | "error"; text: string } | null>(null);

  function formatBytes(bytes: number): string {
    if (!bytes || bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  }

  function thumbUrl(url: string | null | undefined, size: string): string {
    if (!url) return "";
    return url.replace("{w}x{h}", size);
  }

  async function loadLibraryData() {
    loading = true;
    error = null;
    try {
      const [tracksData, statsData, smartData] = await Promise.all([
        api.allLibraryTracks(),
        api.libraryStats(),
        api.getSmartPlaylists().catch(() => []),
      ]);
      tracks = tracksData;
      stats = statsData;
      smartPlaylists = smartData;
      if (selectedSmartPlaylist) {
        const found = smartPlaylists.find((s) => s.id === selectedSmartPlaylist!.id);
        if (found) selectSmartPlaylist(found);
      }
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function selectSmartPlaylist(sp: SmartPlaylist) {
    selectedSmartPlaylist = sp;
    smartLoading = true;
    try {
      const detail = await api.getSmartPlaylist(sp.id);
      smartPlaylistTracks = detail.tracks || [];
    } catch (err) {
      console.error("Failed to load smart playlist tracks:", err);
    } finally {
      smartLoading = false;
    }
  }

  async function handleDeleteSmartPlaylist(sp: SmartPlaylist) {
    if (!confirm(`Are you sure you want to delete smart playlist "${sp.name}"?`)) return;
    try {
      await api.deleteSmartPlaylist(sp.id);
      if (selectedSmartPlaylist?.id === sp.id) {
        selectedSmartPlaylist = null;
        smartPlaylistTracks = [];
      }
      await loadLibraryData();
    } catch (err) {
      alert(`Error deleting smart playlist: ${err}`);
    }
  }

  function handleOpenCreateSmart() {
    editingSmartPlaylist = null;
    showSmartPlaylistModal = true;
  }

  function handleOpenEditSmart(sp: SmartPlaylist) {
    editingSmartPlaylist = sp;
    showSmartPlaylistModal = true;
  }

  let isServer = $state(false);

  onMount(() => {
    isServer = typeof window !== "undefined" && !Boolean((window as any).__TAURI_INTERNALS__);
    loadLibraryData();
  });

  // Derived unique playlists and formats for filter dropdowns
  let allPlaylists = $derived(
    Array.from(new Set(tracks.flatMap((t) => t.playlists || []))).sort()
  );

  let allFormats = $derived(
    Array.from(new Set(tracks.map((t) => t.format).filter(Boolean))).sort()
  );

  // Filtered & Sorted Tracks
  let filteredTracks = $derived(
    tracks.filter((t) => {
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesTitle = t.title.toLowerCase().includes(q);
        const matchesArtist = t.artist.toLowerCase().includes(q);
        const matchesAlbum = t.album.toLowerCase().includes(q);
        const matchesPlaylist = (t.playlists || []).some((p) => p.toLowerCase().includes(q));
        if (!matchesTitle && !matchesArtist && !matchesAlbum && !matchesPlaylist) {
          return false;
        }
      }
      if (selectedPlaylistFilter !== "all" && !(t.playlists || []).includes(selectedPlaylistFilter)) {
        return false;
      }
      if (selectedFormatFilter !== "all" && t.format !== selectedFormatFilter) {
        return false;
      }
      if (selectedLyricsFilter === "has_lyrics" && !t.has_lyrics) {
        return false;
      }
      if (selectedLyricsFilter === "no_lyrics" && t.has_lyrics) {
        return false;
      }
      if (selectedStatusFilter === "on_disk" && !t.exists_on_disk) {
        return false;
      }
      if (selectedStatusFilter === "missing" && t.exists_on_disk) {
        return false;
      }
      return true;
    })
  );

  let sortedTracks = $derived(
    [...filteredTracks].sort((a, b) => {
      let comp = 0;
      if (sortKey === "downloaded_at") {
        comp = (a.downloaded_at || "").localeCompare(b.downloaded_at || "");
      } else if (sortKey === "title") {
        comp = a.title.localeCompare(b.title);
      } else if (sortKey === "artist") {
        comp = a.artist.localeCompare(b.artist);
      } else if (sortKey === "album") {
        comp = a.album.localeCompare(b.album);
      } else if (sortKey === "file_size") {
        comp = (a.file_size || 0) - (b.file_size || 0);
      }
      return sortAsc ? comp : -comp;
    })
  );

  let selectedTracksList = $derived(
    tracks.filter((t) => selectedTrackIds.has(t.track_id))
  );

  function toggleTrackSelect(trackId: string, shiftKey: boolean) {
    const next = new Set(selectedTrackIds);
    if (shiftKey && lastSelectedTrackId && sortedTracks.length > 0) {
      const prevIndex = sortedTracks.findIndex((t) => t.track_id === lastSelectedTrackId);
      const currIndex = sortedTracks.findIndex((t) => t.track_id === trackId);
      if (prevIndex !== -1 && currIndex !== -1) {
        const [start, end] = prevIndex < currIndex ? [prevIndex, currIndex] : [currIndex, prevIndex];
        for (let i = start; i <= end; i++) {
          next.add(sortedTracks[i].track_id);
        }
        selectedTrackIds = next;
        lastSelectedTrackId = trackId;
        return;
      }
    }
    if (next.has(trackId)) {
      next.delete(trackId);
    } else {
      next.add(trackId);
    }
    selectedTrackIds = next;
    lastSelectedTrackId = trackId;
  }

  function toggleSelectAllTracks() {
    if (selectedTrackIds.size === sortedTracks.length) {
      selectedTrackIds = new Set();
    } else {
      selectedTrackIds = new Set(sortedTracks.map((t) => t.track_id));
    }
  }

  // Album Groupings
  interface AlbumGroup {
    album: string;
    artist: string;
    artwork_url: string | null;
    tracks: LibraryTrack[];
    total_size: number;
    playlists: Set<string>;
  }

  let albumGroups = $derived.by(() => {
    const map = new Map<string, AlbumGroup>();
    for (const t of filteredTracks) {
      const key = `${t.artist} — ${t.album}`;
      let group = map.get(key);
      if (!group) {
        group = {
          album: t.album,
          artist: t.artist,
          artwork_url: t.artwork_url,
          tracks: [],
          total_size: 0,
          playlists: new Set<string>(),
        };
        map.set(key, group);
      }
      group.tracks.push(t);
      group.total_size += t.file_size || 0;
      (t.playlists || []).forEach((p) => group!.playlists.add(p));
      if (!group.artwork_url && t.artwork_url) {
        group.artwork_url = t.artwork_url;
      }
    }
    return Array.from(map.values()).sort((a, b) => a.album.localeCompare(b.album));
  });

  // Artist Groupings
  interface ArtistGroup {
    artist: string;
    albums: Set<string>;
    tracks: LibraryTrack[];
    total_size: number;
  }

  let artistGroups = $derived.by(() => {
    const map = new Map<string, ArtistGroup>();
    for (const t of filteredTracks) {
      let group = map.get(t.artist);
      if (!group) {
        group = {
          artist: t.artist,
          albums: new Set<string>(),
          tracks: [],
          total_size: 0,
        };
        map.set(t.artist, group);
      }
      group.albums.add(t.album);
      group.tracks.push(t);
      group.total_size += t.file_size || 0;
    }
    return Array.from(map.values()).sort((a, b) => a.artist.localeCompare(b.artist));
  });

  // Health Actions
  async function runAudit() {
    auditLoading = true;
    auditError = null;
    repairMessage = null;
    try {
      auditReport = await api.auditLibrary();
    } catch (e) {
      auditError = String(e);
    } finally {
      auditLoading = false;
    }
  }

  async function runIntegrityCheck() {
    integrityLoading = true;
    integrityError = null;
    repairMessage = null;
    try {
      integrityReport = await api.verifyIntegrity();
      if (integrityReport) {
        void notifyIntegrityCompleted(integrityReport.corrupted?.length ?? 0);
      }
    } catch (e) {
      integrityError = String(e);
    } finally {
      integrityLoading = false;
    }
  }

  async function handlePruneMissing() {
    if (!confirm("Are you sure you want to prune database references for missing tracks? This cannot be undone.")) {
      return;
    }
    repairLoading = true;
    repairMessage = null;
    try {
      const res = await api.repairLibrary("prune_missing");
      repairMessage = {
        type: "success",
        text: `Pruned ${res.pruned_count ?? 0} missing track record(s) from database.`,
      };
      await Promise.all([loadLibraryData(), runAudit()]);
    } catch (e) {
      repairMessage = { type: "error", text: String(e) };
    } finally {
      repairLoading = false;
    }
  }

  async function handleAdoptOrphans() {
    repairLoading = true;
    repairMessage = null;
    try {
      const res = await api.repairLibrary("adopt_orphans");
      repairMessage = {
        type: "success",
        text: `Successfully imported ${res.adopted_count ?? 0} untracked audio file(s) into the library.`,
      };
      await Promise.all([loadLibraryData(), runAudit()]);
    } catch (e) {
      repairMessage = { type: "error", text: String(e) };
    } finally {
      repairLoading = false;
    }
  }

  async function handleRegenerateM3u8() {
    repairLoading = true;
    repairMessage = null;
    try {
      const res = await api.repairLibrary("regenerate_m3u8");
      repairMessage = {
        type: "success",
        text: `Regenerated ${(res.playlists || []).length} playlist .m3u8 file(s).`,
      };
    } catch (e) {
      repairMessage = { type: "error", text: String(e) };
    } finally {
      repairLoading = false;
    }
  }

  async function runDuplicateScan() {
    duplicatesLoading = true;
    duplicatesError = null;
    repairMessage = null;
    try {
      duplicatesReport = await api.getLibraryDuplicates();
    } catch (e) {
      duplicatesError = String(e);
    } finally {
      duplicatesLoading = false;
    }
  }

  async function handleSweepDuplicates(groupIds?: string[]) {
    const isAll = !groupIds || groupIds.length === 0;
    const msg = isAll
      ? `Are you sure you want to sweep all duplicate songs across your library? ${sweepDeleteFiles ? "Duplicate audio files & lyrics sidecars will be safely deleted from storage, and playlists will be remapped to the primary copy." : "Duplicates will be removed from database and remapped."}`
      : `Sweep selected duplicate song group?`;
    if (!confirm(msg)) return;

    sweepLoading = true;
    repairMessage = null;
    try {
      const res = await api.deduplicateLibrary({
        keep_criteria: sweepCriteria,
        delete_files: sweepDeleteFiles,
        remap_playlists: sweepRemapPlaylists,
        group_ids: groupIds,
      });
      repairMessage = {
        type: "success",
        text: `Duplicate sweep completed: Removed ${res.removed_tracks_count} duplicate track(s), deleted ${res.deleted_files_count} file(s), freed ${formatBytes(res.freed_bytes)}, and remapped ${res.remapped_playlist_references} playlist reference(s).`,
      };
      await Promise.all([loadLibraryData(), runDuplicateScan(), runAudit()]);
    } catch (e) {
      repairMessage = { type: "error", text: String(e) };
    } finally {
      sweepLoading = false;
    }
  }

  function toggleDuplicateGroup(groupId: string) {
    expandedDuplicateGroups[groupId] = !expandedDuplicateGroups[groupId];
  }

  function filterByPlaylist(pl: string) {
    selectedPlaylistFilter = pl;
    activeTab = "tracks";
  }

  function filterByArtist(art: string) {
    searchQuery = art;
    activeTab = "tracks";
  }

  function filterByAlbum(alb: string) {
    searchQuery = alb;
    activeTab = "tracks";
  }
</script>

<div class="h-full flex flex-col overflow-hidden" style="background:var(--bg);color:var(--text-primary);">
  <!-- Header Bar -->
  <div class="p-6 pb-4 border-b flex flex-col gap-4" style="border-color:var(--border);">
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        <h1 class="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
          <span>♫</span> Library Stewardship
        </h1>
        <span class="text-xs px-2.5 py-0.5 rounded-full font-medium" style="background:var(--accent-dim);color:var(--accent);border:1px solid rgba(252,211,77,0.2);">
          {isServer ? "Server / Headless" : "Workstation"}
        </span>
      </div>

      <div class="flex items-center gap-2.5">
        <button
          onclick={() => (showPlaylistImportModal = true)}
          class="px-3 py-1.5 text-xs font-bold rounded-lg flex items-center gap-1.5 transition-colors text-black"
          style="background:var(--accent);"
          title="Import playlist from Spotify, Tidal, CSV, M3U"
        >
          <span>⤓</span> Import & Match
        </button>
        <button
          onclick={() => { dapExportPlaylist = "All Tracks"; dapExportTrackCount = tracks.length; }}
          class="px-3 py-1.5 text-xs font-semibold rounded-lg flex items-center gap-1.5 transition-colors"
          style="background:var(--surface);color:var(--text-secondary);border:1px solid var(--border);"
          title="Export entire library to portable DAP player"
        >
          <span>⚡</span> Export to DAP
        </button>
        <button
          onclick={loadLibraryData}
          disabled={loading}
          class="px-3 py-1.5 text-xs font-semibold rounded-lg flex items-center gap-1.5 transition-colors"
          style="background:var(--surface);color:var(--text-secondary);border:1px solid var(--border);"
        >
          <span>↻</span> {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
    </div>

    <!-- Stats Ribbon -->
    {#if stats}
      <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
        <div class="p-3 rounded-xl flex flex-col justify-center" style="background:var(--surface);border:1px solid var(--border);">
          <span class="text-[11px] font-medium uppercase tracking-wider text-zinc-500">Tracks</span>
          <span class="text-lg font-bold text-white mt-0.5">{stats.total_tracks.toLocaleString()}</span>
        </div>
        <div class="p-3 rounded-xl flex flex-col justify-center" style="background:var(--surface);border:1px solid var(--border);">
          <span class="text-[11px] font-medium uppercase tracking-wider text-zinc-500">Albums</span>
          <span class="text-lg font-bold text-white mt-0.5">{stats.total_albums.toLocaleString()}</span>
        </div>
        <div class="p-3 rounded-xl flex flex-col justify-center" style="background:var(--surface);border:1px solid var(--border);">
          <span class="text-[11px] font-medium uppercase tracking-wider text-zinc-500">Artists</span>
          <span class="text-lg font-bold text-white mt-0.5">{stats.total_artists.toLocaleString()}</span>
        </div>
        <div class="p-3 rounded-xl flex flex-col justify-center" style="background:var(--surface);border:1px solid var(--border);">
          <span class="text-[11px] font-medium uppercase tracking-wider text-zinc-500">Storage Size</span>
          <span class="text-lg font-bold text-white mt-0.5">{formatBytes(stats.total_bytes)}</span>
        </div>
        <div class="p-3 rounded-xl flex flex-col justify-center" style="background:var(--surface);border:1px solid var(--border);">
          <span class="text-[11px] font-medium uppercase tracking-wider text-zinc-500">Playlists / Graveyard</span>
          <div class="flex items-center gap-1.5 text-lg font-bold text-white mt-0.5">
            <span>{stats.total_playlists}</span>
            <span class="text-xs font-normal text-zinc-500">({stats.delisted_count} delisted)</span>
          </div>
        </div>
      </div>
    {/if}

    <!-- Tab Navigation -->
    <div class="flex items-center gap-2 pt-1 border-t" style="border-color:var(--border);">
      {#each [
        { id: "tracks", label: "Tracks", count: tracks.length },
        { id: "albums", label: "Albums", count: albumGroups.length },
        { id: "artists", label: "Artists", count: artistGroups.length },
        { id: "smart", label: "⚡ Smart Playlists", count: smartPlaylists.length },
        { id: "health", label: "Health & Diagnostics", badge: auditReport?.summary.missing_files_count ? `! ${auditReport.summary.missing_files_count}` : null },
      ] as tab}
        <button
          onclick={() => (activeTab = tab.id as Tab)}
          class="px-4 py-2 text-xs font-bold rounded-lg transition-colors flex items-center gap-2 {activeTab === tab.id ? 'bg-amber-400 text-black shadow-sm' : 'bg-transparent text-[var(--text-secondary)] hover:text-white hover:bg-[var(--surface)]'}"
        >
          <span>{tab.label}</span>
          {#if tab.count !== undefined && activeTab !== tab.id}
            <span class="opacity-60 text-[10px]">({tab.count})</span>
          {/if}
          {#if tab.badge}
            <span class="px-1.5 py-0.2 rounded text-[10px] bg-red-500 text-white font-bold">{tab.badge}</span>
          {/if}
        </button>
      {/each}
    </div>
  </div>

  <!-- Content Area -->
  <div class="flex-1 overflow-y-auto p-6">
    {#if error}
      <div class="p-4 rounded-xl mb-4 text-xs bg-red-950/50 border border-red-800 text-red-300">
        Failed to load library: {error}
      </div>
    {/if}

    <!-- TAB: TRACKS / ALBUMS / ARTISTS (Share Search & Filter Bar) -->
    {#if activeTab !== "health"}
      <div class="flex flex-wrap items-center gap-3 mb-6">
        <!-- Search bar -->
        <div class="flex-1 min-w-[240px] relative">
          <input
            bind:value={searchQuery}
            placeholder="Search tracks, artists, albums, or playlists…"
            class="w-full px-3.5 py-2 text-xs rounded-lg outline-none transition-all placeholder:text-zinc-500"
            style="background:var(--surface);border:1px solid var(--border);color:white;"
          />
          {#if searchQuery}
            <button
              onclick={() => (searchQuery = "")}
              class="absolute right-3 top-2.5 text-xs text-zinc-500 hover:text-white"
            >✕</button>
          {/if}
        </div>

        <!-- Playlist Filter -->
        <select
          bind:value={selectedPlaylistFilter}
          class="px-3 py-2 text-xs rounded-lg outline-none cursor-pointer"
          style="background:var(--surface);border:1px solid var(--border);color:var(--text-secondary);"
        >
          <option value="all">All Playlists ({allPlaylists.length})</option>
          {#each allPlaylists as pl}
            <option value={pl}>{pl}</option>
          {/each}
        </select>

        <!-- Format Filter -->
        <select
          bind:value={selectedFormatFilter}
          class="px-3 py-2 text-xs rounded-lg outline-none cursor-pointer"
          style="background:var(--surface);border:1px solid var(--border);color:var(--text-secondary);"
        >
          <option value="all">All Formats</option>
          {#each allFormats as fmt}
            <option value={fmt}>{fmt}</option>
          {/each}
        </select>

        <!-- Lyrics Filter -->
        <select
          bind:value={selectedLyricsFilter}
          class="px-3 py-2 text-xs rounded-lg outline-none cursor-pointer"
          style="background:var(--surface);border:1px solid var(--border);color:var(--text-secondary);"
        >
          <option value="all">All Lyrics</option>
          <option value="has_lyrics">With .lrc Lyrics</option>
          <option value="no_lyrics">Missing Lyrics</option>
        </select>

        <!-- Sort Control -->
        <div class="flex items-center gap-1">
          <select
            bind:value={sortKey}
            class="px-3 py-2 text-xs rounded-lg outline-none cursor-pointer"
            style="background:var(--surface);border:1px solid var(--border);color:var(--text-secondary);"
          >
            <option value="downloaded_at">Date Downloaded</option>
            <option value="title">Title</option>
            <option value="artist">Artist</option>
            <option value="album">Album</option>
            <option value="file_size">File Size</option>
          </select>
          <button
            onclick={() => (sortAsc = !sortAsc)}
            title={sortAsc ? "Sort Ascending" : "Sort Descending"}
            class="p-2 text-xs rounded-lg transition-colors"
            style="background:var(--surface);border:1px solid var(--border);color:var(--text-secondary);"
          >
            {sortAsc ? "▲" : "▼"}
          </button>
        </div>
      </div>
    {/if}

    <!-- TAB: TRACKS VIEW -->
    {#if activeTab === "tracks"}
      {#if loading}
        <div class="text-zinc-500 text-xs py-8 text-center">Loading library tracks…</div>
      {:else if sortedTracks.length === 0}
        <div class="text-zinc-500 text-xs py-12 text-center flex flex-col items-center gap-2">
          <span>No tracks found matching your query or filter.</span>
          {#if searchQuery || selectedPlaylistFilter !== "all" || selectedFormatFilter !== "all"}
            <button
              onclick={() => { searchQuery = ""; selectedPlaylistFilter = "all"; selectedFormatFilter = "all"; selectedLyricsFilter = "all"; }}
              class="text-amber-400 underline cursor-pointer"
            >Reset filters</button>
          {/if}
        </div>
      {:else}
        <div class="h-[600px] w-full relative">
          <VirtualTrackTable
            tracks={sortedTracks}
            selectedTrackIds={selectedTrackIds}
            ontoggleSelect={toggleTrackSelect}
            ontoggleSelectAll={toggleSelectAllTracks}
            onfilterArtist={filterByArtist}
            onfilterAlbum={filterByAlbum}
            onfilterPlaylist={filterByPlaylist}
            onopenLyrics={(t) => (activeLyricsTrack = t)}
            onrevealTrack={(p) => api.revealTrack(p).catch(console.error)}
          />

          {#if selectedTrackIds.size > 0}
            <div class="fixed bottom-24 left-1/2 -translate-x-1/2 z-30 px-5 py-3 rounded-2xl border shadow-2xl backdrop-blur-xl flex items-center gap-4 bg-[rgba(24,24,27,0.95)] border-amber-400/40 text-white animate-fade-in">
              <span class="text-xs font-bold text-amber-300">
                {selectedTrackIds.size} track{selectedTrackIds.size === 1 ? "" : "s"} selected
              </span>
              <div class="h-4 w-px bg-zinc-700"></div>
              <button
                onclick={() => { batchTagCoverFocus = false; showBatchTagModal = true; }}
                class="px-3 py-1.5 rounded-lg text-xs font-bold bg-amber-400 text-black hover:bg-amber-300 transition-colors flex items-center gap-1.5 shadow"
              >
                <span>🏷️</span>
                <span>Edit Tags</span>
              </button>
              <button
                onclick={() => { batchTagCoverFocus = true; showBatchTagModal = true; }}
                class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-zinc-800 hover:bg-zinc-700 text-zinc-200 transition-colors flex items-center gap-1.5 border border-zinc-700"
              >
                <span>🖼️</span>
                <span>Replace Cover</span>
              </button>
              <button
                onclick={() => (selectedTrackIds = new Set())}
                class="text-xs text-zinc-400 hover:text-white transition-colors ml-2"
              >
                ✕ Clear
              </button>
            </div>
          {/if}
        </div>
      {/if}
    {/if}

    <!-- TAB: ALBUMS VIEW -->
    {#if activeTab === "albums"}
      {#if albumGroups.length === 0}
        <div class="text-zinc-500 text-xs py-12 text-center">No albums found matching criteria.</div>
      {:else}
        <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
          {#each albumGroups as alb}
            <button
              type="button"
              class="rounded-xl overflow-hidden p-3 flex flex-col gap-2.5 cursor-pointer transition-all hover:-translate-y-0.5 hover:shadow-lg text-left"
              style="background:var(--surface);border:1px solid var(--border);"
              onclick={() => filterByAlbum(alb.album)}
            >
              <div class="aspect-square w-full rounded-lg overflow-hidden bg-black/40 flex items-center justify-center">
                {#if alb.artwork_url}
                  <img
                    src={thumbUrl(alb.artwork_url, "300x300")}
                    alt={alb.album}
                    class="w-full h-full object-cover"
                    onerror={(e) => {
                      const img = e.currentTarget as HTMLImageElement;
                      const lp = alb.tracks[0]?.local_path;
                      if (lp && !img.src.includes("/track-art")) {
                        img.src = `/track-art?path=${encodeURIComponent(lp)}`;
                      } else {
                        img.style.display = "none";
                      }
                    }}
                  />
                {:else if alb.tracks[0]?.local_path}
                  <img
                    src={`/track-art?path=${encodeURIComponent(alb.tracks[0].local_path)}`}
                    alt={alb.album}
                    class="w-full h-full object-cover"
                    onerror={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                  />
                {:else}
                  <span class="text-4xl text-zinc-700">♪</span>
                {/if}
              </div>

              <div class="flex flex-col min-w-0 w-full">
                <div class="font-bold text-xs text-white truncate" title={alb.album}>{alb.album}</div>
                <div class="text-[11px] text-zinc-400 truncate mt-0.5" title={alb.artist}>{alb.artist}</div>
                <div class="flex items-center justify-between text-[10px] text-zinc-500 mt-2 pt-2 border-t" style="border-color:var(--border);">
                  <span>{alb.tracks.length} track{alb.tracks.length === 1 ? "" : "s"}</span>
                  <span class="font-mono">{formatBytes(alb.total_size)}</span>
                </div>
              </div>
            </button>
          {/each}
        </div>
      {/if}
    {/if}

    <!-- TAB: ARTISTS VIEW -->
    {#if activeTab === "artists"}
      {#if artistGroups.length === 0}
        <div class="text-zinc-500 text-xs py-12 text-center">No artists found matching criteria.</div>
      {:else}
        <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {#each artistGroups as art}
            <button
              type="button"
              class="p-4 rounded-xl flex items-center justify-between cursor-pointer transition-all hover:bg-white/[0.04] text-left w-full"
              style="background:var(--surface);border:1px solid var(--border);"
              onclick={() => filterByArtist(art.artist)}
            >
              <div class="flex flex-col min-w-0 pr-3">
                <span class="font-bold text-xs text-white truncate">{art.artist}</span>
                <span class="text-[11px] text-zinc-400 mt-0.5">
                  {art.albums.size} album{art.albums.size === 1 ? "" : "s"} • {art.tracks.length} track{art.tracks.length === 1 ? "" : "s"}
                </span>
              </div>
              <span class="text-[11px] font-mono text-zinc-500 flex-shrink-0">{formatBytes(art.total_size)}</span>
            </button>
          {/each}
        </div>
      {/if}
    {/if}

    <!-- TAB: SMART PLAYLISTS -->
    {#if activeTab === "smart"}
      <div class="flex flex-col gap-6">
        <!-- Top Toolbar -->
        <div class="flex items-center justify-between bg-zinc-900/60 p-4 rounded-xl border border-zinc-800">
          <div>
            <h2 class="text-sm font-bold text-white flex items-center gap-2">
              <span>⚡</span> Dynamic Smart Playlists
            </h2>
            <p class="text-xs text-zinc-400 mt-0.5">
              Live queries that automatically update as your lossless library expands.
            </p>
          </div>
          <button
            onclick={handleOpenCreateSmart}
            class="px-3.5 py-1.5 bg-amber-400 hover:bg-amber-300 text-black text-xs font-bold rounded-lg shadow flex items-center gap-1.5 transition"
          >
            <span>＋</span> New Smart Playlist
          </button>
        </div>

        {#if smartPlaylists.length === 0}
          <div class="text-center py-16 px-4 rounded-xl border border-dashed border-zinc-800 bg-zinc-950/40">
            <div class="text-3xl mb-2">⚡</div>
            <div class="text-sm font-bold text-zinc-300">No Smart Playlists Created</div>
            <p class="text-xs text-zinc-500 max-w-sm mx-auto mt-1 mb-4">
              Create rules to automatically group tracks by artist, format, tags, date added, or existing playlists.
            </p>
            <button
              onclick={handleOpenCreateSmart}
              class="px-4 py-2 bg-amber-400 hover:bg-amber-300 text-black text-xs font-bold rounded-lg transition"
            >
              Create Your First Smart Playlist
            </button>
          </div>
        {:else}
          <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <!-- Playlists List -->
            <div class="flex flex-col gap-2.5">
              {#each smartPlaylists as sp}
                <div
                  role="button"
                  tabindex="0"
                  onclick={() => selectSmartPlaylist(sp)}
                  onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') selectSmartPlaylist(sp); }}
                  class="p-4 rounded-xl border text-left transition flex flex-col gap-2 cursor-pointer {selectedSmartPlaylist?.id === sp.id ? 'border-amber-400 bg-amber-400/5' : 'border-zinc-800 bg-zinc-900/40 hover:border-zinc-700'}"
                >
                  <div class="flex items-center justify-between w-full">
                    <div class="font-bold text-xs text-zinc-100 flex items-center gap-2">
                      <span class="text-amber-400">⚡</span>
                      <span>{sp.name}</span>
                    </div>
                    <span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-zinc-800 text-zinc-300 border border-zinc-700">
                      {sp.track_count ?? 0} tracks
                    </span>
                  </div>
                  {#if sp.description}
                    <p class="text-[11px] text-zinc-400 line-clamp-1">{sp.description}</p>
                  {/if}
                  <div class="flex items-center justify-between text-[10px] text-zinc-500 pt-2 border-t border-zinc-800/80 w-full mt-1">
                    <span>Updated {new Date(sp.updated_at).toLocaleDateString()}</span>
                    <div class="flex items-center gap-2">
                      <button
                        onclick={(e) => { e.stopPropagation(); handleOpenEditSmart(sp); }}
                        class="hover:text-amber-400 transition"
                        title="Edit Rules"
                      >
                        ✏️ Edit
                      </button>
                      <button
                        onclick={(e) => { e.stopPropagation(); handleDeleteSmartPlaylist(sp); }}
                        class="hover:text-red-400 transition"
                        title="Delete Smart Playlist"
                      >
                        🗑️
                      </button>
                    </div>
                  </div>
                </div>
              {/each}
            </div>

            <!-- Detail & Track View -->
            <div class="lg:col-span-2 border border-zinc-800 rounded-xl bg-zinc-950 p-4 flex flex-col min-h-[400px]">
              {#if !selectedSmartPlaylist}
                <div class="flex-1 flex flex-col items-center justify-center text-center p-8 text-zinc-500 text-xs">
                  <span>Select a smart playlist from the left to view matching tracks.</span>
                </div>
              {:else}
                <div class="flex items-center justify-between pb-3 mb-3 border-b border-zinc-800">
                  <div>
                    <h3 class="text-sm font-bold text-zinc-100 flex items-center gap-2">
                      <span class="text-amber-400">⚡</span> {selectedSmartPlaylist.name}
                    </h3>
                    {#if selectedSmartPlaylist.description}
                      <p class="text-xs text-zinc-400 mt-0.5">{selectedSmartPlaylist.description}</p>
                    {/if}
                  </div>
                  <div class="flex items-center gap-2">
                    <button
                      onclick={() => handleOpenEditSmart(selectedSmartPlaylist!)}
                      class="px-2.5 py-1 text-xs font-semibold rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-700 transition"
                    >
                      Edit Query
                    </button>
                    <button
                      onclick={() => { dapExportPlaylist = selectedSmartPlaylist!.name; dapExportTrackCount = smartPlaylistTracks.length; }}
                      class="px-2.5 py-1 text-xs font-semibold rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-700 transition"
                    >
                      Export to DAP
                    </button>
                  </div>
                </div>

                {#if smartLoading}
                  <div class="flex-1 flex items-center justify-center text-xs text-zinc-500">
                    Evaluating dynamic query...
                  </div>
                {:else if smartPlaylistTracks.length === 0}
                  <div class="flex-1 flex items-center justify-center text-xs text-zinc-500">
                    No tracks in your library currently match this rule.
                  </div>
                {:else}
                  <div class="flex-1 overflow-y-auto">
                    <VirtualTrackTable
                      tracks={smartPlaylistTracks}
                      onopenLyrics={(t: LibraryTrack) => (activeLyricsTrack = t)}
                      onfilterArtist={(a: string) => filterByArtist(a)}
                      onfilterAlbum={(al: string) => filterByAlbum(al)}
                    />
                  </div>
                {/if}
              {/if}
            </div>
          </div>
        {/if}
      </div>
    {/if}

    <!-- TAB: HEALTH & REPAIR WORKSTATION -->
    {#if activeTab === "health"}
      <div class="flex flex-col gap-6 max-w-5xl mx-auto">
        <!-- Repair Message Banner -->
        {#if repairMessage}
          <div
            class="p-4 rounded-xl text-xs flex items-center justify-between font-medium"
            style={repairMessage.type === "success"
              ? "background:rgba(34,197,94,0.15);color:#4ade80;border:1px solid rgba(34,197,94,0.3);"
              : "background:rgba(239,68,68,0.15);color:#f87171;border:1px solid rgba(239,68,68,0.3);"}
          >
            <span>{repairMessage.text}</span>
            <button onclick={() => (repairMessage = null)} class="text-xs opacity-70 hover:opacity-100">✕</button>
          </div>
        {/if}

        <!-- Maintenance & Diagnostic Cards Grid -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <!-- Card 1: Library Filesystem & Database Health -->
          <div class="p-5 rounded-2xl flex flex-col justify-between gap-4" style="background:var(--surface);border:1px solid var(--border);">
            <div>
              <div class="flex items-center justify-between">
                <h3 class="font-bold text-sm text-white flex items-center gap-2">
                  <span>◈</span> Health & Discrepancy Audit
                </h3>
                {#if auditReport}
                  <span class="text-[10px] px-2 py-0.5 rounded font-mono" style="background:rgba(255,255,255,0.05);color:var(--text-muted);">
                    Scanned {auditReport.summary.total_db_tracks} DB tracks
                  </span>
                {/if}
              </div>
              <p class="text-xs text-zinc-400 mt-2 leading-relaxed">
                Scan your library storage to identify database entries missing files on disk, unindexed audio files, and missing metadata.
              </p>

              {#if auditReport}
                <div class="grid grid-cols-2 gap-2 mt-4 text-xs font-mono">
                  <div class="p-2.5 rounded-lg bg-black/30 border border-white/5">
                    <span class="text-zinc-400 block text-[10px]">Missing Files:</span>
                    <span class={auditReport.summary.missing_files_count > 0 ? "text-red-400 font-bold text-sm" : "text-emerald-400 font-bold text-sm"}>
                      {auditReport.summary.missing_files_count}
                    </span>
                  </div>
                  <div class="p-2.5 rounded-lg bg-black/30 border border-white/5">
                    <span class="text-zinc-400 block text-[10px]">Orphaned Files:</span>
                    <span class={auditReport.summary.orphaned_files_count > 0 ? "text-amber-400 font-bold text-sm" : "text-zinc-300 font-bold text-sm"}>
                      {auditReport.summary.orphaned_files_count}
                    </span>
                  </div>
                  <div class="p-2.5 rounded-lg bg-black/30 border border-white/5">
                    <span class="text-zinc-400 block text-[10px]">Missing .lrc:</span>
                    <span class="text-zinc-300 font-bold text-sm">{auditReport.summary.missing_lyrics_count}</span>
                  </div>
                  <div class="p-2.5 rounded-lg bg-black/30 border border-white/5">
                    <span class="text-zinc-400 block text-[10px]">Missing Artwork:</span>
                    <span class="text-zinc-300 font-bold text-sm">{auditReport.summary.missing_art_count}</span>
                  </div>
                </div>
              {/if}

              {#if auditError}
                <div class="mt-3 text-xs text-red-400">{auditError}</div>
              {/if}
            </div>

            <div class="flex flex-wrap gap-2 pt-2 border-t" style="border-color:var(--border);">
              <button
                onclick={runAudit}
                disabled={auditLoading || repairLoading}
                class="px-3.5 py-2 text-xs font-bold rounded-lg transition-all"
                style="background:var(--accent);color:black;"
              >
                {auditLoading ? "Auditing Filesystem…" : "Run Health Scan"}
              </button>

              {#if auditReport?.summary.missing_files_count}
                <button
                  onclick={handlePruneMissing}
                  disabled={repairLoading}
                  class="px-3 py-2 text-xs font-semibold rounded-lg bg-red-900/60 hover:bg-red-800 text-red-200 border border-red-700 transition-colors"
                >
                  Prune Dead DB References ({auditReport.summary.missing_files_count})
                </button>
              {/if}

              {#if auditReport?.summary.orphaned_files_count}
                <button
                  onclick={handleAdoptOrphans}
                  disabled={repairLoading}
                  class="px-3 py-2 text-xs font-semibold rounded-lg bg-amber-900/60 hover:bg-amber-800 text-amber-200 border border-amber-700 transition-colors"
                >
                  Adopt Untracked Files ({auditReport.summary.orphaned_files_count})
                </button>
              {/if}
            </div>
          </div>

          <!-- Card 2: Audio Stream Integrity & FLAC Verification -->
          <div class="p-5 rounded-2xl flex flex-col justify-between gap-4" style="background:var(--surface);border:1px solid var(--border);">
            <div>
              <div class="flex items-center justify-between">
                <h3 class="font-bold text-sm text-white flex items-center gap-2">
                  <span>⚙</span> Audio Frame Integrity Verification
                </h3>
              </div>
              <p class="text-xs text-zinc-400 mt-2 leading-relaxed">
                Run batch stream decoding validation (`flac -t -s`) across your library tracks to ensure bit-perfect audio headers and lossless stream fidelity.
              </p>

              {#if integrityReport}
                <div class="mt-4 p-3 rounded-lg bg-black/30 border border-white/5 text-xs">
                  <div class="flex items-center justify-between">
                    <span class="text-zinc-400">Scanned Tracks:</span>
                    <span class="text-white font-mono font-bold">{integrityReport.checked_count}</span>
                  </div>
                  <div class="flex items-center justify-between mt-1">
                    <span class="text-zinc-400">Status:</span>
                    <span class={integrityReport.status === "ok" ? "text-emerald-400 font-bold" : "text-red-400 font-bold"}>
                      {integrityReport.status === "ok" ? "All Bitstreams Valid" : `${integrityReport.corrupted.length} Corrupted File(s)`}
                    </span>
                  </div>
                </div>
              {/if}

              {#if integrityError}
                <div class="mt-3 text-xs text-red-400">{integrityError}</div>
              {/if}
            </div>

            <div class="pt-2 border-t flex items-center gap-2" style="border-color:var(--border);">
              <button
                onclick={runIntegrityCheck}
                disabled={integrityLoading || repairLoading}
                class="px-3.5 py-2 text-xs font-bold rounded-lg transition-all"
                style="background:var(--surface-hover);color:white;border:1px solid var(--border);"
              >
                {integrityLoading ? "Decoding FLAC Frames…" : "Run Stream Integrity Scan"}
              </button>
            </div>
          </div>

          <!-- Card 3: Playlist Sync & M3U8 Regeneration -->
          <div class="p-5 rounded-2xl flex flex-col justify-between gap-4" style="background:var(--surface);border:1px solid var(--border);">
            <div class="flex flex-col justify-between gap-4 h-full">
              <div>
                <h3 class="font-bold text-sm text-white flex items-center gap-2">
                  <span>☰</span> Playlist Sync & M3U8 Regeneration
                </h3>
                <p class="text-xs text-zinc-400 mt-2 leading-relaxed">
                  Safely reconstruct all `.m3u8` playlist files in your library `playlists/` folder from verified SQLite database track associations.
                </p>
              </div>

              <div class="pt-2 border-t flex items-center gap-2" style="border-color:var(--border);">
                <button
                  onclick={handleRegenerateM3u8}
                  disabled={repairLoading}
                  class="px-3.5 py-2 text-xs font-bold rounded-lg transition-colors"
                  style="background:var(--surface-hover);color:white;border:1px solid var(--border);"
                >
                  {repairLoading ? "Regenerating…" : "Regenerate All Playlists (.m3u8)"}
                </button>
              </div>
            </div>
          </div>

          <!-- Card 4: Duplicate Songs & Storage Sweep -->
          <div class="p-5 rounded-2xl flex flex-col justify-between gap-4" style="background:var(--surface);border:1px solid var(--border);">
            <div>
              <div class="flex items-center justify-between">
                <h3 class="font-bold text-sm text-white flex items-center gap-2">
                  <span>🔍</span> Duplicate Songs & Storage Sweep
                </h3>
                {#if duplicatesReport}
                  <span class="text-[10px] px-2 py-0.5 rounded font-mono {duplicatesReport.total_groups > 0 ? 'bg-amber-500/20 text-amber-300' : 'bg-emerald-500/20 text-emerald-300'}">
                    {duplicatesReport.total_groups > 0 ? `${duplicatesReport.total_groups} duplicate groups` : "Zero duplicates"}
                  </span>
                {/if}
              </div>
              <p class="text-xs text-zinc-400 mt-2 leading-relaxed">
                Identify duplicate songs across single releases vs full albums, collision files (`_coll_*.flac`), and multiple copies. Safely prune duplicate audio files from disk and auto-remap playlists.
              </p>

              {#if duplicatesReport}
                <div class="grid grid-cols-3 gap-2 mt-4 text-xs font-mono">
                  <div class="p-2.5 rounded-lg bg-black/30 border border-white/5">
                    <span class="text-zinc-400 block text-[10px]">Duplicate Groups:</span>
                    <span class={duplicatesReport.total_groups > 0 ? "text-amber-400 font-bold text-sm" : "text-emerald-400 font-bold text-sm"}>
                      {duplicatesReport.total_groups}
                    </span>
                  </div>
                  <div class="p-2.5 rounded-lg bg-black/30 border border-white/5">
                    <span class="text-zinc-400 block text-[10px]">Extra Tracks:</span>
                    <span class="text-white font-bold text-sm">{duplicatesReport.total_duplicate_tracks}</span>
                  </div>
                  <div class="p-2.5 rounded-lg bg-black/30 border border-white/5">
                    <span class="text-zinc-400 block text-[10px]">Reclaimable:</span>
                    <span class="text-emerald-400 font-bold text-sm">{formatBytes(duplicatesReport.total_reclaimable_bytes)}</span>
                  </div>
                </div>

                <!-- Sweep Options -->
                <div class="mt-4 p-3 rounded-lg bg-black/20 border border-white/5 flex flex-col gap-2.5 text-xs">
                  <div class="flex flex-wrap items-center justify-between gap-2">
                    <span class="text-zinc-300 font-semibold text-[11px]">Keep Preference:</span>
                    <select bind:value={sweepCriteria} class="bg-[#121212] border border-[#2a2a2a] rounded px-2 py-1 text-xs text-zinc-200 outline-none">
                      <option value="recommended">Best Quality & Album Version (Recommended)</option>
                      <option value="album_over_single">Full Album over Singles/EPs</option>
                      <option value="highest_quality">Highest Bitrate / File Size</option>
                      <option value="oldest">First Downloaded (Oldest)</option>
                      <option value="newest">Most Recently Downloaded (Newest)</option>
                    </select>
                  </div>
                  <div class="flex flex-wrap gap-4 text-[11px] text-zinc-400 pt-1">
                    <label class="flex items-center gap-1.5 cursor-pointer">
                      <input type="checkbox" bind:checked={sweepDeleteFiles} class="rounded accent-amber-500" />
                      <span>Delete duplicate audio files & .lrc from disk</span>
                    </label>
                    <label class="flex items-center gap-1.5 cursor-pointer">
                      <input type="checkbox" bind:checked={sweepRemapPlaylists} class="rounded accent-amber-500" />
                      <span>Remap playlists & rewrite .m3u8</span>
                    </label>
                  </div>
                </div>
              {/if}

              {#if duplicatesError}
                <div class="mt-3 text-xs text-red-400">{duplicatesError}</div>
              {/if}
            </div>

            <div class="flex flex-wrap gap-2 pt-2 border-t" style="border-color:var(--border);">
              <button
                onclick={runDuplicateScan}
                disabled={duplicatesLoading || sweepLoading}
                class="px-3.5 py-2 text-xs font-bold rounded-lg transition-all"
                style="background:var(--surface-hover);color:white;border:1px solid var(--border);"
              >
                {duplicatesLoading ? "Scanning Library…" : "Scan for Duplicates"}
              </button>

              {#if duplicatesReport?.total_groups}
                <button
                  onclick={() => handleSweepDuplicates()}
                  disabled={sweepLoading || duplicatesLoading}
                  class="px-3.5 py-2 text-xs font-bold rounded-lg bg-amber-500 hover:bg-amber-400 text-black transition-all shadow-sm flex items-center gap-1.5"
                >
                  <span>⚡</span> {sweepLoading ? "Sweeping Duplicates…" : `Sweep All Duplicates (${duplicatesReport.total_duplicate_tracks})`}
                </button>
              {/if}
            </div>
          </div>
        </div>

        <!-- Duplicates Breakdown Accordion Feed -->
        {#if duplicatesReport?.groups?.length}
          <div class="p-5 rounded-2xl border border-amber-900/50 bg-amber-950/15">
            <div class="flex items-center justify-between mb-3">
              <h4 class="text-xs font-bold text-amber-300 uppercase tracking-wider flex items-center gap-2">
                <span>🔍</span> Duplicate Track Groups ({duplicatesReport.groups.length}) — {formatBytes(duplicatesReport.total_reclaimable_bytes)} Reclaimable
              </h4>
              <button
                onclick={() => handleSweepDuplicates()}
                disabled={sweepLoading}
                class="px-3 py-1 rounded-md text-xs font-bold bg-amber-600 hover:bg-amber-500 text-white transition-colors"
              >
                Sweep All
              </button>
            </div>
            <div class="flex flex-col gap-3 max-h-96 overflow-y-auto">
              {#each duplicatesReport.groups as group}
                <div class="p-3 rounded-xl bg-black/40 border border-white/5 flex flex-col gap-2">
                  <div class="flex items-center justify-between">
                    <button
                      type="button"
                      class="flex items-center gap-2.5 min-w-0 text-left cursor-pointer bg-transparent border-none p-0 outline-none flex-1"
                      onclick={() => toggleDuplicateGroup(group.group_id)}
                    >
                      <span class="text-xs text-amber-400 flex-shrink-0">{expandedDuplicateGroups[group.group_id] ? "▼" : "▶"}</span>
                      <div class="truncate">
                        <span class="font-bold text-white text-sm">{group.title}</span>
                        <span class="text-zinc-400 text-xs ml-1.5">by {group.artist}</span>
                      </div>
                    </button>
                    <div class="flex items-center gap-2.5 flex-shrink-0 ml-3">
                      <span class="text-[11px] font-mono text-zinc-400">{group.track_count} copies</span>
                      <span class="text-[11px] font-mono text-emerald-400 font-semibold">{formatBytes(group.reclaimable_bytes)} saveable</span>
                      <button
                        onclick={() => handleSweepDuplicates([group.group_id])}
                        disabled={sweepLoading}
                        class="px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-700/80 hover:bg-amber-600 text-white transition-colors"
                      >
                        Sweep
                      </button>
                    </div>
                  </div>

                  {#if expandedDuplicateGroups[group.group_id]}
                    <div class="mt-2 pt-2 border-t border-white/5 flex flex-col gap-1.5 font-mono text-xs">
                      {#each group.tracks as t}
                        <div class="p-2 rounded flex items-center justify-between gap-3 {t.is_recommended ? 'bg-emerald-950/30 border border-emerald-800/40 text-emerald-200' : 'bg-black/20 text-zinc-400'}">
                          <div class="flex flex-col min-w-0 truncate">
                            <div class="flex items-center gap-2">
                              {#if t.is_recommended}
                                <span class="px-1.5 py-0.2 rounded text-[9px] bg-emerald-700 text-white font-bold uppercase">Primary (Keep)</span>
                              {:else}
                                <span class="px-1.5 py-0.2 rounded text-[9px] bg-zinc-800 text-zinc-400 font-bold uppercase">Duplicate</span>
                              {/if}
                              <span class="font-semibold text-white truncate">{t.album}</span>
                              {#if t.has_collision_suffix}
                                <span class="text-[10px] text-amber-400 font-bold">_coll_ collision file</span>
                              {/if}
                            </div>
                            <span class="text-[10px] text-zinc-500 truncate mt-0.5">{t.local_path}</span>
                          </div>
                          <div class="flex items-center gap-3 flex-shrink-0 text-[11px]">
                            <span class="text-zinc-400">{t.format}</span>
                            <span class="font-bold text-zinc-300">{formatBytes(t.file_size)}</span>
                            {#if t.playlists?.length}
                              <span class="text-[10px] px-1.5 py-0.5 rounded bg-amber-950/60 text-amber-300 border border-amber-800/40">
                                {t.playlists.length} pl
                              </span>
                            {/if}
                          </div>
                        </div>
                      {/each}
                    </div>
                  {/if}
                </div>
              {/each}
            </div>
          </div>
        {/if}

        <!-- Issue Detail Feed -->
        {#if auditReport?.missing_files?.length}
          <div class="p-5 rounded-2xl border border-red-900/50 bg-red-950/20">
            <h4 class="text-xs font-bold text-red-300 uppercase tracking-wider mb-3">
              Missing Track Files ({auditReport.missing_files.length})
            </h4>
            <div class="flex flex-col gap-2 max-h-60 overflow-y-auto font-mono text-xs">
              {#each auditReport.missing_files as item}
                <div class="p-2.5 rounded bg-black/40 flex items-center justify-between text-zinc-300">
                  <div class="flex flex-col min-w-0 pr-4">
                    <span class="font-bold text-white truncate">{item.title} — {item.artist}</span>
                    <span class="text-[10px] text-zinc-500 truncate">{item.local_path}</span>
                  </div>
                  <span class="text-[10px] text-red-400 px-2 py-0.5 rounded bg-red-950 border border-red-800">
                    Missing on disk
                  </span>
                </div>
              {/each}
            </div>
          </div>
        {/if}

        {#if auditReport?.orphaned_files?.length}
          <div class="p-5 rounded-2xl border border-amber-900/50 bg-amber-950/20">
            <h4 class="text-xs font-bold text-amber-300 uppercase tracking-wider mb-3">
              Untracked Audio Files on Disk ({auditReport.orphaned_files.length})
            </h4>
            <div class="flex flex-col gap-2 max-h-60 overflow-y-auto font-mono text-xs">
              {#each auditReport.orphaned_files as item}
                <div class="p-2.5 rounded bg-black/40 flex items-center justify-between text-zinc-300">
                  <div class="flex flex-col min-w-0 pr-4">
                    <span class="font-bold text-white truncate">{item.name}</span>
                    <span class="text-[10px] text-zinc-500 truncate">{item.relative_path}</span>
                  </div>
                  <span class="text-[10px] text-zinc-400">
                    {formatBytes(item.size)}
                  </span>
                </div>
              {/each}
            </div>
          </div>
        {/if}

        {#if integrityReport?.corrupted?.length}
          <div class="p-5 rounded-2xl border border-red-900/50 bg-red-950/20">
            <h4 class="text-xs font-bold text-red-300 uppercase tracking-wider mb-3">
              Corrupted FLAC Audio Files ({integrityReport.corrupted.length})
            </h4>
            <div class="flex flex-col gap-2 max-h-60 overflow-y-auto font-mono text-xs">
              {#each integrityReport.corrupted as item}
                <div class="p-2.5 rounded bg-black/40 flex flex-col gap-1 text-zinc-300">
                  <div class="flex items-center justify-between">
                    <span class="font-bold text-white">{item.title} — {item.artist}</span>
                    <span class="text-[10px] text-red-400 font-bold">Corrupted</span>
                  </div>
                  <span class="text-[10px] text-zinc-500 truncate">{item.local_path}</span>
                  <span class="text-[10px] text-red-300 bg-red-950/60 p-1 rounded font-mono">{item.error}</span>
                </div>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    {/if}
  </div>
</div>

<!-- Lyrics Modal -->
{#if activeLyricsTrack}
  <LyricsModal
    track={activeLyricsTrack}
    onclose={() => (activeLyricsTrack = null)}
  />
{/if}

<!-- DAP Export Modal -->
{#if dapExportPlaylist}
  <DapExportModal
    playlistName={dapExportPlaylist}
    trackCount={dapExportTrackCount}
    onclose={() => (dapExportPlaylist = null)}
  />
{/if}

{#if showPlaylistImportModal}
  <PlaylistImportModal
    onclose={() => (showPlaylistImportModal = false)}
    onstartRip={() => loadLibraryData()}
  />
{/if}

{#if showSmartPlaylistModal}
  <SmartPlaylistModal
    editingPlaylist={editingSmartPlaylist}
    onclose={() => (showSmartPlaylistModal = false)}
    onsaved={(sp) => {
      loadLibraryData();
      selectSmartPlaylist(sp);
    }}
  />
{/if}

{#if showBatchTagModal && selectedTracksList.length > 0}
  <BatchTagModal
    tracks={selectedTracksList}
    initialCoverFocus={batchTagCoverFocus}
    onclose={() => (showBatchTagModal = false)}
    onupdated={() => {
      selectedTrackIds = new Set();
      loadLibraryData();
    }}
  />
{/if}