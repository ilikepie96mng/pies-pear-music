<script lang="ts">
  import { onMount } from "svelte";
  import type { LibraryTrack } from "../api";
  import { player } from "./player.svelte";

  interface Props {
    tracks: LibraryTrack[];
    rowHeight?: number;
    onfilterArtist?: (artist: string) => void;
    onfilterAlbum?: (album: string) => void;
    onfilterPlaylist?: (playlist: string) => void;
    onopenLyrics?: (track: LibraryTrack) => void;
    onrevealTrack?: (localPath: string) => void;
  }

  let {
    tracks,
    rowHeight = 52,
    onfilterArtist,
    onfilterAlbum,
    onfilterPlaylist,
    onopenLyrics,
    onrevealTrack,
  }: Props = $props();

  let containerEl = $state<HTMLDivElement | null>(null);
  let scrollTop = $state(0);
  let viewportHeight = $state(600);

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

  function handleScroll(e: Event) {
    const target = e.currentTarget as HTMLDivElement;
    scrollTop = target.scrollTop;
  }

  onMount(() => {
    if (containerEl) {
      viewportHeight = containerEl.clientHeight;
      const resizeObserver = new ResizeObserver((entries) => {
        for (const entry of entries) {
          viewportHeight = entry.contentRect.height;
        }
      });
      resizeObserver.observe(containerEl);
      return () => resizeObserver.disconnect();
    }
  });

  const buffer = 5;
  let totalHeight = $derived(tracks.length * rowHeight);
  let startIndex = $derived(Math.max(0, Math.floor(scrollTop / rowHeight) - buffer));
  let endIndex = $derived(Math.min(tracks.length, Math.ceil((scrollTop + viewportHeight) / rowHeight) + buffer));
  let visibleTracks = $derived(
    tracks.slice(startIndex, endIndex).map((track, i) => ({
      track,
      index: startIndex + i,
      top: (startIndex + i) * rowHeight,
    }))
  );

  function playTrack(track: LibraryTrack) {
    player.playTrack({
      track_id: track.track_id,
      title: track.title,
      artist: track.artist,
      album: track.album,
      local_path: track.local_path,
      artwork_url: track.artwork_url,
      format: track.format,
    });
  }
</script>

<div
  bind:this={containerEl}
  onscroll={handleScroll}
  class="w-full h-full overflow-y-auto border rounded-xl relative"
  style="border-color:var(--border);background:var(--surface);"
>
  <!-- Table Header Sticky -->
  <div
    class="sticky top-0 z-10 grid grid-cols-12 gap-2 py-3 px-4 text-zinc-400 font-medium uppercase text-[10px] tracking-wider border-b backdrop-blur-md"
    style="border-color:var(--border);background:rgba(18,16,22,0.92);"
  >
    <div class="col-span-1 text-center">#</div>
    <div class="col-span-4">Title & Artist</div>
    <div class="col-span-3 hidden md:block">Album</div>
    <div class="col-span-2">Format</div>
    <div class="col-span-2 text-right">Actions</div>
  </div>

  <!-- Virtual Scroll Content Area -->
  <div class="relative w-full" style="height:{totalHeight}px;">
    {#each visibleTracks as item (item.track.track_id)}
      <div
        role="row"
        tabindex="0"
        onkeydown={(e) => { if (e.key === "Enter") playTrack(item.track); }}
        ondblclick={() => playTrack(item.track)}
        class="absolute left-0 right-0 grid grid-cols-12 gap-2 items-center px-4 hover:bg-white/[0.04] transition-colors border-b text-xs select-none group cursor-pointer"
        style="top:{item.top}px;height:{rowHeight}px;border-color:var(--border);"
      >
        <!-- Index & Artwork -->
        <div class="col-span-1 flex items-center justify-center">
          <div class="w-8 h-8 rounded overflow-hidden bg-black/40 flex items-center justify-center flex-shrink-0 relative">
            {#if item.track.artwork_url}
              <img
                src={thumbUrl(item.track.artwork_url, "64x64")}
                alt=""
                class="w-full h-full object-cover"
                loading="lazy"
                onerror={(e) => ((e.currentTarget as HTMLElement).style.display = "none")}
              />
            {:else}
              <span class="text-zinc-600 text-[10px]">♪</span>
            {/if}
            <button
              onclick={(e) => { e.stopPropagation(); playTrack(item.track); }}
              class="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 flex items-center justify-center text-white text-xs transition-opacity"
              title="Play track"
            >
              ▶
            </button>
          </div>
        </div>

        <!-- Title & Artist -->
        <div class="col-span-4 min-w-0 pr-2">
          <div class="font-semibold text-white truncate">{item.track.title}</div>
          <button
            onclick={(e) => { e.stopPropagation(); onfilterArtist?.(item.track.artist); }}
            class="text-zinc-400 text-[11px] truncate text-left hover:text-amber-400 transition-colors"
          >
            {item.track.artist}
          </button>
        </div>

        <!-- Album -->
        <div class="col-span-3 hidden md:block min-w-0 pr-2">
          <button
            onclick={(e) => { e.stopPropagation(); onfilterAlbum?.(item.track.album); }}
            class="text-zinc-400 hover:text-amber-400 transition-colors truncate text-left"
          >
            {item.track.album}
          </button>
        </div>

        <!-- Format & Size -->
        <div class="col-span-2 flex items-center gap-1.5 flex-wrap">
          <span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-300">
            {item.track.format}
          </span>
          {#if item.track.has_lyrics}
            <span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-300 font-medium">
              LRC
            </span>
          {/if}
          {#if !item.track.exists_on_disk}
            <span class="text-[10px] px-1.5 py-0.5 rounded bg-red-950 text-red-300 font-bold">
              Missing
            </span>
          {/if}
        </div>

        <!-- Actions -->
        <div class="col-span-2 flex items-center justify-end gap-1.5 opacity-80 group-hover:opacity-100 transition-opacity">
          {#if item.track.has_lyrics}
            <button
              onclick={(e) => { e.stopPropagation(); onopenLyrics?.(item.track); }}
              class="px-2 py-1 text-[11px] rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition-colors"
              title="View lyrics"
            >
              🎤
            </button>
          {/if}
          {#if item.track.local_path && item.track.exists_on_disk}
            <button
              onclick={(e) => { e.stopPropagation(); onrevealTrack?.(item.track.local_path); }}
              class="px-2 py-1 text-[11px] rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition-colors"
              title="Reveal in file explorer"
            >
              📁
            </button>
          {/if}
        </div>
      </div>
    {/each}
  </div>
</div>
