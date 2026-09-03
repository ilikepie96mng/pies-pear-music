<script lang="ts">
  import { onMount } from "svelte";
  import {
    api,
    type SmartPlaylist,
    type SmartPlaylistRule,
    type SmartPlaylistRulesConfig,
    type LibraryTrack,
  } from "../api";

  interface Props {
    editingPlaylist?: SmartPlaylist | null;
    onclose: () => void;
    onsaved: (playlist: SmartPlaylist) => void;
  }

  let { editingPlaylist = null, onclose, onsaved }: Props = $props();

  let name = $state("");
  let description = $state("");
  let match = $state<"all" | "any">("all");
  let rules = $state<SmartPlaylistRule[]>([
    { field: "artist", operator: "contains", value: "" },
  ]);
  let sortBy = $state<"downloaded_at" | "title" | "artist" | "album" | "random">("downloaded_at");
  let sortOrder = $state<"asc" | "desc">("desc");
  let hasLimit = $state(false);
  let limitCount = $state<number>(50);

  // Preview state
  let previewLoading = $state(false);
  let previewTracks = $state<LibraryTrack[]>([]);
  let previewCount = $state(0);
  let previewError = $state<string | null>(null);

  // Saving state
  let saving = $state(false);
  let saveError = $state<string | null>(null);

  const availableFields: { id: SmartPlaylistRule["field"]; label: string }[] = [
    { id: "title", label: "Title" },
    { id: "artist", label: "Artist" },
    { id: "album", label: "Album" },
    { id: "playlist", label: "Playlist Membership" },
    { id: "format", label: "Format (ALAC/FLAC/M4A/MP3)" },
    { id: "downloaded_at", label: "Date Added" },
    { id: "local_path", label: "File Path" },
  ];

  const fieldOperators: Record<SmartPlaylistRule["field"], { id: SmartPlaylistRule["operator"]; label: string }[]> = {
    title: [
      { id: "contains", label: "contains" },
      { id: "not_contains", label: "does not contain" },
      { id: "equals", label: "is exactly" },
      { id: "not_equals", label: "is not" },
      { id: "starts_with", label: "starts with" },
      { id: "ends_with", label: "ends with" },
      { id: "regex", label: "matches regex" },
    ],
    artist: [
      { id: "contains", label: "contains" },
      { id: "not_contains", label: "does not contain" },
      { id: "equals", label: "is exactly" },
      { id: "not_equals", label: "is not" },
      { id: "starts_with", label: "starts with" },
      { id: "ends_with", label: "ends with" },
      { id: "regex", label: "matches regex" },
    ],
    album: [
      { id: "contains", label: "contains" },
      { id: "not_contains", label: "does not contain" },
      { id: "equals", label: "is exactly" },
      { id: "not_equals", label: "is not" },
      { id: "starts_with", label: "starts with" },
      { id: "ends_with", label: "ends with" },
      { id: "regex", label: "matches regex" },
    ],
    playlist: [
      { id: "equals", label: "is in playlist" },
      { id: "not_equals", label: "is not in playlist" },
      { id: "contains", label: "playlist name contains" },
      { id: "not_contains", label: "playlist name does not contain" },
      { id: "is_empty", label: "not in any playlist" },
      { id: "is_not_empty", label: "in at least one playlist" },
    ],
    format: [
      { id: "equals", label: "is (e.g. M4A, FLAC, MP3)" },
      { id: "not_equals", label: "is not" },
    ],
    downloaded_at: [
      { id: "in_past_days", label: "in the past (days)" },
      { id: "after_date", label: "after date (YYYY-MM-DD)" },
      { id: "before_date", label: "before date (YYYY-MM-DD)" },
    ],
    local_path: [
      { id: "contains", label: "contains path" },
      { id: "starts_with", label: "starts with path" },
    ],
  };

  onMount(() => {
    if (editingPlaylist) {
      name = editingPlaylist.name;
      description = editingPlaylist.description ?? "";
      if (editingPlaylist.rules) {
        match = editingPlaylist.rules.match ?? "all";
        if (editingPlaylist.rules.rules && editingPlaylist.rules.rules.length > 0) {
          rules = JSON.parse(JSON.stringify(editingPlaylist.rules.rules));
        }
        sortBy = editingPlaylist.rules.sort_by ?? "downloaded_at";
        sortOrder = editingPlaylist.rules.sort_order ?? "desc";
        if (editingPlaylist.rules.limit) {
          hasLimit = true;
          limitCount = editingPlaylist.rules.limit;
        }
      }
    }
    triggerPreview();
  });

  function addRule() {
    rules.push({ field: "artist", operator: "contains", value: "" });
    triggerPreview();
  }

  function removeRule(index: number) {
    if (rules.length <= 1) {
      rules = [{ field: "artist", operator: "contains", value: "" }];
    } else {
      rules.splice(index, 1);
    }
    triggerPreview();
  }

  function buildConfig(): SmartPlaylistRulesConfig {
    return {
      match,
      rules: rules.filter((r) => {
        if (r.operator === "is_empty" || r.operator === "is_not_empty") return true;
        return r.value !== undefined && String(r.value).trim() !== "";
      }),
      sort_by: sortBy,
      sort_order: sortOrder,
      limit: hasLimit ? Number(limitCount) : undefined,
    };
  }

  let previewDebounceTimer: any = null;
  function triggerPreview() {
    clearTimeout(previewDebounceTimer);
    previewDebounceTimer = setTimeout(async () => {
      previewLoading = true;
      previewError = null;
      try {
        const config = buildConfig();
        const res = await api.previewSmartPlaylist(config);
        previewTracks = res.tracks;
        previewCount = res.track_count;
      } catch (err) {
        previewError = String(err);
      } finally {
        previewLoading = false;
      }
    }, 250);
  }

  async function handleSave() {
    if (!name.trim()) {
      saveError = "Please specify a name for the Smart Playlist.";
      return;
    }
    saving = true;
    saveError = null;
    try {
      const config = buildConfig();
      let result: SmartPlaylist;
      if (editingPlaylist) {
        result = await api.updateSmartPlaylist(editingPlaylist.id, {
          name: name.trim(),
          description: description.trim(),
          rules: config,
        });
      } else {
        result = await api.createSmartPlaylist(name.trim(), description.trim(), config);
      }
      onsaved(result);
      onclose();
    } catch (e) {
      saveError = String(e);
    } finally {
      saving = false;
    }
  }
