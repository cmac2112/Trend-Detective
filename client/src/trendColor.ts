// Diverging scale for trend maps: blue (decreasing) <- gray (no change) -> red (increasing).
// Interpolated in OKLab so equal steps in slope look like equal steps in colour, and the
// midpoint is a true neutral rather than a muddy mix. The map tiles are always light, so
// the light-mode steps are used in both themes.

export const DECREASE = "#2a78d6";
export const NEUTRAL = "#f0efec";
export const INCREASE = "#e34948";

type Lab = [number, number, number];

const toLinear = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const toSrgb = (c: number) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);

function hexToLab(hex: string): Lab {
  const [r, g, b] = [1, 3, 5].map((i) => toLinear(parseInt(hex.slice(i, i + 2), 16) / 255));
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}

function labToHex([L, a, b]: Lab): string {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const rgb = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ];
  return "#" + rgb.map((c) => Math.round(Math.min(1, Math.max(0, toSrgb(c))) * 255).toString(16).padStart(2, "0")).join("");
}

const LABS = { down: hexToLab(DECREASE), mid: hexToLab(NEUTRAL), up: hexToLab(INCREASE) };

/** Colour for a slope, given the symmetric limit where the scale saturates. */
export function trendColor(slope: number, limit: number): string {
  const t = limit > 0 ? Math.max(-1, Math.min(1, slope / limit)) : 0;
  const pole = t < 0 ? LABS.down : LABS.up;
  const k = Math.abs(t);
  return labToHex(LABS.mid.map((v, i) => v + (pole[i] - v) * k) as Lab);
}

/** CSS gradient matching trendColor, for the legend. */
export function legendGradient(steps = 9): string {
  const stops = Array.from({ length: steps }, (_, i) => trendColor(-1 + (2 * i) / (steps - 1), 1));
  return `linear-gradient(to right, ${stops.join(", ")})`;
}

/** A rounded, readable limit for the legend (e.g. 0.4372 -> 0.45). */
export function niceLimit(x: number): number {
  if (!(x > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(x));
  const n = x / p;
  const step = n <= 1 ? 1 : n <= 1.5 ? 1.5 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 3 ? 3 : n <= 4 ? 4 : n <= 5 ? 5 : n <= 7.5 ? 7.5 : 10;
  return step * p;
}
