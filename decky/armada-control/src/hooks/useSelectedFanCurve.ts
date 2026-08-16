import type { Dispatch, SetStateAction } from "react";
import { formatCurve, parseCurve } from "../lib/fanCurve";
import type { CurvePoint } from "../lib/fanCurve";
import { clone, update } from "../lib/util";
import type { CurvesState } from "../types";

export function useSelectedFanCurve(
  state: CurvesState,
  setState: Dispatch<SetStateAction<CurvesState | null>>,
  selected: string,
) {
  const names = Object.keys(state.fanCurves || {}).sort();
  const curveName = names.includes(selected) ? selected : names[0] || "";
  const curve = curveName ? state.fanCurves[curveName] : undefined;
  const points = curve ? parseCurve(curve.curve) : [];
  const factoryCurve = curveName ? state.factoryFanCurves?.[curveName] : undefined;

  const commitPoints = (nextPoints: CurvePoint[]) => {
    if (!curveName) return;
    setState((current) =>
      current ? update(current, ["fanCurves", curveName, "curve"], formatCurve(nextPoints)) : current,
    );
  };

  const resetCurve = () => {
    if (!curveName || !factoryCurve) return;
    setState((current) => (current ? update(current, ["fanCurves", curveName], clone(factoryCurve)) : current));
  };

  return { names, curveName, curve, points, factoryCurve, commitPoints, resetCurve };
}
