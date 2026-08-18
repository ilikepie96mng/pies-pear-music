<script lang="ts">
  import { onMount } from "svelte";
  import { player } from "./player.svelte";
  import { api } from "../api";
  import LyricsModal from "./LyricsModal.svelte";

  let showLyrics = $state(false);
  let canvasRef = $state<HTMLCanvasElement | null>(null);
  let waveformData = $state<number[] | null>(null);
  let isLoadingWaveform = $state(false);
  let isHovering = $state(false);
  let hoverFraction = $state(0);
  let hoverX = $state(0);
  let isDragging = $state(false);
  let currentTrackId = $state<string | null>(null);

  function formatTime(secs: number): string {
    if (!secs || isNaN(secs) || secs < 0) return "0:00";
    const mins = Math.floor(secs / 60);
    const remaining = Math.floor(secs % 60);
    return `${mins}:${remaining < 10 ? "0" : ""}${remaining}`;
  }

  function handleVolume(e: Event) {
    const input = e.target as HTMLInputElement;
    player.setVolume(Number(input.value));
  }

  function thumbUrl(url: string | null | undefined, size: string): string {
    if (!url) return "";
    return url.replace("{w}x{h}", size);
  }

  // Fetch waveform when current track changes
  $effect(() => {
    const track = player.currentTrack;
    if (!track) {
      waveformData = null;
      currentTrackId = null;
      return;
    }

    if (track.track_id === currentTrackId && waveformData !== null) {
      return;
    }

    currentTrackId = track.track_id;
    isLoadingWaveform = true;

    api.getWaveform(track.track_id, 120)
      .then((res) => {
        if (currentTrackId === track.track_id) {
          waveformData = res.peaks;
          isLoadingWaveform = false;
        }
      })
      .catch((err) => {
        console.warn("Waveform extraction/fetch error:", err);
        if (currentTrackId === track.track_id) {
          waveformData = null;
          isLoadingWaveform = false;
        }
      });
  });

  // Render canvas whenever currentTime, duration, waveformData, or hover state updates
  $effect(() => {
    // Reactive dependencies
    const canvas = canvasRef;
    const peaks = waveformData;
    const currentTime = player.currentTime;
    const duration = player.duration || 1;
    const hovering = isHovering;
    const hoverFrac = hoverFraction;

    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;

    if (width === 0 || height === 0) return;

    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
    }

    ctx.save();
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);

    const playFraction = Math.max(0, Math.min(1, currentTime / duration));
    const count = peaks && peaks.length > 0 ? peaks.length : 80;
    const spacing = 1.5;
    const barWidth = Math.max(1.5, (width - (count - 1) * spacing) / count);

    for (let i = 0; i < count; i++) {
      const x = i * (barWidth + spacing);
      const frac = i / count;

      // Amplitude peak
      let amp = 0.3;
      if (peaks && peaks.length > 0) {
        amp = Math.max(0.08, peaks[i]);
      } else {
        // Subtle fallback wave pattern
        amp = 0.2 + 0.35 * Math.abs(Math.sin((i / count) * Math.PI * 4));
      }

      const barHeight = Math.max(3, amp * (height - 6));
      const y = (height - barHeight) / 2;
      const radius = Math.min(barWidth / 2, 1.5);

      // Bar color based on playback and hover state
      if (frac <= playFraction) {
        // Played region (Accent amber/gold)
        ctx.fillStyle = "#fbbf24";
      } else if (hovering && frac <= hoverFrac) {
        // Hover preview scrub region
        ctx.fillStyle = "rgba(251, 191, 36, 0.45)";
      } else {
        // Unplayed region
        ctx.fillStyle = "rgba(161, 161, 170, 0.35)";
      }

      // Draw rounded bar
      ctx.beginPath();
      if (typeof ctx.roundRect === "function") {
        ctx.roundRect(x, y, barWidth, barHeight, radius);
      } else {
        ctx.rect(x, y, barWidth, barHeight);
      }
      ctx.fill();
    }

    // Draw Playhead cursor
    const playheadX = playFraction * width;
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.roundRect ? ctx.roundRect(Math.max(0, playheadX - 1), 0, 2, height, 1) : ctx.rect(playheadX - 1, 0, 2, height);
    ctx.fill();

    // Draw Hover hairline
    if (hovering) {
      const hX = hoverFrac * width;
      ctx.fillStyle = "rgba(255, 255, 255, 0.7)";
      ctx.beginPath();
      ctx.roundRect ? ctx.roundRect(Math.max(0, hX - 0.5), 0, 1, height, 0.5) : ctx.rect(hX - 0.5, 0, 1, height);
      ctx.fill();
    }

    ctx.restore();
  });

  function getFractionFromEvent(e: PointerEvent): number {
    if (!canvasRef) return 0;
    const rect = canvasRef.getBoundingClientRect();
    const x = e.clientX - rect.left;
    return Math.max(0, Math.min(1, x / rect.width));
  }

  function handlePointerDown(e: PointerEvent) {
    if (!canvasRef || !player.duration) return;
    isDragging = true;
    try {
      canvasRef.setPointerCapture(e.pointerId);
    } catch {}
    const frac = getFractionFromEvent(e);
    hoverFraction = frac;
    hoverX = e.clientX - canvasRef.getBoundingClientRect().left;
    player.seek(frac * player.duration);
  }

  function handlePointerMove(e: PointerEvent) {
    if (!canvasRef) return;
    const rect = canvasRef.getBoundingClientRect();
    const frac = getFractionFromEvent(e);
    isHovering = true;
    hoverFraction = frac;
    hoverX = e.clientX - rect.left;

    if (isDragging && player.duration) {
      player.seek(frac * player.duration);
    }
  }

  function handlePointerUp(e: PointerEvent) {
    if (!canvasRef) return;
    isDragging = false;
    try {
      canvasRef.releasePointerCapture(e.pointerId);
    } catch {}
  }

  function handlePointerLeave() {
    if (!isDragging) {
      isHovering = false;
    }
  }
