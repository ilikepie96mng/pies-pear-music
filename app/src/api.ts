import { invoke } from "@tauri-apps/api/core";

let _port: number | null = null;

async function getPort(): Promise<number> {
  if (_port !== null) return _port;
  const cached = sessionStorage.getItem("api_port");
  if (cached) {
    _port = parseInt(cached, 10);
    return _port;
  }
  _port = await invoke<number>("get_api_port");
  sessionStorage.setItem("api_port", String(_port));
  return _port;
}

async function base(): Promise<string> {
  return `http://127.0.0.1:${await getPort()}`;
}

export interface Playlist {
  name: string;
  url: string;
  last_synced: string | null;
  paused: boolean;
}

export interface Track {
  track_id: string;
  title: string;
  artist: string;
  album: string;
  local_path: string;
  downloaded_at: string;
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

export interface QueueJob {
  id: string;
  type: "playlist" | "one-off";
  playlist_name: string | null;
  url: string | null;
}

export interface QueueStatus {
  active: QueueJob | null;
  pending: QueueJob[];
}

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

export const api = {
  async playlists(): Promise<Playlist[]> {
    const r = await fetch(`${await base()}/playlists`);
    return r.json();
  },

  async addPlaylist(name: string, url: string): Promise<Playlist> {
    const r = await fetch(`${await base()}/playlists`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, url }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async deletePlaylist(name: string): Promise<void> {
    await fetch(`${await base()}/playlists/${encodeURIComponent(name)}`, {
      method: "DELETE",
    });
  },

  async patchPlaylist(name: string, patch: { name?: string; paused?: boolean }): Promise<Playlist> {
    const r = await fetch(`${await base()}/playlists/${encodeURIComponent(name)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async library(): Promise<Record<string, Track[]>> {
    const r = await fetch(`${await base()}/library`);
    return r.json();
  },

  trackArtUrl(localPath: string): string {
    if (_port === null) return "";
    return `http://127.0.0.1:${_port}/track-art?path=${encodeURIComponent(localPath)}`;
  },

  syncJobUrl(name: string, format: string = "ALAC"): string {
    if (_port === null) throw new Error("Port not yet known");
    return `http://127.0.0.1:${_port}/sync/${encodeURIComponent(name)}?format=${encodeURIComponent(format)}`;
  },

  async stats(): Promise<Stats> {
    const r = await fetch(`${await base()}/stats`);
    return r.json();
  },

  async diagnostics(): Promise<DiagnosticCheck[]> {
    const r = await fetch(`${await base()}/diagnostics`);
    return r.json();
  },

  async queue(): Promise<QueueStatus> {
    const r = await fetch(`${await base()}/sync/queue`);
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },

  async config(): Promise<Record<string, string>> {
    const r = await fetch(`${await base()}/config`);
    return r.json();
  },

  async updateConfig(updates: Partial<Record<string, string>>): Promise<void> {
    const r = await fetch(`${await base()}/config`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    if (!r.ok) throw new Error(await r.text());
  },

  async syncHistory(playlistName?: string, limit = 30): Promise<SyncRun[]> {
    const url = playlistName
      ? `${await base()}/sync-history/${encodeURIComponent(playlistName)}?limit=${limit}`
      : `${await base()}/sync-history?limit=${limit}`;
    const r = await fetch(url);
    return r.json();
  },

  wrapper: {
    async login(email: string, password: string): Promise<{ status: string; msg: string }> {
      const r = await fetch(`${await base()}/wrapper/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      return r.json();
    },

    async stop(): Promise<{ status: string; msg: string }> {
      const r = await fetch(`${await base()}/wrapper/stop`, { method: "POST" });
      return r.json();
    },

    async submit2fa(code: string): Promise<{ status: string; msg: string }> {
      const r = await fetch(`${await base()}/wrapper/2fa`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      return r.json();
    },

    async status(): Promise<{ running: boolean; needs_2fa: boolean; logs: string[] }> {
      const r = await fetch(`${await base()}/wrapper/status`);
      return r.json();
    },
  },

  download: {
    oneOffUrl(url: string, format: string): string {
      if (_port === null) throw new Error("Port not yet known");
      return `http://127.0.0.1:${_port}/download/one-off?url=${encodeURIComponent(url)}&format=${encodeURIComponent(format)}`;
    },
  },
};
