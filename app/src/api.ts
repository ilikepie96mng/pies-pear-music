import { invoke } from "@tauri-apps/api/core";

interface ApiConnection {
  port: number;
  capability: string;
}

let _connection: ApiConnection | null = null;
let _isTauri: boolean | null = null;

async function getConnection(): Promise<ApiConnection> {
  if (_connection !== null) return _connection;
  try {
    _connection = await invoke<ApiConnection>("get_api_connection");
    _isTauri = true;
    return _connection;
  } catch {
    _isTauri = false;
    const token = typeof localStorage !== "undefined" ? localStorage.getItem("pies_api_token") || "" : "";
    const port = typeof window !== "undefined" && window.location.port ? parseInt(window.location.port, 10) : 10025;
    _connection = { port, capability: token };
    return _connection;
  }
}

async function base(): Promise<string> {
  const conn = await getConnection();
  if (_isTauri) {
    return `http://127.0.0.1:${conn.port}`;
  }
  if (typeof window !== "undefined" && window.location.origin && window.location.hostname !== "tauri.localhost") {
    return window.location.origin;
  }
  return `http://127.0.0.1:${conn.port}`;
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const connection = await getConnection();
  const headers: Record<string, string> = {
    ...(connection.capability ? { "X-Pies-Api-Token": connection.capability } : {}),
    ...(init.headers as Record<string, string>),
  };
  return fetch(`${await base()}${path}`, {
    ...init,
    headers,
  });
}

