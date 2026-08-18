<script lang="ts">
  import { api, type LibraryTrack, type BatchTagFields } from "../api";

  interface Props {
    tracks: LibraryTrack[];
    initialCoverFocus?: boolean;
    onclose: () => void;
    onupdated: () => void;
  }

  let { tracks, initialCoverFocus = false, onclose, onupdated }: Props = $props();

  // Field change states
  let changeArtist = $state(false);
  let artistVal = $state("");

  let changeAlbum = $state(false);
  let albumVal = $state("");

  let changeAlbumArtist = $state(false);
  let albumArtistVal = $state("");

  let changeGenre = $state(false);
  let genreVal = $state("");

  let changeYear = $state(false);
  let yearVal = $state("");

  let changeTrackNum = $state(false);
  let trackNumVal = $state<number | null>(null);

  let changeDiscNum = $state(false);
  let discNumVal = $state<number | null>(null);

  let changeLyrics = $state(false);
  let lyricsVal = $state("");

  let changeComment = $state(false);
  let commentVal = $state("");

  // Cover Art State
  let coverDataUrl = $state<string | null>(null);
  let coverMime = $state<string>("image/jpeg");
  let coverFileName = $state<string | null>(null);
  let removeCover = $state(false);
  let isDragging = $state(false);

  // Options
  let reorganizeFiles = $state(true);

  // Submission State
  let saving = $state(false);
  let errorMessage = $state<string | null>(null);
  let successMessage = $state<string | null>(null);

  // Check shared initial metadata
  $effect(() => {
    if (tracks.length === 1) {
      const t = tracks[0];
      artistVal = t.artist || "";
      albumVal = t.album || "";
      albumArtistVal = t.artist || "";
      changeArtist = true;
      changeAlbum = true;
    } else if (tracks.length > 1) {
      const firstArtist = tracks[0].artist;
      const allSameArtist = tracks.every((t) => t.artist === firstArtist);
      if (allSameArtist) {
        artistVal = firstArtist;
      }

      const firstAlbum = tracks[0].album;
      const allSameAlbum = tracks.every((t) => t.album === firstAlbum);
      if (allSameAlbum) {
        albumVal = firstAlbum;
      }
    }
  });

  function handleFileSelect(file: File) {
    if (!file.type.startsWith("image/")) {
      errorMessage = "Please select an image file (JPEG, PNG, or WEBP).";
      return;
    }
    errorMessage = null;
    coverFileName = file.name;
    coverMime = file.type || "image/jpeg";
    removeCover = false;

    const reader = new FileReader();
    reader.onload = (e) => {
      coverDataUrl = e.target?.result as string;
    };
    reader.readAsDataURL(file);
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    isDragging = false;
    if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
      handleFileSelect(e.dataTransfer.files[0]);
    }
  }

  async function handleSave() {
    saving = true;
    errorMessage = null;
    successMessage = null;

    const fields: BatchTagFields = {};
    if (changeArtist && artistVal.trim()) fields.artist = artistVal.trim();
    if (changeAlbum && albumVal.trim()) fields.album = albumVal.trim();
    if (changeAlbumArtist && albumArtistVal.trim()) fields.album_artist = albumArtistVal.trim();
    if (changeGenre && genreVal.trim()) fields.genre = genreVal.trim();
    if (changeYear && yearVal.trim()) fields.year = yearVal.trim();
    if (changeTrackNum && trackNumVal !== null) fields.track_num = trackNumVal;
    if (changeDiscNum && discNumVal !== null) fields.disc_num = discNumVal;
    if (changeLyrics) fields.lyrics = lyricsVal;
    if (changeComment) fields.comment = commentVal;

    try {
      const res = await api.batchTagTracks({
        track_ids: tracks.map((t) => t.track_id),
        fields,
        cover_art_base64: coverDataUrl,
        cover_art_mime: coverMime,
        remove_cover: removeCover,
        reorganize_files: reorganizeFiles,
      });

      if (res.errors && res.errors.length > 0) {
        errorMessage = `Updated ${res.updated} track(s), but encountered ${res.errors.length} error(s):\n${res.errors.join("\n")}`;
      } else {
        successMessage = `Successfully updated metadata for ${res.updated} track(s)!`;
        setTimeout(() => {
          onupdated();
          onclose();
        }, 800);
      }
    } catch (err) {
      errorMessage = String(err);
    } finally {
      saving = false;
    }
  }
