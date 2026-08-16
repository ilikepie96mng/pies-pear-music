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
  import { api, type Playlist } from "../api";

  type View = "playlist" | "sync" | "settings" | "setup" | "diagnostics" | "dashboard" | "download" | "home" | "about" | "data" | "graveyard" | "library";

  let view = $state<View>("home");
  let playlists = $state<Playlist[]>([]);
  let selectedName = $state<string | null>(null);
  let syncingPlaylist = $state<string | null>(null);
  let dashboardKey = $state(0);

  let selectedPlaylist = $derived(playlists.find(p => p.name === selectedName) ?? null);

  onMount(async () => {
    playlists = await api.playlists();
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

<div class="flex h-screen overflow-hidden select-none" style="background:var(--bg);color:var(--text-primary);">
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
    onopenDashboard={() => (view = "dashboard")}
    onopenDownload={() => (view = "download")}
    onopenGraveyard={() => (view = "graveyard")}
    onopenAbout={() => (view = "about")}
    onopenData={() => (view = "data")}
    onopenSync={syncingPlaylist ? () => (view = "sync") : undefined}
    onplaylistAdded={onPlaylistAdded}
  />
  <main class="flex-1 overflow-hidden">
    <!-- SyncProgress stays mounted while a sync is in-flight so it doesn't remount and re-queue -->
    {#if syncingPlaylist}
      <div class="h-full" class:hidden={view !== "sync"}>
        {#key syncingPlaylist}
          <SyncProgress playlistName={syncingPlaylist} ondone={onSyncDone} />
        {/key}
      </div>
    {/if}
    <div class="h-full" class:hidden={view === "sync"}>
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
      {:else if view === "dashboard"}
        {#key dashboardKey}
          <Dashboard
            onstartSync={startSync}
            onselectPlaylist={selectPlaylist}
            onopenDiagnostics={() => (view = "diagnostics")}
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
      {:else if view === "download"}
        <Download />
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
</div>