export async function streamEvents(
  path: string,
  onEvent: (event: SyncEvent) => void | Promise<void>,
  signal?: AbortSignal,
): Promise<void> {
  const response = await request(path, { signal });
  if (!response.ok || !response.body) throw new Error(`Stream request failed (${response.status})`);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      pending += decoder.decode(value, { stream: true });
      const messages = pending.split("\n\n");
      pending = messages.pop() ?? "";
      for (const message of messages) {
        const data = message
          .split("\n")
          .filter((line) => line.startsWith("data: "))
          .map((line) => line.slice(6))
          .join("\n");
        if (data) await onEvent(JSON.parse(data) as SyncEvent);
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export interface Playlist {
  name: string;
  url: string;
  last_synced: string | null;
  paused: boolean;
  thumbnail_url: string | null;
}

export interface Track {
  track_id: string;
  title: string;
  artist: string;
  album: string;
  local_path: string;
  downloaded_at: string;
  artwork_url: string | null;
  has_lyrics?: boolean;
}

export interface DapExportResult {
  status: string;
  playlist_name: string;
  format: string;
  bitrate: string;
  target_dir: string;
  export_dir: string;
  exported_count: number;
  skipped_count: number;
  error_count: number;
  playlist_file: string;
  files: string[];
}

export interface GraveyardTrack {
  playlist_name: string;
  track_id: string;
  delisted_at: string;
  title: string;
  artist: string;
  album: string;
  local_path: string;
  artwork_url: string | null;
}

export interface LyricLine {
  time_ms?: number;
  timestamp?: string;
  text: string;
}

export interface TrackLyrics {
  track_id: string;
  title: string;
  artist: string;
  album: string;
  lyrics: string;
  synced: boolean;
  source: "lrc" | "embedded" | "am_api" | "lrclib" | "none";
  lines?: LyricLine[];
}

export interface AudioWaveform {
  track_id: string;
  points: number;
  duration: number;
  peaks: number[];
}

export interface SyncEvent {
  status: "queued" | "running" | "done" | "error";
  position?: number;
  phase?: string;
  message?: string;
  new?: number;
  skipped?: number;
  errors?: number;
  log_path?: string;
}

export interface DuplicateTrackInfo {
  title: string;
  artist: string;
  album: string;
  count: number;
  track_ids: string[];
}

export interface SmartPlaylistRule {
  field: "title" | "artist" | "album" | "local_path" | "downloaded_at" | "playlist" | "format";
  operator: "equals" | "not_equals" | "contains" | "not_contains" | "starts_with" | "ends_with" | "regex" | "in_past_days" | "before_date" | "after_date" | "is_empty" | "is_not_empty";
  value?: string | number;
}

export interface SmartPlaylistRulesConfig {
  match?: "all" | "any";
  rules: SmartPlaylistRule[];
  sort_by?: "downloaded_at" | "title" | "artist" | "album" | "random";
  sort_order?: "asc" | "desc";
  limit?: number;
}

export interface SmartPlaylist {
  id: number;
  name: string;
  description: string | null;
  rules_json: string;
  rules?: SmartPlaylistRulesConfig;
  track_count?: number;
  tracks?: LibraryTrack[];
  created_at: string;
  updated_at: string;
}

export interface DeduplicateResult {
  status: string;
  playlist_name: string;
  duplicates_found: number;
  removed_count: number;
  removed_track_ids: string[];
}

export interface IntegrationsHealth {
  gemini: boolean;
  lastfm: boolean;
  jellyfin: boolean;
  navidrome: boolean;
  strawberry: boolean;
}

export type QueueStatus = QueueSummary;

export interface DiagnosticCheck {
  label: string;
  ok: boolean;
  detail?: string;
}

export interface Stats {
  playlist_count: number;
  total_tracks: number;
  last_sync: string | null;
  playlists: { name: string; track_count: number; last_synced: string | null }[];
}

export interface SyncRun {
  id: number;
  playlist_name: string;
  started_at: string;
  ended_at: string;
  status: "success" | "error";
  new_count: number;
  skipped_count: number;
  error_count: number;
  log_path: string;
  error_message: string | null;
}

export interface RecentTrack {
  title: string;
  artist: string;
  album: string;
  local_path: string;
  artwork_url: string | null;
  downloaded_at: string;
}

export interface BatchTagFields {
  title?: string;
  artist?: string;
  album?: string;
  album_artist?: string;
  genre?: string;
  year?: string;
  track_num?: number;
  disc_num?: number;
  lyrics?: string;
  comment?: string;
}

export interface BatchTagRequest {
  track_ids: string[];
  fields: BatchTagFields;
  cover_art_base64?: string | null;
  cover_art_mime?: string;
  remove_cover?: boolean;
  reorganize_files?: boolean;
}

export interface BatchTagResponse {
  updated: number;
  total_requested: number;
  errors: string[];
  tracks: Array<{
    track_id: string;
    title: string;
    artist: string;
    album: string;
    local_path: string;
  }>;
}

export interface Recommendation {
  artist: string;
  similar_to: string;
  reason: string;
  match: number;
  lastfm_url: string;
}

export interface RecommendedTrack {
  name: string;
  url: string;
  artist: string;
}

export interface RecommendedAlbum {
  name: string;
  url: string;
  artist: string;
  image_url: string | null;
}

export interface HomeData {
  recent_tracks: RecentTrack[];
  recommendations: Recommendation[];
  recommended_tracks: RecommendedTrack[];
  recommended_albums: RecommendedAlbum[];
  recommendations_available: boolean;
  recommendation_source: "live" | "cached" | "unavailable";
  recommendations_updated_at: string | null;
  last_sync: { run_id: number; playlist_name: string; started_at: string; synced_at: string; new_tracks: number } | null;
}

export interface LibraryTrack {
  track_id: string;
  title: string;
  artist: string;
  album: string;
  local_path: string;
  downloaded_at: string;
  artwork_url: string | null;
  playlists: string[];
  has_lyrics: boolean;
  format: string;
  file_size: number;
  exists_on_disk: boolean;
}

export interface LibraryStats {
  total_tracks: number;
  total_albums: number;
  total_artists: number;
  total_playlists: number;
  delisted_count: number;
  total_bytes: number;
}

export interface AuditMissingTrack {
  track_id: string;
  title: string;
  artist: string;
  album: string;
  local_path: string;
  playlists?: string[];
}

export interface AuditOrphanFile {
  path: string;
  name: string;
  size: number;
  relative_path: string;
}

export interface LibraryAuditReport {
  missing_files: AuditMissingTrack[];
  orphaned_files: AuditOrphanFile[];
  missing_lyrics: AuditMissingTrack[];
  missing_art: AuditMissingTrack[];
  summary: {
    total_db_tracks: number;
    missing_files_count: number;
    orphaned_files_count: number;
    missing_lyrics_count: number;
    missing_art_count: number;
  };
}

export interface IntegrityErrorTrack {
  track_id: string;
  title: string;
  artist: string;
  album: string;
  local_path: string;
  error: string;
}

export interface LibraryIntegrityReport {
  checked_count: number;
  corrupted: IntegrityErrorTrack[];
  status: "ok" | "errors_found";
}

export interface DuplicateTrackItem {
  track_id: string;
  title: string;
  artist: string;
  album: string;
  local_path: string;
  file_exists: boolean;
  file_size: number;
  format: string;
  downloaded_at: string;
  am_track_id?: string | null;
  artwork_url?: string | null;
  playlists: string[];
  has_collision_suffix: boolean;
  album_is_single: boolean;
  is_recommended?: boolean;
}

export interface DuplicateGroup {
  group_id: string;
  title: string;
  artist: string;
  track_count: number;
  reclaimable_bytes: number;
  tracks: DuplicateTrackItem[];
}

export interface LibraryDuplicatesReport {
  total_groups: number;
  total_duplicate_tracks: number;
  total_reclaimable_bytes: number;
  groups: DuplicateGroup[];
}

export interface LibraryDeduplicateResult {
  status: string;
  processed_groups: number;
  removed_tracks_count: number;
  deleted_files_count: number;
  freed_bytes: number;
  remapped_playlist_references: number;
  repaired_playlists_count: number;
}

export interface LibraryRepairResult {
  status?: string;
  action?: string;
  pruned_count?: number;
  repaired_count?: number;
  playlists?: string[];
  adopted_count?: number;
  adopted?: { track_id: string; title: string; artist: string; album: string; local_path: string }[];
}

export interface DownloadRequestItem {
  id: string;
  url: string;
  format: string;
  requester: string;
  status: string;
  notes: string;
  created_at: string;
}

export interface ImportMatchResult {
  original_title: string;
  original_artist: string;
  original_album: string;
  original_isrc: string;
  matched: boolean;
  match_score: number;
  am_track?: {
    id: string;
    title: string;
    artist: string;
    album: string;
    url?: string;
  } | null;
}

export interface GeminiTrackItem {
  title: string;
  artist: string;
  album: string;
  rationale: string;
  matched?: boolean;
  in_library?: boolean;
  artwork_url?: string | null;
  local_track?: LibraryTrack | null;
  am_track?: {
    id: string;
    title: string;
    artist: string;
    album: string;
    url?: string;
    artwork_url?: string | null;
  } | null;
}

export interface GeminiPlaylistResult {
  playlist_title: string;
  description: string;
  vibe_tags: string[];
  tracks: GeminiTrackItem[];
}

export interface CatalogSong {
  id: string;
  title: string;
  artist: string;
  album: string;
  url?: string;
  artwork_url?: string | null;
  isrc?: string;
}

export interface CatalogTrack {
  id: string;
  title: string;
  artist: string;
  album: string;
  track_number: number;
  disc_number: number;
  duration_ms: number;
  url?: string;
  artwork_url?: string | null;
  isrc?: string;
}

export interface CatalogAlbum {
  id: string;
  title: string;
  artist: string;
  release_date: string;
  record_label?: string;
  genre_names?: string[];
  track_count: number;
  artwork_url?: string | null;
  url?: string;
  is_single?: boolean;
  is_compilation?: boolean;
  is_complete?: boolean;
  tracks?: CatalogTrack[];
}

export interface CatalogArtist {
  id: string;
  name: string;
  url?: string;
  artwork_url?: string | null;
  genres?: string[];
  genre_names?: string[];
  album_count?: number;
  albums?: CatalogAlbum[];
}

export interface CatalogSearchResult {
  songs: CatalogSong[];
  albums: CatalogAlbum[];
  artists: CatalogArtist[];
}

export interface StorageTestResult {
  path: string;
  exists: boolean;
  is_dir: boolean;
  writable: boolean;
  free_space_bytes: number;
  free_space_formatted: string;
  latency_ms: number;
  message: string;
}

export const api = {
  async playlists(): Promise<Playlist[]> {
    const r = await request("/playlists");
    return r.json();
  },

  async playlistTracks(name: string): Promise<Track[]> {
    const r = await request(`/playlists/${encodeURIComponent(name)}/tracks`);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async addPlaylist(name: string, url: string): Promise<Playlist> {
    const r = await request("/playlists", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, url }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async deletePlaylist(name: string): Promise<void> {
    await request(`/playlists/${encodeURIComponent(name)}`, {
      method: "DELETE",
    });
  },

  async patchPlaylist(name: string, patch: { name?: string; paused?: boolean }): Promise<Playlist> {
    const r = await request(`/playlists/${encodeURIComponent(name)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async library(): Promise<Record<string, Track[]>> {
    const r = await request("/library");
    return r.json();
  },

  async allLibraryTracks(): Promise<LibraryTrack[]> {
    const r = await request("/library/tracks");
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async libraryStats(): Promise<LibraryStats> {
    const r = await request("/library/stats");
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async auditLibrary(): Promise<LibraryAuditReport> {
    const r = await request("/library/audit");
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async getLibraryDuplicates(): Promise<LibraryDuplicatesReport> {
    const r = await request("/library/duplicates");
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async deduplicateLibrary(payload?: {
    keep_criteria?: string;
    delete_files?: boolean;
    remap_playlists?: boolean;
    group_ids?: string[];
  }): Promise<LibraryDeduplicateResult> {
    const r = await request("/library/deduplicate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Deduplication failed (${r.status})`);
    }
    return r.json();
  },

  async verifyIntegrity(limit?: number): Promise<LibraryIntegrityReport> {
    const r = await request("/library/verify-integrity", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async repairLibrary(action: string, payload?: { track_ids?: string[]; file_paths?: string[] }): Promise<LibraryRepairResult> {
    const r = await request("/library/repair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, ...payload }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Repair failed (${r.status})`);
    }
    return r.json();
  },

  async trackArtUrl(localPath: string): Promise<string> {
    const response = await request(`/track-art?path=${encodeURIComponent(localPath)}`);
    if (!response.ok) return "";
    return URL.createObjectURL(await response.blob());
  },

  async stats(): Promise<Stats> {
    const r = await request("/stats");
    return r.json();
  },

  async diagnostics(): Promise<DiagnosticCheck[]> {
    const r = await request("/diagnostics");
    return r.json();
  },

  async syncQueue(): Promise<QueueStatus> {
    const r = await request("/sync/queue");
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },

  async config(): Promise<Record<string, any>> {
    const r = await request("/config");
    return r.json();
  },

  async updateConfig(updates: Partial<Record<string, any>>): Promise<void> {
    const r = await request("/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    if (!r.ok) throw new Error(await r.text());
  },

  async importDatabase(file: File): Promise<{ status: string; total_tracks: number; total_playlists: number }> {
    const arrayBuffer = await file.arrayBuffer();
    const r = await request("/database/import", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: arrayBuffer,
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async testJellyfin(serverUrl: string, apiKey: string): Promise<{ success: boolean; message: string }> {
    const r = await request("/integrations/jellyfin/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ server_url: serverUrl, api_key: apiKey }),
    });
    if (!r.ok) {
      const text = await r.text();
      return { success: false, message: `Server error (${r.status}): ${text}` };
    }
    return r.json();
  },

  async testNavidrome(serverUrl: string, user: string, token: string, salt: string): Promise<{ success: boolean; message: string }> {
    const r = await request("/integrations/navidrome/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ server_url: serverUrl, user, token, salt }),
    });
    if (!r.ok) {
      const text = await r.text();
      return { success: false, message: `Server error (${r.status}): ${text}` };
    }
    return r.json();
  },

  async downloadRequests(status?: string): Promise<DownloadRequestItem[]> {
    const url = status ? `/api/v1/requests?status=${encodeURIComponent(status)}` : "/api/v1/requests";
    const r = await request(url);
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },

  async createDownloadRequest(url: string, format: string = "ALAC", requester: string = "local", notes: string = ""): Promise<DownloadRequestItem> {
    const r = await request("/api/v1/requests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, format, requester, notes }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async parsePlaylistImport(sourceType: "url" | "csv" | "m3u", content: string): Promise<{ source_type: string; track_count: number; matches: ImportMatchResult[] }> {
    const r = await request("/playlist/parse-import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_type: sourceType, content }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async curateGemini(
    prompt: string,
    trackCount: number = 20,
    model?: string,
    libraryOnly: boolean = false,
  ): Promise<GeminiPlaylistResult> {
    const r = await request("/gemini/curate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt,
        track_count: trackCount,
        model: model || undefined,
        library_only: libraryOnly,
      }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || "Gemini curation failed");
    }
    return r.json();
  },

  async downloadGeminiTracks(
    tracks: Array<{ url?: string; am_track?: { url?: string; id?: string } | null; title?: string; artist?: string }>,
    format: string = "ALAC",
  ): Promise<{ queued: number; job_ids: string[] }> {
    const r = await request("/gemini/download-tracks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tracks, format }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to queue track downloads");
    }
    return r.json();
  },

  async getGeminiModels(): Promise<string[]> {
    const r = await request("/gemini/models");
    if (!r.ok) return [];
    const data = await r.json().catch(() => ({ models: [] }));
    return data.models || [];
  },

  async saveGeminiPlaylist(name: string, tracks: unknown[], prompt: string = ""): Promise<Playlist> {
    const r = await request("/gemini/save-playlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, tracks, prompt }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to save playlist");
    }
    return r.json();
  },

  async home(): Promise<HomeData> {
    const r = await request("/home");
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },

  async libraryProfile(): Promise<Record<string, unknown>> {
    const r = await request("/library-profile");
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async excludeRecommendationArtist(artist: string): Promise<void> {
    const r = await request("/recommendations/exclusions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ artist }),
    });
    if (!r.ok) throw new Error(await r.text());
  },

  async recommendationExclusions(): Promise<string[]> {
    const r = await request("/recommendations/exclusions");
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json() as { artists: string[] };
    return data.artists;
  },

  async includeRecommendationArtist(artist: string): Promise<void> {
    const r = await request(`/recommendations/exclusions/${encodeURIComponent(artist)}`, { method: "DELETE" });
    if (!r.ok) throw new Error(await r.text());
  },

  async clearRecommendationExclusions(): Promise<void> {
    const r = await request("/recommendations/exclusions", { method: "DELETE" });
    if (!r.ok) throw new Error(await r.text());
  },

  async recommendationPreferences(): Promise<{ genres: string[] }> {
    const r = await request("/recommendations/preferences");
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async updateRecommendationPreferences(genres: string[]): Promise<{ genres: string[] }> {
    const r = await request("/recommendations/preferences", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ genres }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async syncRunTracks(runId: number): Promise<{ run_id: number; playlist_name: string; tracks: RecentTrack[] }> {
    const r = await request(`/sync-runs/${runId}/tracks`);
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },

  async strawberryExport(playlistName: string): Promise<{ removed: number; inserted: number; playlist_id: number; backup: string }> {
    const r = await request("/strawberry/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ playlist_name: playlistName }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `${r.status}`);
    }
    return r.json();
  },

  async playlistM3u(playlistName: string): Promise<string> {
    const r = await request(`/playlists/${encodeURIComponent(playlistName)}/m3u`);
    if (!r.ok) throw new Error(await r.text());
    return r.text();
  },

  async savePlaylistM3u(playlistName: string, path: string): Promise<void> {
    const r = await request(`/playlists/${encodeURIComponent(playlistName)}/m3u/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    if (!r.ok) throw new Error(await r.text());
  },

  async revealTrack(localPath: string): Promise<void> {
    const r = await request("/reveal-track", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ local_path: localPath }),
    });
    if (!r.ok) throw new Error(await r.text());
  },

  async syncHistory(playlistName?: string, limit = 30): Promise<SyncRun[]> {
    const url = playlistName
      ? `/sync-history/${encodeURIComponent(playlistName)}?limit=${limit}`
      : `/sync-history?limit=${limit}`;
    const r = await request(url);
    return r.json();
  },

  async exportDap(
    playlistName: string,
    targetDir: string,
    format: string = "opus",
    bitrate?: string,
  ): Promise<DapExportResult> {
    const r = await request("/export/dap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        playlist_name: playlistName,
        target_dir: targetDir,
        format,
        ...(bitrate ? { bitrate } : {}),
      }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Export failed (${r.status})`);
    }
    return r.json();
  },

  async getStreamingGraveyard(playlistName?: string): Promise<{ tracks: GraveyardTrack[]; count: number }> {
    const url = playlistName
      ? `/streaming-graveyard?playlist_name=${encodeURIComponent(playlistName)}`
      : "/streaming-graveyard";
    const r = await request(url);
    if (!r.ok) throw new Error(`Failed to load streaming graveyard (${r.status})`);
    return r.json();
  },

  async getTrackLyrics(trackId: string): Promise<TrackLyrics> {
    const r = await request(`/api/v1/tracks/lyrics?track_id=${encodeURIComponent(trackId)}`);
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to load lyrics (${r.status})`);
    }
    return r.json();
  },

  async getStreamUrl(trackId: string): Promise<string> {
    const conn = await getConnection();
    return `http://127.0.0.1:${conn.port}/api/v1/stream?track_id=${encodeURIComponent(trackId)}&token=${encodeURIComponent(conn.capability)}`;
  },

  async getWaveform(trackId: string, points: number = 100): Promise<AudioWaveform> {
    const r = await request(`/api/v1/waveform?track_id=${encodeURIComponent(trackId)}&points=${points}`);
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to load waveform (${r.status})`);
    }
    return r.json();
  },

  async getPlaylistDuplicates(playlistName: string): Promise<{ playlist_name: string; duplicates: DuplicateTrackInfo[]; count: number }> {
    const r = await request(`/playlists/${encodeURIComponent(playlistName)}/duplicates`);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async deduplicatePlaylist(playlistName: string): Promise<DeduplicateResult> {
    const r = await request(`/playlists/${encodeURIComponent(playlistName)}/deduplicate`, {
      method: "POST",
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async getIntegrationsHealth(): Promise<IntegrationsHealth> {
    const r = await request("/system/integrations-health");
    if (!r.ok) {
      return { gemini: false, lastfm: false, jellyfin: false, navidrome: false, strawberry: false };
    }
    return r.json();
  },

  async getSmartPlaylists(): Promise<SmartPlaylist[]> {
    const r = await request("/smart-playlists");
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async createSmartPlaylist(name: string, description: string = "", rules: SmartPlaylistRulesConfig): Promise<SmartPlaylist> {
    const r = await request("/smart-playlists", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description, rules }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async getSmartPlaylist(id: number): Promise<SmartPlaylist> {
    const r = await request(`/smart-playlists/${id}`);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async updateSmartPlaylist(
    id: number,
    data: { name?: string; description?: string; rules?: SmartPlaylistRulesConfig }
  ): Promise<SmartPlaylist> {
    const r = await request(`/smart-playlists/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async deleteSmartPlaylist(id: number): Promise<void> {
    const r = await request(`/smart-playlists/${id}`, { method: "DELETE" });
    if (!r.ok) throw new Error(await r.text());
  },

  async previewSmartPlaylist(rules: SmartPlaylistRulesConfig): Promise<{ tracks: LibraryTrack[]; track_count: number }> {
    const r = await request("/smart-playlists/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rules }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async batchTagTracks(payload: BatchTagRequest): Promise<BatchTagResponse> {
    const r = await request("/api/v1/tracks/batch-tag", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Batch tagging failed (${r.status})`);
    }
    return r.json();
  },

  async getTrackCoverUrl(trackId: string): Promise<string> {
    const conn = await getConnection();
    return `http://127.0.0.1:${conn.port}/api/v1/tracks/cover?track_id=${encodeURIComponent(trackId)}&token=${encodeURIComponent(conn.capability)}`;
  },

  async resyncArtwork(): Promise<{ running: boolean; total: number; processed: number; updated: number; message: string; error?: string | null }> {
    const r = await request("/library/resync-artwork", { method: "POST" });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Artwork resync failed (${r.status})`);
    }
    return r.json();
  },

  async getArtworkResyncStatus(): Promise<{ running: boolean; total: number; processed: number; updated: number; message: string; error?: string | null }> {
    const r = await request("/library/resync-artwork/status");
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to get artwork status (${r.status})`);
    }
    return r.json();
  },

  async searchCatalog(
    query: string,
    types: string[] = ["songs", "albums", "artists"],
    limit: number = 8,
  ): Promise<CatalogSearchResult> {
    const typesParam = types.join(",");
    const r = await request(`/catalog/search?q=${encodeURIComponent(query)}&types=${encodeURIComponent(typesParam)}&limit=${limit}`);
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Catalog search failed (${r.status})`);
    }
    return r.json();
  },

  async catalogAlbum(idOrUrl: string): Promise<CatalogAlbum> {
    const isUrl = idOrUrl.startsWith("http");
    const param = isUrl ? `url=${encodeURIComponent(idOrUrl)}` : `id=${encodeURIComponent(idOrUrl)}`;
    const r = await request(`/catalog/album?${param}`);
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to fetch album (${r.status})`);
    }
    return r.json();
  },

  async catalogArtist(idOrUrl: string): Promise<CatalogArtist> {
    const isUrl = idOrUrl.startsWith("http");
    const param = isUrl ? `url=${encodeURIComponent(idOrUrl)}` : `id=${encodeURIComponent(idOrUrl)}`;
    const r = await request(`/catalog/artist?${param}`);
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to fetch artist discography (${r.status})`);
    }
    return r.json();
  },

  async downloadAlbum(urlOrId: string, format: string = "ALAC"): Promise<{ queued: number; job_ids: string[] }> {
    const isUrl = urlOrId.startsWith("http");
    const payload = isUrl ? { url: urlOrId, format } : { album_id: urlOrId, format };
    const r = await request("/download/album", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to queue album download (${r.status})`);
    }
    return r.json();
  },

  async downloadArtistAlbums(
    albums: Array<{ id?: string; album_id?: string; url?: string; title?: string }>,
    format: string = "ALAC",
    artistId?: string,
  ): Promise<{ queued: number; job_ids: string[] }> {
    const r = await request("/download/artist-albums", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ artist_id: artistId, albums, format }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to queue artist albums (${r.status})`);
    }
    return r.json();
  },

  wrapper: {
    async login(email: string, password: string): Promise<{ status: string; msg: string }> {
      const r = await request("/wrapper/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      return r.json();
    },

    async stop(): Promise<{ status: string; msg: string }> {
      const r = await request("/wrapper/stop", { method: "POST" });
      return r.json();
    },

    async restart(): Promise<{ status: string; msg: string }> {
      const r = await request("/wrapper/restart", { method: "POST" });
      return r.json();
    },

    async logout(): Promise<{ status: string; msg: string }> {
      const r = await request("/wrapper/logout", { method: "POST" });
      return r.json();
    },

    async submit2fa(code: string): Promise<{ status: string; msg: string }> {
      const r = await request("/wrapper/2fa", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      return r.json();
    },

    async status(): Promise<{
      running: boolean;
      logging_in?: boolean;
      needs_2fa: boolean;
      "2fa_type": string;
      has_saved_credentials?: boolean;
      logs: string[];
    }> {
      const r = await request("/wrapper/status");
      return r.json();
    },
  },

  async testStoragePath(path: string): Promise<StorageTestResult> {
    const r = await request("/api/v1/storage/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Storage test failed (${r.status})`);
    }
    return r.json();
  },

  async resolveSmb(uri: string): Promise<{ uri: string; resolved_path: string | null; found: boolean }> {
    const r = await request("/api/v1/storage/resolve-smb", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ uri }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `SMB resolution failed (${r.status})`);
    }
    return r.json();
  },

  async generateNavidromeToken(password: string): Promise<{ token: string; salt: string }> {
    const r = await request("/api/v1/integrations/navidrome/generate-token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Token generation failed (${r.status})`);
    }
    return r.json();
  },

  queue: {
    async get(): Promise<QueueSummary> {
      const r = await request("/api/v1/queue");
      if (!r.ok) throw new Error(`Failed to fetch queue (${r.status})`);
      return r.json();
    },

    async add(payload: {
      urls?: string[];
      items?: Array<{
        url?: string;
        id?: string;
        album_id?: string;
        title?: string;
        artist?: string;
        album?: string;
        artwork_url?: string | null;
        total_tracks?: number;
        item_type?: string;
      }>;
      format?: string;
      batch_id?: string;
      batch_title?: string;
    }): Promise<{ queued: number; job_ids: number[]; batch_id?: string }> {
      const r = await request("/api/v1/queue/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || `Failed to add items to queue (${r.status})`);
      }
      return r.json();
    },

    async cancel(params: { jobId?: number; batchId?: string; cancelAll?: boolean }): Promise<{ cancelled: number }> {
      const r = await request("/api/v1/queue/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: params.jobId,
          batch_id: params.batchId,
          cancel_all: params.cancelAll ?? false,
        }),
      });
      if (!r.ok) throw new Error(`Failed to cancel queue items (${r.status})`);
      return r.json();
    },

    async retry(jobIds?: number[]): Promise<{ retried: number }> {
      const r = await request("/api/v1/queue/retry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_ids: jobIds || [] }),
      });
      if (!r.ok) throw new Error(`Failed to retry jobs (${r.status})`);
      return r.json();
    },

    async clear(olderThanDays: number = 0): Promise<{ cleared: number }> {
      const r = await request(`/api/v1/queue/clear?older_than_days=${olderThanDays}`, {
        method: "POST",
      });
      if (!r.ok) throw new Error(`Failed to clear queue (${r.status})`);
      return r.json();
    },

    async reorder(jobId: number, newPosition: number): Promise<{ reordered: boolean }> {
      const r = await request("/api/v1/queue/reorder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: jobId, new_position: newPosition }),
      });
      if (!r.ok) throw new Error(`Failed to reorder job (${r.status})`);
      return r.json();
    },
  },

  scheduler: {
    async getStatus(): Promise<SchedulerStatus> {
      const r = await request("/api/v1/scheduler/status");
      if (!r.ok) throw new Error(`Failed to get scheduler status (${r.status})`);
      return r.json();
    },

    async trigger(): Promise<{ status: string }> {
      const r = await request("/api/v1/scheduler/trigger", { method: "POST" });
      if (!r.ok) throw new Error(`Failed to trigger scheduler (${r.status})`);
      return r.json();
    },

    async updateConfig(enabled: boolean, intervalMinutes: number): Promise<SchedulerStatus> {
      const r = await request("/api/v1/scheduler/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled, interval_minutes: intervalMinutes }),
      });
      if (!r.ok) throw new Error(`Failed to update scheduler config (${r.status})`);
      return r.json();
    },
  },

  integrations: {
    async testWebhook(req: {
      service: string;
      url?: string;
      token?: string;
      chat_id?: string;
      api_key?: string;
      user?: string;
      salt?: string;
    }): Promise<{ success: boolean; message: string }> {
      const r = await request("/api/v1/integrations/test-webhook", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      });
      if (!r.ok) throw new Error(`Failed to test webhook (${r.status})`);
      return r.json();
    },
  },
};

export interface SchedulerStatus {
  enabled: boolean;
  running: boolean;
  interval_minutes: number;
  last_run_time: string | null;
  last_run_status: string;
  last_run_message: string;
  run_count: number;
}

export interface QueueJob {
  id: number | string;
  batch_id?: string | null;
  batch_title?: string | null;
  url: string;
  title: string;
  artist?: string;
  album?: string;
  artwork_url?: string | null;
  format: string;
  status: "pending" | "running" | "done" | "error" | "cancelled";
  item_type?: "album" | "single" | "playlist" | "direct";
  total_tracks?: number;
  new_tracks?: number;
  skipped_tracks?: number;
  error_count?: number;
  error_message?: string | null;
  log_path?: string | null;
  position?: number;
  created_at?: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface QueueSummary {
  active: QueueJob | null;
  pending: QueueJob[];
  completed: QueueJob[];
  counts: {
    pending: number;
    running: number;
    done: number;
    error: number;
    cancelled: number;
    total: number;
  };
}
