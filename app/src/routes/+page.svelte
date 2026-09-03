<script lang="ts">
  import { onMount } from "svelte";
  import Sidebar from "$lib/Sidebar.svelte";
  import SyncProgress from "$lib/SyncProgress.svelte";
  import Settings from "$lib/Settings.svelte";
  import SetupWizard from "$lib/SetupWizard.svelte";
  import Diagnostics from "$lib/Diagnostics.svelte";
  import Dashboard from "$lib/Dashboard.svelte";
  import Home from "$lib/Home.svelte";
  import PlaylistDetail from "$lib/PlaylistDetail.svelte";
  import Download from "$lib/Download.svelte";
  import About from "$lib/About.svelte";
  import DataControls from "$lib/DataControls.svelte";
  import StreamingGraveyard from "$lib/StreamingGraveyard.svelte";
  import Library from "$lib/Library.svelte";
  import PlaylistCreator from "$lib/PlaylistCreator.svelte";
  import PlaylistImportModal from "$lib/PlaylistImportModal.svelte";
  import QuickStartModal from "$lib/QuickStartModal.svelte";
  import LoginModal from "$lib/LoginModal.svelte";
  import PlayerBar from "$lib/PlayerBar.svelte";
  import { player } from "$lib/player.svelte";
  import { api, type Playlist } from "../api";

  type View = "playlist" | "sync" | "settings" | "setup" | "diagnostics" | "dashboard" | "download" | "home" | "about" | "data" | "graveyard" | "library" | "creator" | "import";

  let view = $state<View>("home");
  let playlists = $state<Playlist[]>([]);
  let selectedName = $state<string | null>(null);
  let syncingPlaylist = $state<string | null>(null);
  let dashboardKey = $state(0);
  let showImportModal = $state(false);
  let showTourModal = $state(false);

  // Authentication State
  let authRequired = $state(false);
  let authenticated = $state(true);
  let authChecked = $state(false);

  let selectedPlaylist = $derived(playlists.find(p => p.name === selectedName) ?? null);

  async function checkAuthAndLoad() {
    try {
      const status = await api.authStatus();
      authRequired = status.auth_required;
      authenticated = status.authenticated;
    } catch {
      authRequired = false;
      authenticated = true;
    } finally {
      authChecked = true;
    }

    if (authenticated) {
      api.playlists().then(pl => { playlists = pl; }).catch(() => {});
    }
  }

  onMount(() => {
    checkAuthAndLoad();

    const handleCreated = (e: Event) => {
      api.playlists().then(pl => { playlists = pl; });
      const detail = (e as CustomEvent).detail;
      if (detail?.name) {
        selectedName = detail.name;
        view = "playlist";
      }
    };
    window.addEventListener("playlist-created", handleCreated);
    return () => window.removeEventListener("playlist-created", handleCreated);
  });

  function selectPlaylist(name: string) {
    selectedName = name;
    view = "playlist";
  }

  function startSync(name: string) {
    syncingPlaylist = name;
    view = "sync";
  }

  async function onSyncDone() {
    syncingPlaylist = null;
    playlists = await api.playlists();
    dashboardKey++;
    view = selectedName ? "playlist" : "dashboard";
  }

  function onPlaylistAdded(pl: Playlist) {
    playlists = [...playlists, pl];
  }

  function onPlaylistDeleted(name: string) {
    playlists = playlists.filter(p => p.name !== name);
    if (selectedName === name) { selectedName = null; view = "dashboard"; }
  }

  function onPlaylistRenamed(oldName: string, newName: string) {
    selectedName = newName;
  }

  function onPlaylistUpdated(updated: Playlist) {
    playlists = playlists.map(p => p.name === updated.name ? updated : p);
  }
</script>