</script>

<!-- Backdrop -->
<div
  role="dialog"
  aria-modal="true"
  class="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 select-none"
  onclick={(e) => { if (e.target === e.currentTarget) onclose(); }}
  onkeydown={(e) => { if (e.key === "Escape") onclose(); }}
  tabindex="-1"
>
  <div
    class="w-full max-w-2xl rounded-2xl border shadow-2xl flex flex-col max-h-[90vh] overflow-hidden"
    style="background:var(--surface);border-color:var(--border);color:var(--text-primary);"
  >
    <!-- Header -->
    <div class="px-6 py-4 border-b flex items-center justify-between" style="border-color:var(--border);">
      <div class="flex items-center gap-3">
        <span class="text-xl">🏷️</span>
        <div>
          <h2 class="text-base font-bold text-white">
            {tracks.length === 1 ? "Edit Track Metadata" : `Batch Tag ${tracks.length} Tracks`}
          </h2>
          <p class="text-xs text-zinc-400">
            {tracks.length === 1 ? tracks[0].title : `Modifying tags across ${tracks.length} selected library tracks`}
          </p>
        </div>
      </div>
      <button
        onclick={onclose}
        class="w-8 h-8 rounded-lg flex items-center justify-center text-zinc-400 hover:text-white hover:bg-white/10 transition-colors"
        aria-label="Close"
      >
        ✕
      </button>
    </div>

    <!-- Body -->
    <div class="p-6 flex-1 overflow-y-auto space-y-6">
      {#if errorMessage}
        <div class="p-3.5 rounded-xl bg-red-950/60 border border-red-500/40 text-red-200 text-xs whitespace-pre-line">
          {errorMessage}
        </div>
      {/if}

      {#if successMessage}
        <div class="p-3.5 rounded-xl bg-emerald-950/60 border border-emerald-500/40 text-emerald-200 text-xs">
          {successMessage}
        </div>
      {/if}

      <!-- Common Metadata Fields -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <!-- Artist -->
        <div class="flex flex-col gap-1.5">
          <div class="flex items-center justify-between">
            <label for="tag-artist" class="text-xs font-semibold text-zinc-300">Artist</label>
            <label class="text-[10px] text-zinc-400 flex items-center gap-1 cursor-pointer">
              <input type="checkbox" bind:checked={changeArtist} class="rounded accent-amber-400" />
              <span>Update</span>
            </label>
          </div>
          <input
            id="tag-artist"
            type="text"
            bind:value={artistVal}
            oninput={() => (changeArtist = true)}
            placeholder={tracks.length > 1 ? "<Keep existing artists>" : "Artist Name"}
            class="px-3 py-2 rounded-lg text-xs bg-black/40 border border-zinc-700 text-white placeholder-zinc-500 focus:border-amber-400 focus:outline-none transition-colors"
          />
        </div>

        <!-- Album -->
        <div class="flex flex-col gap-1.5">
          <div class="flex items-center justify-between">
            <label for="tag-album" class="text-xs font-semibold text-zinc-300">Album</label>
            <label class="text-[10px] text-zinc-400 flex items-center gap-1 cursor-pointer">
              <input type="checkbox" bind:checked={changeAlbum} class="rounded accent-amber-400" />
              <span>Update</span>
            </label>
          </div>
          <input
            id="tag-album"
            type="text"
            bind:value={albumVal}
            oninput={() => (changeAlbum = true)}
            placeholder={tracks.length > 1 ? "<Keep existing albums>" : "Album Name"}
            class="px-3 py-2 rounded-lg text-xs bg-black/40 border border-zinc-700 text-white placeholder-zinc-500 focus:border-amber-400 focus:outline-none transition-colors"
          />
        </div>

        <!-- Album Artist -->
        <div class="flex flex-col gap-1.5">
          <div class="flex items-center justify-between">
            <label for="tag-album-artist" class="text-xs font-semibold text-zinc-300">Album Artist</label>
            <label class="text-[10px] text-zinc-400 flex items-center gap-1 cursor-pointer">
              <input type="checkbox" bind:checked={changeAlbumArtist} class="rounded accent-amber-400" />
              <span>Update</span>
            </label>
          </div>
          <input
            id="tag-album-artist"
            type="text"
            bind:value={albumArtistVal}
            oninput={() => (changeAlbumArtist = true)}
            placeholder="Album Artist"
            class="px-3 py-2 rounded-lg text-xs bg-black/40 border border-zinc-700 text-white placeholder-zinc-500 focus:border-amber-400 focus:outline-none transition-colors"
          />
        </div>

        <!-- Genre -->
        <div class="flex flex-col gap-1.5">
          <div class="flex items-center justify-between">
            <label for="tag-genre" class="text-xs font-semibold text-zinc-300">Genre</label>
            <label class="text-[10px] text-zinc-400 flex items-center gap-1 cursor-pointer">
              <input type="checkbox" bind:checked={changeGenre} class="rounded accent-amber-400" />
              <span>Update</span>
            </label>
          </div>
          <input
            id="tag-genre"
            type="text"
            bind:value={genreVal}
            oninput={() => (changeGenre = true)}
            placeholder="e.g. Synthwave, Electronic"
            class="px-3 py-2 rounded-lg text-xs bg-black/40 border border-zinc-700 text-white placeholder-zinc-500 focus:border-amber-400 focus:outline-none transition-colors"
          />
        </div>

        <!-- Year -->
        <div class="flex flex-col gap-1.5">
          <div class="flex items-center justify-between">
            <label for="tag-year" class="text-xs font-semibold text-zinc-300">Year / Date</label>
            <label class="text-[10px] text-zinc-400 flex items-center gap-1 cursor-pointer">
              <input type="checkbox" bind:checked={changeYear} class="rounded accent-amber-400" />
              <span>Update</span>
            </label>
          </div>
          <input
            id="tag-year"
            type="text"
            bind:value={yearVal}
            oninput={() => (changeYear = true)}
            placeholder="e.g. 2024"
            class="px-3 py-2 rounded-lg text-xs bg-black/40 border border-zinc-700 text-white placeholder-zinc-500 focus:border-amber-400 focus:outline-none transition-colors"
          />
        </div>

        <!-- Disc Number -->
        <div class="flex flex-col gap-1.5">
          <div class="flex items-center justify-between">
            <label for="tag-disc-num" class="text-xs font-semibold text-zinc-300">Disc Number</label>
            <label class="text-[10px] text-zinc-400 flex items-center gap-1 cursor-pointer">
              <input type="checkbox" bind:checked={changeDiscNum} class="rounded accent-amber-400" />
              <span>Update</span>
            </label>
          </div>
          <input
            id="tag-disc-num"
            type="number"
            min="1"
            bind:value={discNumVal}
            oninput={() => (changeDiscNum = true)}
            placeholder="1"
            class="px-3 py-2 rounded-lg text-xs bg-black/40 border border-zinc-700 text-white placeholder-zinc-500 focus:border-amber-400 focus:outline-none transition-colors"
          />
        </div>
      </div>

      <!-- Cover Art Dropzone & Replacer -->
      <div class="flex flex-col gap-2 pt-2 border-t" style="border-color:var(--border);">
        <span class="text-xs font-bold text-white flex items-center gap-2">
          <span>🖼️ Cover Artwork</span>
          {#if coverDataUrl}
            <span class="text-[10px] text-emerald-400 font-mono">✓ Ready to Embed</span>
          {/if}
        </span>

        <div
          role="region"
          aria-label="Cover artwork dropzone"
          ondragover={(e) => { e.preventDefault(); isDragging = true; }}
          ondragleave={() => (isDragging = false)}
          ondrop={handleDrop}
          class="border-2 border-dashed rounded-xl p-5 flex flex-col items-center justify-center gap-3 transition-colors {isDragging ? 'border-amber-400 bg-amber-400/10' : 'border-zinc-700 bg-black/30 hover:border-zinc-500'}"
        >
          {#if coverDataUrl}
            <div class="flex items-center gap-4">
              <img
                src={coverDataUrl}
                alt="Cover preview"
                class="w-24 h-24 rounded-lg object-cover shadow-lg border border-amber-400/40"
              />
              <div class="flex flex-col gap-1.5 text-xs">
                <span class="font-bold text-white truncate max-w-xs">{coverFileName || "Custom Cover Art"}</span>
                <span class="text-[11px] text-zinc-400 font-mono">{coverMime}</span>
                <button
                  type="button"
                  onclick={() => { coverDataUrl = null; coverFileName = null; }}
                  class="text-[11px] text-red-400 hover:text-red-300 underline text-left mt-1"
                >
                  ✕ Discard Upload
                </button>
              </div>
            </div>
          {:else}
            <div class="flex flex-col items-center gap-1.5 text-center">
              <span class="text-2xl text-zinc-500">📥</span>
              <span class="text-xs text-zinc-300 font-medium">Drag and drop album artwork image here</span>
              <span class="text-[11px] text-zinc-500">Supports JPEG, PNG, WEBP</span>
              <label class="mt-2 px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-semibold cursor-pointer transition-colors">
                Browse Files
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  class="hidden"
                  onchange={(e) => {
                    const input = e.target as HTMLInputElement;
                    if (input.files?.[0]) handleFileSelect(input.files[0]);
                  }}
                />
              </label>
            </div>
          {/if}
        </div>

        {#if !coverDataUrl}
          <label class="flex items-center gap-2 mt-1 cursor-pointer">
            <input type="checkbox" bind:checked={removeCover} class="rounded accent-red-400" />
            <span class="text-xs text-zinc-400 hover:text-white">🗑️ Remove embedded cover art from all selected tracks</span>
          </label>
        {/if}
      </div>

      <!-- File System Reorganization Toggle -->
      <div class="pt-2 border-t flex items-center justify-between" style="border-color:var(--border);">
        <label class="flex items-center gap-2.5 cursor-pointer">
          <input type="checkbox" bind:checked={reorganizeFiles} class="rounded accent-amber-400" />
          <div class="flex flex-col">
            <span class="text-xs font-semibold text-white">Reorganize Audio Files</span>
            <span class="text-[11px] text-zinc-400">Move audio files on disk if Artist or Album tags are changed</span>
          </div>
        </label>
      </div>
    </div>

    <!-- Footer Actions -->
    <div class="px-6 py-4 border-t flex items-center justify-between bg-black/40" style="border-color:var(--border);">
      <button
        onclick={onclose}
        class="px-4 py-2 text-xs font-medium text-zinc-400 hover:text-white transition-colors"
      >
        Cancel
      </button>

      <button
        onclick={handleSave}
        disabled={saving}
        class="px-5 py-2.5 rounded-xl text-xs font-bold bg-amber-400 text-black hover:bg-amber-300 transition-transform active:scale-95 shadow-lg flex items-center gap-2 disabled:opacity-50"
      >
        {#if saving}
          <span>⏳ Saving tags…</span>
        {:else}
          <span>💾 Save Tags ({tracks.length} Track{tracks.length === 1 ? "" : "s"})</span>
        {/if}
      </button>
    </div>
  </div>
</div>
