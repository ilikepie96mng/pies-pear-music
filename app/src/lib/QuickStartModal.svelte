<script lang="ts">
  interface Props {
    onclose: () => void;
    onopenSetup: () => void;
    onopenSettings: () => void;
    onopenCreator: () => void;
    onopenImport: () => void;
    onopenLibrary: () => void;
  }

  let { onclose, onopenSetup, onopenSettings, onopenCreator, onopenImport, onopenLibrary }: Props = $props();

  let step = $state(0);

  const TOUR_STEPS = [
    {
      title: "Welcome to Pies Pear Music",
      tagline: "Your high-fidelity lossless music workstation",
      icon: "🍎",
      summary: "Pies Pear Music syncs, manages, tags, and downloads bit-perfect Apple Lossless Audio Codec (ALAC) and Dolby Atmos music directly to your local library and portable audio players (DAPs).",
      bullets: [
        "Lossless ALAC & Atmos audio downloads with automatic metadata embedding.",
        "Smart Dynamic Playlists with real-time rule evaluation & duplicate detection.",
        "Interactive waveform scrubbing and synchronized lyrics (.lrc).",
        "Automated backup sync to portable DAPs and Strawberry Music Player.",
      ],
      primaryAction: { label: "Start Feature Tour →", action: () => step = 1 },
      secondaryAction: { label: "Run Setup Wizard", action: () => { onclose(); onopenSetup(); } },
    },
    {
      title: "Step 1: Setup & Configuration",
      tagline: "Connect your directories and Apple Music account",
      icon: "⚙️",
      summary: "Make sure your music storage folder and downloader wrapper paths are properly set.",
      bullets: [
        "Music Folder: Where all ALAC / AAC / Atmos files are neatly organized.",
        "Wrapper Directory: The podman container wrapper for lossless decryption.",
        "Apple Music Account: Log in once securely to authenticate downloads.",
        "Last.fm & Gemini AI Keys: Optional API keys for AI curation and discovery.",
      ],
      primaryAction: { label: "Next: Smart Playlists →", action: () => step = 2 },
      secondaryAction: { label: "Open Settings", action: () => { onclose(); onopenSettings(); } },
    },
    {
      title: "Step 2: Playlist Creator & Gemini AI",
      tagline: "Curate custom mixes and download missing tracks",
      icon: "🔀",
      summary: "Build playlists manually or let Gemini AI generate cohesive mixes tailored to your taste.",
      bullets: [
        "📚 Library-Only Mode: Constrains the AI to pick exclusively from your own collection.",
        "⚡ Automated Missing Track Downloader: Queues unowned songs for 1-click lossless fetching.",
        "Canonical Album Track Rule: AI prioritizes original studio versions automatically.",
        "Multi-Format Export: Export to .m3u8, sync to Strawberry, or transcode for portable DAPs.",
      ],
      primaryAction: { label: "Next: Streaming Import →", action: () => step = 3 },
      secondaryAction: { label: "Open Playlist Creator", action: () => { onclose(); onopenCreator(); } },
    },
    {
      title: "Step 3: Streaming Import & Graveyard",
      tagline: "Bring your playlists anywhere and protect against delisting",
      icon: "⚡",
      summary: "Import playlists from Spotify, Tidal, or Apple Music and preserve songs if they are ever removed upstream.",
      bullets: [
        "⚡ Streaming Import: Paste any public playlist URL to match and download tracks locally.",
        "🏛 Streaming Graveyard: Tracks removed from upstream playlists are automatically preserved in your local library archive.",
        "🔍 Check Duplicates: Instant audit to remove duplicate title/artist songs with 1 click.",
        "🏷 Batch Metadata Editor: Mass-edit tags and replace cover art seamlessly.",
      ],
      primaryAction: { label: "Next: Audiophile Player →", action: () => step = 4 },
      secondaryAction: { label: "Open Streaming Import", action: () => { onclose(); onopenImport(); } },
    },
    {
      title: "Step 4: Lossless Player & DAP Export",
      tagline: "Bit-perfect listening and on-the-go offline sync",
      icon: "🎵",
      summary: "Enjoy built-in playback with an interactive waveform visualizer and synchronized lyrics.",
      bullets: [
        "Interactive Waveform Scrubber: Click or drag across real-time audio peaks to seek.",
        "Synchronized Lyrics: View timestamped .lrc lyrics in a floating modal.",
        "📱 Export to DAP: 1-click transcode to Opus/MP3 or copy bit-perfect ALAC to your SD card.",
        "🍓 Strawberry Sync: Direct database export to Strawberry Music Player.",
      ],
      primaryAction: { label: "Finish Tour & Explore Library ✓", action: () => { onclose(); onopenLibrary(); } },
      secondaryAction: { label: "Close Guide", action: () => onclose() },
    },
  ];

  let current = $derived(TOUR_STEPS[step]);
