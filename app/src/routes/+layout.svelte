<script lang="ts">
  import { onMount } from 'svelte';
  import '../app.css';
  import { applyTheme, getStoredTheme } from '$lib/themes';
  let { children } = $props();

  onMount(() => applyTheme(getStoredTheme()));
</script>

{@render children()}
