<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../api";

  let cfg = $state<Record<string, string>>({});
  let saving = $state(false);
  let saved = $state(false);
  let error = $state<string | null>(null);
  let loaded = $state(false);

  onMount(async () => {
    cfg = await api.config();
    loaded = true;
  });

  const SECTIONS: {
    title: string;
    hint?: string;
    fields: { key: string; label: string; hint: string; type?: string; mono?: boolean }[];
  }[] = [
    {
      title: "Paths",
      fields: [
        { key: "music_dir",   label: "Music directory",   hint: "Where synced ALAC files are stored. Must exist or be creatable." },
        { key: "staging_dir", label: "Staging directory", hint: "Place downloaded .m4a files here before running sync." },
        { key: "state_dir",   label: "State directory",   hint: "Where the track database (downloaded.db) and sync logs are stored." },
      ],
    },
    {
      title: "Sync",
      fields: [
        { key: "github_remote", label: "GitHub remote", hint: "Optional — used to push state DB changes. Leave blank to disable." },
      ],
    },
  ];

  function isEmpty(key: string): boolean {
    return !cfg[key]?.trim();
  }

  const REQUIRED = new Set(["music_dir", "state_dir"]);

  let hasIssues = $derived([...REQUIRED].some(k => isEmpty(k)));

  async function save() {
    saving = true;
    error = null;
    try {
      const updates: Record<string, string> = {};
      for (const section of SECTIONS) {
        for (const f of section.fields) {
          updates[f.key] = cfg[f.key] ?? "";
        }
      }
      await api.updateConfig(updates);
      saved = true;
      setTimeout(() => (saved = false), 2500);
    } catch (e) {
      error = String(e);
    } finally {
      saving = false;
    }
  }
</script>

<div class="p-8 max-w-xl">
  <div class="mb-7">
    <h1 class="text-white text-2xl font-bold tracking-tight">Settings</h1>
    <p class="text-zinc-500 text-sm mt-1">Saved to <span class="font-mono text-zinc-400 text-xs">~/.config/pies-alac-rip/config.yaml</span></p>
  </div>

  {#if !loaded}
    <div class="flex flex-col gap-4">
      {#each [1,2,3] as _}
        <div class="h-14 rounded-xl bg-[#111] animate-pulse border border-[#1e1e1e]"></div>
      {/each}
    </div>
  {:else}
    <div class="flex flex-col gap-7">
      {#each SECTIONS as section}
        <div>
          <div class="flex items-baseline gap-2 mb-3">
            <span class="text-zinc-300 text-sm font-semibold">{section.title}</span>
            {#if section.hint}
              <span class="text-zinc-600 text-xs">{section.hint}</span>
            {/if}
          </div>

          <div class="flex flex-col gap-3 border border-[#1e1e1e] rounded-xl overflow-hidden">
            {#each section.fields as field, fi}
              <div class="px-4 {fi > 0 ? 'pt-3 border-t border-[#181818]' : 'pt-4'} pb-3">
                <div class="flex items-center justify-between mb-1.5">
                  <label class="text-zinc-400 text-[10px] uppercase tracking-widest font-semibold" for={field.key}>
                    {field.label}
                  </label>
                  {#if REQUIRED.has(field.key) && isEmpty(field.key)}
                    <span class="text-amber-500 text-[9px] uppercase tracking-wider font-semibold">required</span>
                  {/if}
                </div>
                  <input
                    id={field.key}
                    bind:value={cfg[field.key]}
                    type={field.type ?? "text"}
                    class="w-full bg-[#0d0d0d] border rounded-lg px-3 py-2 text-white text-sm outline-none transition-colors
                      {field.mono ? 'font-mono text-xs' : ''}
                      {isEmpty(field.key) && REQUIRED.has(field.key)
                        ? 'border-amber-800/60 focus:border-amber-600'
                        : 'border-[#2a2a2a] focus:border-amber-700'}"
                  />
                <p class="text-zinc-600 text-[10px] mt-1.5 leading-relaxed">{field.hint}</p>
              </div>
            {/each}
          </div>
        </div>
      {/each}

      {#if error}
        <div class="bg-red-950/40 border border-red-900/50 rounded-xl px-4 py-3 text-red-400 text-sm">{error}</div>
      {/if}

      {#if hasIssues}
        <div class="bg-amber-950/30 border border-amber-900/40 rounded-xl px-4 py-3 text-amber-400 text-sm flex items-center gap-2">
          <span>⚠</span>
          <span>Some required fields are empty. The app may not function until they're filled in.</span>
        </div>
      {/if}

      <button
        onclick={save}
        disabled={saving}
        class="w-full py-2.5 rounded-xl font-bold text-sm transition-colors disabled:opacity-50
          {saved
            ? 'bg-green-900/50 text-green-400 border border-green-800/50'
            : 'bg-amber-700 hover:bg-amber-600 text-white'}">
        {saving ? "Saving…" : saved ? "✓ Saved" : "Save changes"}
      </button>
    </div>
  {/if}
</div>
