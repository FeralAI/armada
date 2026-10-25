export {};

declare global {
  interface Window {
    SteamClient?: any;
    settingsStore?: any;
    SuspendResumeStore?: any;
    downloadsStore?: any;
    SystemPowerStore?: any;
    appDetailsStore?: any;
    Router?: any;
  }
}
