<script lang="ts">
  import { player } from "./player.svelte";
  import LyricsModal from "./LyricsModal.svelte";

  let showLyrics = $state(false);

  function formatTime(secs: number): string {
    if (!secs || isNaN(secs) || secs < 0) return "0:00";
    const mins = Math.floor(secs / 60);
    const remaining = Math.floor(secs % 60);
    return `${mins}:${remaining < 10 ? "0" : ""}${remaining}`;
  }

  function handleSeek(e: Event) {
    const input = e.target as HTMLInputElement;
    player.seek(Number(input.value));
  }

  function handleVolume(e: Event) {
    const input = e.target as HTMLInputElement;
    player.setVolume(Number(input.value));
  }

  function thumbUrl(url: string | null | undefined, size: string): string {
    if (!url) return "";
    return url.replace("{w}x{h}", size);
  }
</script>

{#if player.currentTrack}
  <footer
    class="fixed bottom-0 left-0 right-0 h-20 px-6 flex items-center justify-between z-40 border-t backdrop-blur-xl shadow-2xl select-none"
    style="background:rgba(18,16,22,0.88);border-color:var(--border);color:var(--text-primary);"
  >
    <!-- Left: Track Metadata & Artwork -->
    <div class="flex items-center gap-3 w-1/4 min-w-[200px]">
      <div class="w-12 h-12 rounded-lg overflow-hidden bg-black/50 flex-shrink-0 relative group">
        {#if player.currentTrack.artwork_url}
          <img
            src={thumbUrl(player.currentTrack.artwork_url, "128x128")}
            alt=""
            class="w-full h-full object-cover"
          />
        {:else}
          <div class="w-full h-full flex items-center justify-center text-zinc-500 text-lg">♫</div>
        {/if}
      </div>

      <div class="flex flex-col min-w-0">
        <div class="flex items-center gap-2">
          <span class="font-bold text-xs text-white truncate max-w-[180px]">{player.currentTrack.title}</span>
          <span class="text-[9px] px-1.5 py-0.5 rounded font-mono font-bold bg-amber-400/20 text-amber-300 border border-amber-400/30">
            {player.currentTrack.format || "ALAC"}
          </span>
        </div>
        <span class="text-[11px] text-zinc-400 truncate max-w-[180px]">{player.currentTrack.artist}</span>
      </div>
    </div>

    <!-- Center: Playback Controls & Progress Bar -->
    <div class="flex flex-col items-center gap-1.5 w-2/4 max-w-xl">
      <div class="flex items-center gap-4">
        <button
          onclick={() => player.seek(Math.max(0, player.currentTime - 10))}
          class="text-xs text-zinc-400 hover:text-white transition-colors"
          title="Rewind 10s"
        >
          ⏮ 10s
        </button>

        <button
          onclick={() => player.togglePlay()}
          class="w-10 h-10 rounded-full flex items-center justify-center font-bold text-base transition-transform active:scale-95 shadow-lg"
          style="background:var(--accent);color:black;"
          aria-label={player.isPlaying ? "Pause" : "Play"}
        >
          {player.isPlaying ? "❚❚" : "▶"}
        </button>

        <button
          onclick={() => player.seek(Math.min(player.duration, player.currentTime + 10))}
          class="text-xs text-zinc-400 hover:text-white transition-colors"
          title="Forward 10s"
        >
          10s ⏭
        </button>
      </div>

      <!-- Scrubber -->
      <div class="flex items-center gap-2.5 w-full">
        <span class="text-[10px] font-mono text-zinc-400 min-w-[32px] text-right">
          {formatTime(player.currentTime)}
        </span>
        <input
          type="range"
          min="0"
          max={player.duration || 100}
          value={player.currentTime}
          oninput={handleSeek}
          class="flex-1 h-1 bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-amber-400"
        />
        <span class="text-[10px] font-mono text-zinc-400 min-w-[32px]">
          {formatTime(player.duration)}
        </span>
      </div>
    </div>

    <!-- Right: Volume & Extra Utilities -->
    <div class="flex items-center justify-end gap-4 w-1/4 min-w-[180px]">
      <button
        onclick={() => (showLyrics = true)}
        class="text-xs px-2.5 py-1 rounded-lg border font-medium transition-colors hover:border-amber-400"
        style="background:var(--surface);border-color:var(--border);color:var(--text-secondary);"
        title="Open synchronized lyrics"
      >
        🎤 Lyrics
      </button>

      <div class="flex items-center gap-2">
        <button
          onclick={() => player.toggleMute()}
          class="text-xs text-zinc-400 hover:text-white"
        >
          {player.isMuted || player.volume === 0 ? "🔇" : "🔊"}
        </button>
        <input
          type="range"
          min="0"
          max="1"
          step="0.05"
          value={player.isMuted ? 0 : player.volume}
          oninput={handleVolume}
          class="w-20 h-1 bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-amber-400"
        />
      </div>
    </div>
  </footer>

  {#if showLyrics}
    <LyricsModal
      track={{
        track_id: player.currentTrack.track_id,
        title: player.currentTrack.title,
        artist: player.currentTrack.artist,
        album: player.currentTrack.album,
        local_path: player.currentTrack.local_path,
        artwork_url: player.currentTrack.artwork_url,
      }}
      onclose={() => (showLyrics = false)}
    />
  {/if}
{/if}
