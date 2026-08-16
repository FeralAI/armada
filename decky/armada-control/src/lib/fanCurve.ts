export interface CurvePoint {
  temp: number;
  pwm: number;
}

export function parseCurve(text: string | undefined): CurvePoint[] {
  if (!text) return [];
  return text
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      const [tempPart, pwmPart] = item.split(":");
      return { temp: parseInt(tempPart, 10), pwm: parseInt(pwmPart, 10) };
    })
    .filter((point) => Number.isFinite(point.temp) && Number.isFinite(point.pwm))
    .sort((a, b) => a.temp - b.temp);
}

export function formatCurve(points: CurvePoint[]): string {
  return [...points]
    .sort((a, b) => a.temp - b.temp)
    .map((point) => `${Math.round(point.temp)}:${Math.round(point.pwm)}`)
    .join(",");
}

export function slugifyCurveName(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 32);
}
