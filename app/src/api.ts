import { invoke } from "@tauri-apps/api/core";

let _port: number | null = null;

async function getPort(): Promise<number> {
  if (_port !== null) return _port;
  _port = await invoke<number>("get_api_port");
  return _port;
}

async function base(): Promise<string> {
  return `http://127.0.0.1:${await getPort()}`;
}

export interface Playlist {
  name: string;
  url: string;
  last_synced: string | null;
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
  status: "running" | "done" | "error";
  new_so_far?: number;
  new?: number;
  skipped?: number;
  errors?: number;
  message?: string;
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

  async library(): Promise<Record<string, Track[]>> {
    const r = await fetch(`${await base()}/library`);
    return r.json();
  },

  async trackArtUrl(localPath: string): Promise<string> {
    return `${await base()}/track-art?path=${encodeURIComponent(localPath)}`;
  },

  async syncUrl(name: string): Promise<string> {
    return `${await base()}/sync/${encodeURIComponent(name)}`;
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
};