</script>

<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 overflow-y-auto">
  <div class="bg-zinc-900 border border-zinc-700 rounded-xl w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
    <!-- Header -->
    <div class="flex items-center justify-between px-6 py-4 border-b border-zinc-800 bg-zinc-900/90">
      <div class="flex items-center gap-3">
        <div class="w-8 h-8 rounded-lg bg-amber-400/10 border border-amber-400/30 flex items-center justify-center text-amber-400 text-base">
          ⚡
        </div>
        <div>
          <h2 class="text-base font-bold text-zinc-100">
            {editingPlaylist ? "Edit Smart Playlist" : "New Smart Dynamic Playlist"}
          </h2>
          <p class="text-xs text-zinc-400">
            Auto-evaluating live query rules updated instantly across your local music library.
          </p>
        </div>
      </div>
      <button
        onclick={onclose}
        class="text-zinc-400 hover:text-zinc-200 p-1.5 rounded-lg hover:bg-zinc-800 transition"
        aria-label="Close"
      >
        ✕
      </button>
    </div>

    <!-- Body Content -->
    <div class="flex-1 overflow-y-auto p-6 space-y-6">
      {#if saveError}
        <div class="p-3 bg-red-950/60 border border-red-800 text-red-300 text-xs rounded-lg flex items-center gap-2">
          <span>⚠️</span>
          <span>{saveError}</span>
        </div>
      {/if}

      <!-- Basic Info -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label for="sp-name" class="block text-xs font-semibold text-zinc-300 uppercase tracking-wider mb-1.5">
            Playlist Name <span class="text-amber-400">*</span>
          </label>
          <input
            id="sp-name"
            type="text"
            bind:value={name}
            placeholder="e.g. High-Res Classics, 2026 Additions..."
            class="w-full px-3 py-2 bg-zinc-950 border border-zinc-700 rounded-lg text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-amber-400 transition"
          />
        </div>
        <div>
          <label for="sp-desc" class="block text-xs font-semibold text-zinc-300 uppercase tracking-wider mb-1.5">
            Description (Optional)
          </label>
          <input
            id="sp-desc"
            type="text"
            bind:value={description}
            placeholder="e.g. Tracks matching query criteria"
            class="w-full px-3 py-2 bg-zinc-950 border border-zinc-700 rounded-lg text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-amber-400 transition"
          />
        </div>
      </div>

      <!-- Rule Match Mode -->
      <div class="flex items-center justify-between bg-zinc-950/60 p-3 rounded-lg border border-zinc-800">
        <div class="flex items-center gap-3">
          <span class="text-xs font-semibold text-zinc-300">Match tracks where:</span>
          <select
            bind:value={match}
            onchange={triggerPreview}
            class="bg-zinc-900 border border-zinc-700 text-zinc-200 text-xs rounded px-2.5 py-1 focus:outline-none focus:border-amber-400"
          >
            <option value="all">ALL conditions match (AND)</option>
            <option value="any">ANY condition matches (OR)</option>
          </select>
        </div>
        <button
          onclick={addRule}
          class="px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-medium rounded border border-zinc-700 flex items-center gap-1.5 transition"
        >
          <span>＋</span> Add Condition
        </button>
      </div>

      <!-- Conditions List -->
      <div class="space-y-2.5">
        {#each rules as rule, idx}
          <div class="flex items-center gap-2 p-2.5 bg-zinc-950 rounded-lg border border-zinc-800 group hover:border-zinc-700 transition">
            <!-- Field -->
            <select
              bind:value={rule.field}
              onchange={() => {
                const ops = fieldOperators[rule.field];
                if (ops && ops.length > 0) rule.operator = ops[0].id;
                triggerPreview();
              }}
              class="bg-zinc-900 border border-zinc-700 text-zinc-200 text-xs rounded px-2.5 py-1.5 focus:outline-none focus:border-amber-400 flex-shrink-0"
            >
              {#each availableFields as f}
                <option value={f.id}>{f.label}</option>
              {/each}
            </select>

            <!-- Operator -->
            <select
              bind:value={rule.operator}
              onchange={triggerPreview}
              class="bg-zinc-900 border border-zinc-700 text-zinc-200 text-xs rounded px-2.5 py-1.5 focus:outline-none focus:border-amber-400 flex-shrink-0"
            >
              {#each (fieldOperators[rule.field] || []) as op}
                <option value={op.id}>{op.label}</option>
              {/each}
            </select>

            <!-- Value Input (if applicable) -->
            {#if rule.operator !== "is_empty" && rule.operator !== "is_not_empty"}
              <input
                type="text"
                bind:value={rule.value}
                oninput={triggerPreview}
                placeholder={rule.operator === "in_past_days" ? "e.g. 30" : "Value..."}
                class="flex-1 px-2.5 py-1.5 bg-zinc-900 border border-zinc-700 rounded text-xs text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-amber-400 transition"
              />
            {:else}
              <div class="flex-1 text-xs text-zinc-500 italic px-2">No additional value needed</div>
            {/if}

            <!-- Delete Rule -->
            <button
              onclick={() => removeRule(idx)}
              class="text-zinc-500 hover:text-red-400 p-1.5 rounded hover:bg-zinc-800 transition"
              title="Remove condition"
            >
              ✕
            </button>
          </div>
        {/each}
      </div>

      <!-- Sorting & Limits -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2 border-t border-zinc-800">
        <div>
          <label for="sort-by-select" class="block text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-1">Sort By</label>
          <select
            id="sort-by-select"
            bind:value={sortBy}
            onchange={triggerPreview}
            class="w-full bg-zinc-950 border border-zinc-700 text-zinc-200 text-xs rounded px-2.5 py-1.5 focus:outline-none focus:border-amber-400"
          >
            <option value="downloaded_at">Date Added</option>
            <option value="title">Track Title</option>
            <option value="artist">Artist Name</option>
            <option value="album">Album Title</option>
            <option value="random">Random Shuffled</option>
          </select>
        </div>
        <div>
          <label for="order-select" class="block text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-1">Order</label>
          <select
            id="order-select"
            bind:value={sortOrder}
            onchange={triggerPreview}
            disabled={sortBy === "random"}
            class="w-full bg-zinc-950 border border-zinc-700 text-zinc-200 text-xs rounded px-2.5 py-1.5 focus:outline-none focus:border-amber-400 disabled:opacity-50"
          >
            <option value="desc">Descending (Z-A / Newest First)</option>
            <option value="asc">Ascending (A-Z / Oldest First)</option>
          </select>
        </div>
        <div>
          <div class="flex items-center justify-between mb-1">
            <label for="limit-toggle" class="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Limit Results</label>
            <input
              id="limit-toggle"
              type="checkbox"
              bind:checked={hasLimit}
              onchange={triggerPreview}
              class="accent-amber-400 rounded"
            />
          </div>
          <input
            type="number"
            min="1"
            max="10000"
            bind:value={limitCount}
            oninput={triggerPreview}
            disabled={!hasLimit}
            class="w-full px-2.5 py-1.5 bg-zinc-950 border border-zinc-700 rounded text-xs text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-amber-400 transition disabled:opacity-50"
          />
        </div>
      </div>

      <!-- Live Dynamic Preview -->
      <div class="border border-zinc-800 rounded-lg overflow-hidden bg-zinc-950">
        <div class="flex items-center justify-between px-3.5 py-2 bg-zinc-900/70 border-b border-zinc-800">
          <div class="flex items-center gap-2">
            <span class="text-xs font-bold text-zinc-300">Live Preview</span>
            <span class="px-2 py-0.5 rounded-full bg-amber-400/10 text-amber-400 text-[11px] font-bold">
              {previewLoading ? "Calculating..." : `${previewCount} tracks matched`}
            </span>
          </div>
        </div>

        {#if previewError}
          <div class="p-3 text-xs text-red-400 bg-red-950/20">{previewError}</div>
        {:else if previewTracks.length === 0}
          <div class="p-6 text-center text-xs text-zinc-500">
            No tracks match the current rule criteria.
          </div>
        {:else}
          <div class="max-h-48 overflow-y-auto divide-y divide-zinc-800/60">
            {#each previewTracks.slice(0, 15) as track}
              <div class="px-3.5 py-2 flex items-center justify-between text-xs hover:bg-zinc-900/50">
                <div class="flex items-center gap-3 min-w-0">
                  <div class="truncate">
                    <span class="font-medium text-zinc-200">{track.title}</span>
                    <span class="text-zinc-500 ml-1.5">• {track.artist}</span>
                  </div>
                </div>
                <span class="text-[11px] text-zinc-500 truncate ml-4 max-w-[150px]">{track.album}</span>
              </div>
            {/each}
            {#if previewTracks.length > 15}
              <div class="p-2 text-center text-[11px] text-zinc-500 italic bg-zinc-900/30">
                +{previewTracks.length - 15} more tracks
              </div>
            {/if}
          </div>
        {/if}
      </div>
    </div>

    <!-- Modal Footer Actions -->
    <div class="px-6 py-4 border-t border-zinc-800 bg-zinc-900/90 flex items-center justify-between">
      <button
        onclick={onclose}
        class="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs font-semibold rounded-lg border border-zinc-700 transition"
      >
        Cancel
      </button>
      <button
        onclick={handleSave}
        disabled={saving}
        class="px-5 py-2 bg-amber-400 hover:bg-amber-300 text-black text-xs font-bold rounded-lg shadow transition disabled:opacity-50 flex items-center gap-2"
      >
        {#if saving}
          <span class="animate-spin text-sm">⏳</span>
          <span>Saving...</span>
        {:else}
          <span>✓</span>
          <span>{editingPlaylist ? "Update Smart Playlist" : "Create Smart Playlist"}</span>
        {/if}
      </button>
    </div>
  </div>
</div>
