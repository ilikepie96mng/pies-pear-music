<script lang="ts">
  import Sidebar from "$lib/Sidebar.svelte";
  import Library from "$lib/Library.svelte";
  import SyncProgress from "$lib/SyncProgress.svelte";
  import Settings from "$lib/Settings.svelte";

  type View = "library" | "sync" | "settings";

  let view = $state<View>("library");
  let selectedPlaylist = $state<string | null>(null);
  let syncingPlaylist = $state<string | null>(null);

  function selectPlaylist(name: string) {
    selectedPlaylist = name;
    view = "library";
  }

  function startSync(name: string) {
    syncingPlaylist = name;
    view = "sync";
  }

  function onSyncDone() {
    syncingPlaylist = null;
    view = "library";
  }
</script>

<div class="flex h-screen bg-[#0f0f0f] text-white overflow-hidden select-none">
  <Sidebar
    {selectedPlaylist}
    {syncingPlaylist}
    onselectPlaylist={selectPlaylist}
    onstartSync={startSync}
    onopenSettings={() => (view = "settings")}
  />
  <main class="flex-1 overflow-auto">
    {#if view === "library" && selectedPlaylist}
      <Library playlistName={selectedPlaylist} />
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
