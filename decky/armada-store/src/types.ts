export interface LaunchSpec {
  name: string;
  exe: string;
  startDir: string;
  launchOptions: string;
}

export interface CatalogApp {
  id: string;
  name: string;
  summary: string;
  category: string;
  icon: string;
  note: string;
  installType: "flatpak" | "appimage" | "compat" | "";
  launch: LaunchSpec | null;
}

export interface Catalog {
  apps: CatalogApp[];
  home?: string;
}

export interface Job {
  appId: string;
  action: "install" | "uninstall";
  phase: string;
  percent: number | null;
  error: string;
}

export interface InstalledInfo {
  installed: boolean;
  version?: string;
}

export interface Status {
  jobs: Job[];
  installed: Record<string, InstalledInfo>;
  shortcuts: Record<string, number>;
  pending: string[];
}
