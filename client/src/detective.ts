// "Data detective" questions: what kind of place, and what are you curious about? The answers
// point to the variables most likely to show a trend there, each with a one-line reason a
// student can follow. A fixed table rather than an AI call: instant, offline, and the same
// answer every time (important in a classroom or a live demo).

export interface Choice {
  key: string;
  label: string;
  icon: string;
}

export const PLACES: Choice[] = [
  { key: "rainforest", label: "Rainforest", icon: "🌳" },
  { key: "dry", label: "Desert or dry land", icon: "🏜️" },
  { key: "farmland", label: "Farmland", icon: "🌾" },
  { key: "cold", label: "Arctic or cold sea", icon: "🧊" },
  { key: "mountains", label: "Mountains & snow", icon: "🏔️" },
  { key: "city", label: "A big city", icon: "🏙️" },
  { key: "ocean", label: "Ocean or coast", icon: "🌊" },
  { key: "lake", label: "Lake, reservoir or river basin", icon: "💧" },
];

export const INTERESTS: Choice[] = [
  { key: "heat", label: "Heat", icon: "🌡️" },
  { key: "water", label: "Water & drought", icon: "💧" },
  { key: "plants", label: "Plants", icon: "🌱" },
  { key: "air", label: "The air", icon: "💨" },
  { key: "any", label: "Anything", icon: "🔎" },
];

/** For each place: variables worth checking, most promising first, and why. */
const BY_PLACE: Record<string, [string, string][]> = {
  rainforest: [
    ["ndvi", "Clearing forest for farms and cattle makes the land less green."],
    ["precip", "Trees recycle rain back into the air, so less forest can mean less rain downwind."],
    ["evapotranspiration", "Forests 'sweat' huge amounts of water; cleared land releases less."],
    ["t2m", "Bare or grazed land warms up more than shady, evaporating forest."],
    ["root_zone_moisture", "Deep soil water dries out when rain falls and trees no longer hold the soil."],
    ["soil_moisture", "Surface soil dries faster without a forest canopy."],
  ],
  dry: [
    ["precip", "In dry places, small changes in rain decide everything else."],
    ["soil_moisture", "Shows drought directly: how wet the top of the ground is."],
    ["land_surface_temp", "Bare dry ground heats up quickly in the sun."],
    ["t2m", "Many dry regions are warming faster than the global average."],
    ["ndvi", "Sparse desert plants green up or die back with the rain."],
    ["humidity", "Drier air makes droughts worse by pulling water out of soil and plants."],
  ],
  farmland: [
    ["ndvi", "Shows how healthy crops are, and where irrigation has spread."],
    ["root_zone_moisture", "The water crops actually drink; falls in droughts and with heavy pumping."],
    ["soil_moisture", "Changes fast with rain, drought and irrigation."],
    ["evapotranspiration", "Irrigated crops pump lots of water into the air."],
    ["precip", "Rain decides how much farmers must irrigate."],
    ["t2m", "Hotter growing seasons stress crops."],
  ],
  cold: [
    ["t2m", "The Arctic is warming about four times faster than the planet as a whole."],
    ["airs_surface_temp", "A satellite check on the warming, independent of the model."],
    ["humidity", "Warmer air and open (ice-free) water add moisture to the air."],
    ["water_vapor", "Warm air holds more water vapour, itself a greenhouse gas."],
    ["snow_water", "Less snow on land around the Arctic as winters warm."],
    ["precip", "More open water and warmer air can mean more snow and rain."],
  ],
  mountains: [
    ["snow_water", "Mountain snowpack is a water tower that feeds rivers in spring and summer."],
    ["runoff", "Earlier melt changes when, and how much, water reaches rivers."],
    ["t2m", "Mountains often warm faster than the lowlands around them."],
    ["precip", "Shifts between snow and rain change the whole water supply."],
    ["root_zone_moisture", "Soils dry out earlier in the year when snow melts early."],
  ],
  city: [
    ["tropospheric_ozone", "Smog: ozone near the ground forms from traffic and industry pollution in sunlight."],
    ["land_surface_temp", "Roads and roofs make cities hotter than the countryside (the urban heat island)."],
    ["ndvi", "Growing cities replace parks and fields with concrete."],
    ["t2m", "Warming plus the heat island means more dangerous heat waves."],
    ["humidity", "Heat plus humidity decides how uncomfortable and dangerous the heat feels."],
  ],
  ocean: [
    ["t2m", "Air over the sea follows the warming ocean surface."],
    ["airs_surface_temp", "A satellite view of the same warming."],
    ["water_vapor", "A warmer ocean evaporates more water into the air."],
    ["precip", "More water vapour can mean heavier rain."],
    ["sea_level_pressure", "Shifts in pressure show changing wind and storm patterns."],
  ],
  lake: [
    ["precip", "Rain and snow over the basin fill the lake or reservoir."],
    ["runoff", "The water that drains off the land into rivers and the lake."],
    ["snow_water", "Mountain snow upstream is often the main water supply."],
    ["evapotranspiration", "Water lost back to the air from the land and the lake."],
    ["soil_moisture", "Dry soils soak up rain before any reaches the river."],
    ["t2m", "Warmer air evaporates more water from the lake's surface."],
  ],
};

const BY_INTEREST: Record<string, string[]> = {
  heat: ["t2m", "land_surface_temp", "airs_surface_temp"],
  water: ["precip", "soil_moisture", "root_zone_moisture", "runoff", "snow_water", "evapotranspiration", "humidity", "water_vapor"],
  plants: ["ndvi", "evapotranspiration", "root_zone_moisture", "soil_moisture"],
  air: ["tropospheric_ozone", "co2", "water_vapor", "humidity", "sea_level_pressure"],
};

const GENERIC: Record<string, string> = {
  t2m: "The most direct sign of warming.",
  land_surface_temp: "How hot the ground itself gets.",
  airs_surface_temp: "Temperature measured from space, independent of models.",
  precip: "Rain and snow: the source of all fresh water here.",
  soil_moisture: "Shows drought directly.",
  root_zone_moisture: "Deeper water that plants rely on; changes slowly.",
  runoff: "Water that drains into rivers.",
  snow_water: "Water stored as snow.",
  evapotranspiration: "Water returned to the air by plants and soil.",
  humidity: "How much water is in the air we breathe.",
  water_vapor: "All the water vapour above this place; a greenhouse gas.",
  ndvi: "How green the plants are.",
  tropospheric_ozone: "Ground-level ozone pollution.",
  co2: "The main greenhouse gas (rising worldwide).",
  sea_level_pressure: "Weather-pattern changes.",
};

export interface Suggestion {
  key: string;
  why: string;
}

/** Variables to try for these answers, best first (at most `limit`). */
export function suggest(place: string | null, interest: string | null, limit = 4): Suggestion[] {
  const wanted = interest && interest !== "any" ? new Set(BY_INTEREST[interest]) : null;
  if (place) {
    const list = BY_PLACE[place] ?? [];
    const matched = wanted ? list.filter(([k]) => wanted.has(k)) : list;
    // Interest that doesn't suit this place (e.g. "plants" in the ocean): fall back to the place.
    return (matched.length ? matched : list).slice(0, limit).map(([key, why]) => ({ key, why }));
  }
  if (wanted) return [...wanted].slice(0, limit).map((key) => ({ key, why: GENERIC[key] ?? "" }));
  return [];
}

export const placeLabel = (key: string | null) => PLACES.find((p) => p.key === key)?.label.toLowerCase() ?? "";
