<script lang="ts">
  import { onMount } from "svelte";
  import Sidebar from "$lib/Sidebar.svelte";
  import SyncProgress from "$lib/SyncProgress.svelte";
  import Settings from "$lib/Settings.svelte";
  import SetupWizard from "$lib/SetupWizard.svelte";
  import Diagnostics from "$lib/Diagnostics.svelte";
  import Dashboard from "$lib/Dashboard.svelte";
  import PlaylistDetail from "$lib/PlaylistDetail.svelte";
  import { api, type Playlist } from "../api";

  type View = "playlist" | "sync" | "settings" | "setup" | "diagnostics" | "dashboard";

  let view = $state<View>("dashboard");
  let playlists = $state<Playlist[]>([]);
  let selectedName = $state<string | null>(null);
  let syncingPlaylist = $state<string | null>(null);

  let selectedPlaylist = $derived(playlists.find(p => p.name === selectedName) ?? null);

  onMount(async () => {
    playlists = await api.playlists();
  });

  function selectPlaylist(name: string) {
    selectedName = name;
    view = "playlist";
  }

  function startSync(name: string) {
    if (syncingPlaylist) return;
    syncingPlaylist = name;
    view = "sync";
  }

  async function onSyncDone() {
    syncingPlaylist = null;
    // Refresh playlist list so last_synced timestamps update
    playlists = await api.playlists();
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

<div class="flex h-screen bg-[#0f0f0f] text-white overflow-hidden select-none">
  <Sidebar
    {playlists}
    selectedName={selectedName}
    {syncingPlaylist}
    onselectPlaylist={selectPlaylist}
    onstartSync={startSync}
    onopenSettings={() => (view = "settings")}
    onopenSetup={() => (view = "setup")}
    onopenDiagnostics={() => (view = "diagnostics")}
    onopenDashboard={() => (view = "dashboard")}
    onplaylistAdded={onPlaylistAdded}
  />
  <main class="flex-1 overflow-hidden">
    {#if view === "setup"}
      <SetupWizard ondone={() => (view = "dashboard")} />
    {:else if view === "diagnostics"}
      <Diagnostics onopenSettings={() => (view = "settings")} />
    {:else if view === "dashboard"}
      <Dashboard
        onstartSync={startSync}
        onselectPlaylist={selectPlaylist}
        onopenDiagnostics={() => (view = "diagnostics")}
      />
    {:else if view === "playlist" && selectedPlaylist}
      {#key selectedName}
        <PlaylistDetail
          playlist={selectedPlaylist}
          syncing={syncingPlaylist === selectedPlaylist.name}
          onstartSync={startSync}
          onrenamed={onPlaylistRenamed}
          ondeleted={onPlaylistDeleted}
          onupdated={onPlaylistUpdated}
        />
      {/key}
    {:else if view === "sync" && syncingPlaylist}
      <SyncProgress playlistName={syncingPlaylist} ondone={onSyncDone} />
    {:else if view === "settings"}
      <Settings />
    {:else}
      <div class="flex items-center justify-center h-full text-zinc-600 text-sm">
        Select a playlist from the sidebar
      </div>
    {/if}
  </main>
</div>