<div class="flex h-screen overflow-hidden select-none relative {player.currentTrack ? 'pb-20' : ''}" style="background:var(--bg);color:var(--text-primary);">
  <Sidebar
    {playlists}
    selectedName={selectedName}
    onselectPlaylist={selectPlaylist}
    onstartSync={startSync}
    onopenSettings={() => (view = "settings")}
    onopenSetup={() => (view = "setup")}
    onopenDiagnostics={() => (view = "diagnostics")}
    onopenHome={() => (view = "home")}
    onopenLibrary={() => (view = "library")}
    onopenCreator={() => (view = "creator")}
    onopenImport={() => (showImportModal = true)}
    onopenDashboard={() => (view = "dashboard")}
    onopenDownload={() => (view = "download")}
    onopenGraveyard={() => (view = "graveyard")}
    onopenAbout={() => (view = "about")}
    onopenData={() => (view = "data")}
    onopenTour={() => (showTourModal = true)}
    onopenSync={syncingPlaylist ? () => (view = "sync") : undefined}
    onplaylistAdded={onPlaylistAdded}
  />
  {#if authRequired && !authenticated}
    <LoginModal onsuccess={checkAuthAndLoad} />
  {:else if !authChecked}
    <div class="flex-1 flex items-center justify-center">
      <div class="text-zinc-500 text-sm animate-pulse">Loading workstation...</div>
    </div>
  {:else}
    <main class="flex-1 overflow-hidden">
      <!-- SyncProgress stays mounted while a sync is in-flight so it doesn't remount and re-queue -->
      {#if syncingPlaylist}
        <div class="h-full" class:hidden={view !== "sync"}>
          {#key syncingPlaylist}
            <SyncProgress playlistName={syncingPlaylist} ondone={onSyncDone} />
          {/key}
        </div>
      {/if}

      <!-- Download workstation stays mounted so active streaming downloads continue when browsing away and view state is preserved -->
      <div class="h-full" class:hidden={view !== "download"}>
        <Download />
      </div>

      <!-- Other page views -->
      <div class="h-full" class:hidden={view === "sync" || view === "download"}>
        {#if view === "setup"}
          <SetupWizard ondone={() => (view = "dashboard")} />
        {:else if view === "diagnostics"}
          <Diagnostics onopenSettings={() => (view = "settings")} />
        {:else if view === "home"}
          <Home onopenSettings={() => (view = "settings")} />
        {:else if view === "library"}
          <Library
            onselectPlaylist={selectPlaylist}
            onstartSync={startSync}
          />
        {:else if view === "creator"}
          <PlaylistCreator
            onplaylistSaved={(pl: Playlist) => {
              onPlaylistAdded(pl);
              selectedName = pl.name;
              view = "playlist";
            }}
            onopenDownload={() => (view = "download")}
          />
        {:else if view === "dashboard"}
          {#key dashboardKey}
            <Dashboard
              onstartSync={startSync}
              onselectPlaylist={selectPlaylist}
              onopenDiagnostics={() => (view = "diagnostics")}
              onopenSettings={() => (view = "settings")}
            />
          {/key}
        {:else if view === "playlist" && selectedPlaylist}
          {#key selectedName}
            <PlaylistDetail
              playlist={selectedPlaylist}
              onstartSync={startSync}
              onrenamed={onPlaylistRenamed}
              ondeleted={onPlaylistDeleted}
              onupdated={onPlaylistUpdated}
            />
          {/key}
        {:else if view === "settings"}
          <Settings />
        {:else if view === "graveyard"}
          <StreamingGraveyard onopenSettings={() => (view = "settings")} />
        {:else if view === "about"}
          <About />
        {:else if view === "data"}
          <DataControls />
        {:else}
          <div class="flex items-center justify-center h-full text-zinc-600 text-sm">
            Select a playlist from the sidebar
          </div>
        {/if}
      </div>
    </main>

    {#if showImportModal}
      <PlaylistImportModal
        onclose={() => (showImportModal = false)}
        onstartRip={(matches) => {
          showImportModal = false;
          view = "download";
        }}
      />
    {/if}

    {#if showTourModal}
      <QuickStartModal
        onclose={() => (showTourModal = false)}
        onopenSetup={() => { showTourModal = false; view = "setup"; }}
        onopenSettings={() => { showTourModal = false; view = "settings"; }}
        onopenCreator={() => { showTourModal = false; view = "creator"; }}
        onopenImport={() => { showTourModal = false; showImportModal = true; }}
        onopenLibrary={() => { showTourModal = false; view = "library"; }}
      />
    {/if}
  {/if}

  <PlayerBar />
</div>
