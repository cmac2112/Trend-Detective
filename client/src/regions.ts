// Shared region identity: each region on the map gets a fixed slot (A-E) that decides its
// colour everywhere - map outline, chart lines, table swatch. Colours follow the
// validated categorical palette order and are never cycled; the slot stays with the
// region even if others are removed, so a region never changes colour.

export const MAX_REGIONS = 5;
export const SLOT_LETTERS = ["A", "B", "C", "D", "E"] as const;

/** Light-mode palette, used on the (light) map tiles. Charts use the CSS variables
 *  --series-1..5, which switch to the dark-mode steps automatically. */
export const SLOT_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"] as const;

export const slotVar = (slot: number) => `var(--series-${slot + 1})`;

export interface MapRegion {
  id: number;
  slot: number;
  name: string;
  feature: GeoJSON.Feature;
}