</script>

{#if player.currentTrack}
  <footer
    class="fixed bottom-0 left-0 right-0 h-20 px-6 flex items-center justify-between z-40 border-t backdrop-blur-xl shadow-2xl select-none"
    style="background:rgba(18,16,22,0.92);border-color:var(--border);color:var(--text-primary);"
  >
    <!-- Left: Track Metadata & Artwork -->
    <div class="flex items-center gap-3 w-1/4 min-w-[200px]">
      <div class="w-12 h-12 rounded-lg overflow-hidden bg-black/50 flex-shrink-0 relative group shadow-md border border-white/5">
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

    <!-- Center: Playback Controls & Interactive Waveform Scrubber -->
    <div class="flex flex-col items-center gap-1.5 w-2/4 max-w-xl">
      <div class="flex items-center gap-4">
        <button
          onclick={() => player.seek(Math.max(0, player.currentTime - 10))}
          class="text-xs text-zinc-400 hover:text-white transition-colors p-1"
          title="Rewind 10s"
        >
          ⏮ 10s
        </button>

        <button
          onclick={() => player.togglePlay()}
          class="w-9 h-9 rounded-full flex items-center justify-center font-bold text-sm transition-transform active:scale-95 shadow-lg hover:brightness-110"
          style="background:var(--accent);color:black;"
          aria-label={player.isPlaying ? "Pause" : "Play"}
        >
          {player.isPlaying ? "❚❚" : "▶"}
        </button>

        <button
          onclick={() => player.seek(Math.min(player.duration, player.currentTime + 10))}
          class="text-xs text-zinc-400 hover:text-white transition-colors p-1"
          title="Forward 10s"
        >
          10s ⏭
        </button>
      </div>

      <!-- Interactive Waveform Scrubber with Hover Time Indicator -->
      <div class="flex items-center gap-3 w-full relative">
        <span class="text-[10px] font-mono text-zinc-400 min-w-[34px] text-right tabular-nums">
          {formatTime(player.currentTime)}
        </span>

        <div class="relative flex-1 flex items-center h-7 group cursor-pointer">
          <!-- Canvas Waveform -->
          <canvas
            bind:this={canvasRef}
            onpointerdown={handlePointerDown}
            onpointermove={handlePointerMove}
            onpointerup={handlePointerUp}
            onpointercancel={handlePointerUp}
            onpointerleave={handlePointerLeave}
            class="w-full h-full rounded-md transition-opacity duration-200"
            style="touch-action: none;"
          ></canvas>

          <!-- Floating Hover Time Tooltip -->
          {#if isHovering && player.duration > 0}
            <div
              class="absolute -top-7 transform -translate-x-1/2 px-2 py-0.5 rounded text-[10px] font-mono font-semibold text-white shadow-xl pointer-events-none z-50 border border-amber-400/30 backdrop-blur-md"
              style="left: {hoverX}px; background: rgba(24, 24, 27, 0.95);"
            >
              {formatTime(hoverFraction * player.duration)}
            </div>
          {/if}
        </div>

        <span class="text-[10px] font-mono text-zinc-400 min-w-[34px] tabular-nums">
          {formatTime(player.duration)}
        </span>
      </div>
    </div>

    <!-- Right: Volume & Extra Utilities -->
    <div class="flex items-center justify-end gap-4 w-1/4 min-w-[180px]">
      <button
        onclick={() => (showLyrics = true)}
        class="text-xs px-2.5 py-1 rounded-lg border font-medium transition-colors hover:border-amber-400 hover:text-amber-300"
        style="background:var(--surface);border-color:var(--border);color:var(--text-secondary);"
        title="Open synchronized lyrics"
      >
        🎤 Lyrics
      </button>

      <div class="flex items-center gap-2">
        <button
          onclick={() => player.toggleMute()}
          class="text-xs text-zinc-400 hover:text-white transition-colors"
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

