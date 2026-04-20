<script lang="ts">
  import { api, type Playlist } from "../api";
  import QueueIndicator from "./QueueIndicator.svelte";

  interface Props {
    playlists: Playlist[];
    selectedName: string | null;
    onselectPlaylist: (name: string) => void;
    onstartSync: (name: string) => void;
    onopenSettings: () => void;
    onopenSetup: () => void;
    onopenDiagnostics: () => void;
    onopenDashboard: () => void;
    onopenDownload: () => void;
    onplaylistAdded: (pl: Playlist) => void;
  }

  let {
    playlists, selectedName,
    onselectPlaylist, onstartSync,
    onopenSettings, onopenSetup, onopenDiagnostics, onopenDashboard, onopenDownload,
    onplaylistAdded,
  }: Props = $props();

  let showAddForm = $state(false);
  let newName = $state("");
  let newUrl = $state("");
  let adding = $state(false);
  let addError = $state<string | null>(null);

  async function addPlaylist() {
    if (!newName.trim() || !newUrl.trim()) return;
    adding = true;
    addError = null;
    try {
      const pl = await api.addPlaylist(newName.trim(), newUrl.trim());
      onplaylistAdded(pl);
      newName = "";
      newUrl = "";
      showAddForm = false;
      onselectPlaylist(pl.name);
    } catch (e) {
      addError = String(e);
    } finally {
      adding = false;
    }
  }


</script>

<aside class="w-[180px] min-w-[180px] bg-[#111] flex flex-col border-r border-[#1e1e1e]">
  <div class="p-4 border-b border-[#1e1e1e]">
    <div class="text-white font-bold text-[15px] tracking-tight">pies</div>
    <div class="text-[#555] text-[10px] mt-0.5">music sync</div>
  </div>

  <nav class="p-2 border-b border-[#1e1e1e] flex flex-col gap-0.5">
    <button
      class="w-full text-left px-3 py-1.5 rounded-md text-sm text-[#888] hover:text-white hover:bg-[#1a1a1a] transition-colors"
      onclick={onopenDashboard}
    >
      ▦ Dashboard
    </button>
    <button
      class="w-full text-left px-3 py-1.5 rounded-md text-sm text-[#888] hover:text-white hover:bg-[#1a1a1a] transition-colors"
      onclick={onopenDiagnostics}
    >
      ⊕ Diagnostics
    </button>
    <button
      class="w-full text-left px-3 py-1.5 rounded-md text-sm text-[#888] hover:text-white hover:bg-[#1a1a1a] transition-colors"
      onclick={onopenSettings}
    >
      ⚙ Settings
    </button>
    <button
      class="w-full text-left px-3 py-1.5 rounded-md text-sm text-[#888] hover:text-white hover:bg-[#1a1a1a] transition-colors"
      onclick={onopenSetup}
    >
      ◆ Setup
    </button>
    <button
      class="w-full text-left px-3 py-1.5 rounded-md text-sm text-[#888] hover:text-white hover:bg-[#1a1a1a] transition-colors"
      onclick={onopenDownload}
    >
      ↓ Download
    </button>
  </nav>

  <div class="px-3 pt-3 pb-1 text-[10px] text-[#555] uppercase tracking-widest">Playlists</div>

  <div class="flex-1 overflow-y-auto px-2 flex flex-col gap-0.5">
    {#each playlists as pl}
      <button
        class="w-full text-left px-3 py-2 rounded-md text-sm truncate transition-colors flex items-center gap-1.5
          {selectedName === pl.name ? 'bg-[#1a1a1a] text-white' : 'text-[#888] hover:text-white hover:bg-[#1a1a1a]'}"
        onclick={() => onselectPlaylist(pl.name)}
        type="button"
      >
        {#if pl.paused}
          <span class="text-amber-600 text-[9px] flex-shrink-0">⏸</span>
        {/if}
        <span class="truncate">{pl.name}</span>
      </button>
    {/each}

    {#if showAddForm}
      <div class="px-1 py-2 flex flex-col gap-1">
        <input bind:value={newName} placeholder="Name"
          class="bg-[#1a1a1a] border border-[#333] rounded px-2 py-1 text-xs text-white w-full outline-none focus:border-[#1db954]" />
        <input bind:value={newUrl} placeholder="Playlist URL"
          class="bg-[#1a1a1a] border border-[#333] rounded px-2 py-1 text-xs text-white w-full outline-none focus:border-[#1db954]" />
        {#if addError}
          <div class="text-red-400 text-[10px] bg-red-950 border border-red-800 rounded px-2 py-1 break-all">{addError}</div>
        {/if}
        <div class="flex gap-1">
          <button onclick={addPlaylist} disabled={adding}
            class="flex-1 bg-[#1db954] text-black text-xs rounded py-1 font-semibold disabled:opacity-50">
            {adding ? "…" : "Add"}
          </button>
          <button onclick={() => { showAddForm = false; addError = null; }}
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

  <QueueIndicator />

  <div class="p-2 border-t border-[#1e1e1e]">
    <button
      onclick={() => { const first = playlists.find(p => !p.paused); if (first) onstartSync(first.name); }}
      disabled={playlists.every(p => p.paused)}
      class="w-full bg-[#1db954] text-black text-sm font-bold rounded-lg py-2 hover:bg-[#1ed760] transition-colors disabled:opacity-50"
    >
      ↻ Sync All
    </button>
  </div>
</aside>
