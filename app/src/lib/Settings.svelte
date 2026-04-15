<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../api";

  let cfg = $state<Record<string, string>>({});
  let newPassword = $state("");
  let saving = $state(false);
  let saved = $state(false);
  let error = $state<string | null>(null);

  onMount(async () => { cfg = await api.config(); });

  const fields: { key: string; label: string }[] = [
    { key: "music_dir",        label: "Music directory" },
    { key: "staging_dir",      label: "Staging directory" },
    { key: "media_user_token", label: "Media user token" },
    { key: "apple_id_email",   label: "Apple ID email" },
    { key: "github_remote",    label: "GitHub remote (optional)" },
  ];

  async function save() {
    saving = true;
    error = null;
    try {
      const updates: Record<string, string> = Object.fromEntries(
        fields.map(f => [f.key, cfg[f.key] ?? ""])
      );
      if (newPassword.trim()) updates.apple_id_password = newPassword.trim();
      await api.updateConfig(updates);
      saved = true;
      newPassword = "";
      setTimeout(() => (saved = false), 2500);
    } catch (e) {
      error = String(e);
    } finally {
      saving = false;
    }
  }
</script>

<div class="p-8 max-w-lg">
  <h1 class="text-white text-2xl font-bold mb-6">Settings</h1>

  <div class="flex flex-col gap-4">
    {#each fields as f}
      <label class="flex flex-col gap-1">
        <span class="text-zinc-400 text-xs uppercase tracking-widest">{f.label}</span>
        <input bind:value={cfg[f.key]}
          class="bg-[#1a1a1a] border border-[#333] rounded-lg px-3 py-2 text-white text-sm outline-none focus:border-[#1db954] transition-colors" />
      </label>
    {/each}

    <label class="flex flex-col gap-1">
      <span class="text-zinc-400 text-xs uppercase tracking-widest">
        Apple ID password (leave blank to keep current)
      </span>
      <input type="password" bind:value={newPassword} placeholder="••••••••"
        class="bg-[#1a1a1a] border border-[#333] rounded-lg px-3 py-2 text-white text-sm outline-none focus:border-[#1db954] transition-colors" />
    </label>

    {#if error}
      <div class="text-red-400 text-sm bg-red-950 border border-red-800 rounded-lg px-3 py-2">{error}</div>
    {/if}

    <button onclick={save} disabled={saving}
      class="bg-[#1db954] text-black font-bold py-2 rounded-lg hover:bg-[#1ed760] transition-colors disabled:opacity-50 mt-2">
      {saving ? "Saving…" : saved ? "✓ Saved" : "Save changes"}
    </button>
  </div>
</div>
