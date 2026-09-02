export interface CompatTool {
  id: string;
  label: string;
}

export function defaultWindowsCompatTool(
  tools: CompatTool[],
  defaults: string[],
): string {
  const available = new Set(tools.map((tool) => tool.id));
  return defaults.find((tool) => available.has(tool)) || "";
}
