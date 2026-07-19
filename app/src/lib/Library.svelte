<script lang="ts">
  import { api, type Track } from "../api";

  interface Props { playlistName: string }
  let { playlistName }: Props = $props();

  let tracks = $state<Track[]>([]);
  let artUrls = $state<Record<string, string>>({});
  let loading = $state(true);

  async function load(name: string) {
    loading = true;
    tracks = [];
    artUrls = {};
    const lib = await api.library();
    tracks = lib[name] ?? [];
    const newUrls: Record<string, string> = {};
    for (const t of tracks) {
      const url = await api.trackArtUrl(t.local_path);
      if (url) newUrls[t.track_id] = url;
    }
    artUrls = newUrls;
    loading = false;
  }

  // $effect runs on mount and whenever playlistName changes
  $effect(() => { load(playlistName); });
</script>

<div class="p-6">
  <div class="flex items-baseline gap-3 mb-6">
    <h1 class="text-white text-2xl font-bold">{playlistName}</h1>
    <span class="text-zinc-500 text-sm">{tracks.length} tracks</span>
  </div>

  {#if loading}
    <div class="text-zinc-600 text-sm">Loading…</div>
  {:else if tracks.length === 0}
    <div class="text-zinc-600 text-sm">No tracks yet. Sync this playlist to download them.</div>
  {:else}
    <div class="grid gap-4" style="grid-template-columns: repeat(auto-fill, minmax(140px, 1fr))">
      {#each tracks as track (track.track_id)}
        <div class="bg-[#1a1a1a] rounded-xl overflow-hidden hover:bg-[#222] transition-colors cursor-default">
          <div class="aspect-square bg-[#111] flex items-center justify-center overflow-hidden">
            {#if artUrls[track.track_id]}
              <img src={artUrls[track.track_id]} alt={track.album} class="w-full h-full object-cover" />
            {:else}
              <span class="text-3xl opacity-10">♪</span>
            {/if}
          </div>
          <div class="p-3">
            <div class="text-white text-xs font-semibold truncate">{track.title}</div>
            <div class="text-zinc-500 text-xs truncate mt-0.5">{track.artist}</div>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
