<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { api, type QueueStatus, type QueueJob } from "../api";

  interface Props {
    onopenSync?: () => void;
  }
  let { onopenSync }: Props = $props();

  let status = $state<QueueStatus | null>(null);
  let showPopover = $state(false);
  let interval: ReturnType<typeof setInterval> | null = null;

  async function poll() {
    try {
      status = await api.queue();
    } catch {}
  }

  onMount(() => {
    poll();
    interval = setInterval(poll, 2000);
  });

  onDestroy(() => {
    if (interval !== null) clearInterval(interval);
  });

  function jobLabel(job: QueueJob): string {
    return job.playlist_name ?? "Download";
  }

  let isActive = $derived(status?.active != null);
  let pendingCount = $derived(status?.pending.length ?? 0);
</script>

{#if isActive || pendingCount > 0}
  <div class="relative mx-2 mb-2">
    <button
      onclick={() => { if (onopenSync && isActive) { onopenSync(); } else { showPopover = !showPopover; } }}
      class="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-[#1a1a1a] border border-[var(--accent-dim)] text-xs text-zinc-300 hover:border-[var(--accent)] transition-colors"
      title={isActive && onopenSync ? "View sync progress" : undefined}
    >
      <span class="w-2.5 h-2.5 border border-[var(--accent)] border-t-transparent rounded-full animate-spin flex-shrink-0"></span>
      <span class="truncate flex-1 text-left">
        {#if status?.active}
          {jobLabel(status.active)}
        {/if}
      </span>
      {#if pendingCount > 0}
        <span class="text-zinc-600 flex-shrink-0">+{pendingCount}</span>
      {/if}
    </button>

    {#if showPopover}
      <div
        class="absolute bottom-full left-0 right-0 mb-1 bg-[#111] border border-[#2a2a2a] rounded-lg p-2 z-50 shadow-xl"
      >
        {#if status?.active}
          <div class="flex items-center gap-2 px-2 py-1.5 text-xs">
            <span class="w-2 h-2 border border-[var(--accent)] border-t-transparent rounded-full animate-spin flex-shrink-0"></span>
            <span class="text-white truncate">{jobLabel(status.active)}</span>
            <span class="text-zinc-600 ml-auto flex-shrink-0">running</span>
          </div>
        {/if}
        {#each status?.pending ?? [] as job, i}
          <div class="flex items-center gap-2 px-2 py-1.5 text-xs text-zinc-500">
            <span class="w-4 text-center text-zinc-700 flex-shrink-0">{i + 1}</span>
            <span class="truncate">{jobLabel(job)}</span>
            <span class="text-zinc-700 ml-auto flex-shrink-0">queued</span>
          </div>
        {/each}
      </div>
    {/if}
  </div>
{/if}