</script>

<div
  role="dialog"
  aria-modal="true"
  tabindex="-1"
  class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-md p-4 select-none"
  onclick={(e) => { if (e.target === e.currentTarget) onclose(); }}
  onkeydown={(e) => { if (e.key === "Escape") onclose(); }}
>
  <div class="w-[min(640px,94vw)] rounded-2xl border border-[rgba(252,211,77,0.25)] bg-[#12100e] shadow-2xl overflow-hidden flex flex-col">
    <!-- Header -->
    <div class="px-6 py-4 border-b border-[rgba(255,255,255,0.06)] flex items-center justify-between bg-[#181410]">
      <div class="flex items-center gap-3">
        <span class="text-2xl">{current.icon}</span>
        <div>
          <div class="text-[10px] uppercase tracking-widest font-bold text-amber-400">Quick-Start Guide & Tour</div>
          <div class="text-base font-bold text-white leading-tight mt-0.5">{current.title}</div>
        </div>
      </div>
      <button
        onclick={onclose}
        class="text-zinc-500 hover:text-white w-8 h-8 rounded-full flex items-center justify-center hover:bg-white/10 transition-colors text-lg"
        aria-label="Close"
      >
        &times;
      </button>
    </div>

    <!-- Step Progress Dots -->
    <div class="flex items-center justify-center gap-2 py-3 bg-[#0d0c0a] border-b border-[rgba(255,255,255,0.04)]">
      {#each TOUR_STEPS as _, i}
        <button
          onclick={() => step = i}
          class="h-1.5 rounded-full transition-all {step === i ? 'w-8 bg-amber-400' : 'w-2 bg-zinc-700 hover:bg-zinc-500'}"
          title={`Go to step ${i + 1}`}
        ></button>
      {/each}
    </div>

    <!-- Body Content -->
    <div class="p-6 flex flex-col gap-4">
      <div class="text-xs text-amber-200/90 font-medium">{current.tagline}</div>
      <p class="text-sm text-zinc-300 leading-relaxed">{current.summary}</p>

      <div class="bg-black/40 border border-[rgba(255,255,255,0.06)] rounded-xl p-4 flex flex-col gap-2.5">
        <div class="text-[10px] uppercase tracking-widest font-bold text-zinc-400">Key Highlights</div>
        {#each current.bullets as bullet}
          <div class="flex items-start gap-2 text-xs text-zinc-300">
            <span class="text-amber-400 mt-0.5">•</span>
            <span>{bullet}</span>
          </div>
        {/each}
      </div>
    </div>

    <!-- Footer Actions -->
    <div class="px-6 py-4 border-t border-[rgba(255,255,255,0.06)] bg-[#181410] flex items-center justify-between">
      <div class="flex items-center gap-2">
        {#if step > 0}
          <button
            onclick={() => step = Math.max(0, step - 1)}
            class="px-3 py-1.5 rounded-lg text-xs font-semibold text-zinc-400 hover:text-white bg-white/5 hover:bg-white/10 transition-colors"
          >
            ← Previous
          </button>
        {/if}
        {#if current.secondaryAction}
          <button
            onclick={current.secondaryAction.action}
            class="px-3 py-1.5 rounded-lg text-xs font-semibold text-amber-300 hover:text-amber-200 bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/30 transition-colors"
          >
            {current.secondaryAction.label}
          </button>
        {/if}
      </div>

      <div class="flex items-center gap-2">
        <button
          onclick={current.primaryAction.action}
          class="px-5 py-2 rounded-lg text-xs font-bold bg-amber-400 hover:bg-amber-300 text-black shadow-md transition-transform active:scale-95"
        >
          {current.primaryAction.label}
        </button>
      </div>
    </div>
  </div>
</div>
