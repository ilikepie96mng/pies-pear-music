<script lang="ts">
  import { onMount } from "svelte";
  import { api, type Playlist } from "../api";

  interface Props {
    selectedPlaylist: string | null;
    syncingPlaylist: string | null;
    onselectPlaylist: (name: string) => void;
    onstartSync: (name: string) => void;
    onopenSettings: () => void;
  }

  let { selectedPlaylist, syncingPlaylist, onselectPlaylist, onstartSync, onopenSettings }: Props = $props();

  let playlists = $state<Playlist[]>([]);
  let showAddForm = $state(false);
  let newName = $state("");
  let newUrl = $state("");
  let adding = $state(false);

  onMount(async () => {
    playlists = await api.playlists();
    if (playlists.length > 0 && !selectedPlaylist) {
      onselectPlaylist(playlists[0].name);
    }
  });

  async function addPlaylist() {
    if (!newName.trim() || !newUrl.trim()) return;
    adding = true;
    try {
      const pl = await api.addPlaylist(newName.trim(), newUrl.trim());
      playlists = [...playlists, pl];
      newName = "";
      newUrl = "";
      showAddForm = false;
    } finally {
      adding = false;
    }
  }

  async function removePlaylist(name: string, e: MouseEvent) {
    e.stopPropagation();
    await api.deletePlaylist(name);
    playlists = playlists.filter((p) => p.name !== name);
  }
</script>

<aside class="w-[180px] min-w-[180px] bg-[#111] flex flex-col border-r border-[#1e1e1e]">
  <div class="p-4 border-b border-[#1e1e1e]">
    <div class="text-white font-bold text-[15px] tracking-tight">pies</div>
    <div class="text-[#555] text-[10px] mt-0.5">Apple Music ↓</div>
  </div>

  <nav class="p-2 border-b border-[#1e1e1e]">
    <button
      class="w-full text-left px-3 py-1.5 rounded-md text-sm text-[#888] hover:text-white hover:bg-[#1a1a1a] transition-colors"
      onclick={onopenSettings}
    >
      ⚙ Settings
    </button>
  </nav>

  <div class="px-3 pt-3 pb-1 text-[10px] text-[#555] uppercase tracking-widest">Playlists</div>

  <div class="flex-1 overflow-y-auto px-2 flex flex-col gap-0.5">
    {#each playlists as pl}
      <div class="group flex items-center rounded-md transition-colors
        {selectedPlaylist === pl.name ? 'bg-[#1a1a1a]' : 'hover:bg-[#1a1a1a]'}">
        <button
          class="flex-1 text-left px-3 py-2 text-sm truncate transition-colors
            {selectedPlaylist === pl.name ? 'text-white' : 'text-[#888] group-hover:text-white'}"
          onclick={() => onselectPlaylist(pl.name)}
          type="button"
        >{pl.name}</button>
        <button
          class="hidden group-hover:flex pr-2 text-[#555] hover:text-red-400 text-xs"
          onclick={(e) => removePlaylist(pl.name, e)}
          type="button"
          aria-label="Remove {pl.name}"
        >✕</button>
      </div>
    {/each}

    {#if showAddForm}
      <div class="px-1 py-2 flex flex-col gap-1">
        <input bind:value={newName} placeholder="Name"
          class="bg-[#1a1a1a] border border-[#333] rounded px-2 py-1 text-xs text-white w-full outline-none focus:border-[#1db954]" />
        <input bind:value={newUrl} placeholder="Apple Music URL"
          class="bg-[#1a1a1a] border border-[#333] rounded px-2 py-1 text-xs text-white w-full outline-none focus:border-[#1db954]" />
        <div class="flex gap-1">
          <button onclick={addPlaylist} disabled={adding}
            class="flex-1 bg-[#1db954] text-black text-xs rounded py-1 font-semibold disabled:opacity-50">
            {adding ? "…" : "Add"}
          </button>
          <button onclick={() => (showAddForm = false)}
            class="flex-1 text-[#888] text-xs rounded py-1 bg-[#1a1a1a]">Cancel</button>
        </div>
      </div>
    {:else}
      <button onclick={() => (showAddForm = true)}
        class="w-full text-left px-3 py-2 text-[#555] hover:text-white text-sm transition-colors">
        + Add playlist
      </button>
    {/if}
  </div>

  {#if syncingPlaylist}
    <div class="mx-2 mb-2 bg-[#1a1a1a] rounded-lg p-3 border border-[#222]">
      <div class="text-[10px] text-[#555] uppercase tracking-widest mb-1">Syncing</div>
      <div class="text-white text-xs font-medium truncate">{syncingPlaylist}</div>
      <div class="h-1 bg-[#333] rounded-full mt-2">
        <div class="h-full bg-[#1db954] rounded-full w-full animate-pulse"></div>
      </div>
    </div>
  {/if}

  <div class="p-2 border-t border-[#1e1e1e]">
    <button
      onclick={() => { for (const pl of playlists) onstartSync(pl.name); }}
      disabled={!!syncingPlaylist}
      class="w-full bg-[#1db954] text-black text-sm font-bold rounded-lg py-2 hover:bg-[#1ed760] transition-colors disabled:opacity-50"
    >
      ↻ Sync All
    </button>
  </div>
</aside>
