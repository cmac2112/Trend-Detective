"""Catalog of Earth science variables the tool can analyze.

Each entry says which NASA collection to download, which variable to pull out of
the files, how to convert it to friendly units, and a plain-language definition
for students.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Variable:
    key: str                 # short id used on the command line / API
    name: str                # display name
    definition: str          # plain-language explanation
    collection: str          # CMR short name of the NASA collection
    version: str             # collection version
    source_var: str          # variable name inside the file
    units: str               # units AFTER conversion
    scale: float = 1.0       # converted = raw * scale + offset
    offset: float = 0.0
    group: str | None = None # HDF5 group holding the variable (IMERG uses "Grid")
    related: tuple[str, ...] = field(default_factory=tuple)  # likely drivers / linked variables
    percent_meaningful: bool = True  # False for interval scales like °C, where "% of mean" is nonsense
    mb_per_month: float = 1.0  # measured size of one month's OPeNDAP subset (for download estimates)
    first_month: str = "2001-01"  # first month the collection has data
    last_month: str | None = None  # last month, for discontinued records (None = still updated)
    dim_order: tuple[str, str] = ("lat", "lon")  # spatial axis order in NASA's files
    cloud_seconds_per_month: float = 0.25  # measured streaming speed (varies 0.1-0.35 with NASA load)
    components: tuple[str, ...] = ()  # if set: value = sum of these file variables (source_var is ignored)
    # File-layout details, for datasets that don't follow the GES DISC netCDF conventions (e.g. MODIS HDF4):
    coord_group: str | None = None   # group holding lat/lon, if different from `group`
    lat_name: str = "lat"
    lon_name: str = "lon"
    has_time_dim: bool = True        # False when each file is one 2-D grid with no time axis
    manual_scaling: bool = False     # True: read raw values and apply `scale`/`fill_value` ourselves
    fill_value: float | None = None  # raw value meaning "no data" (with manual_scaling)
    global_fetch: bool = True        # False: too big to download whole files; cloud streaming only
    category: str = "Water"          # groups the variable list in the app
    combine: str = "sum"             # how `components` combine: "sum", or "mean" (ignores a missing one)
    coords_2d: bool = False          # lat/lon stored as 2-D grids (AIRS); the 1-D axes are taken from them
    single_file: bool = False        # whole record in ONE small file: download once, read regions locally

    def available_months(self, start: str, end: str) -> list:
        """The months in start..end (YYYY-MM) that this dataset actually covers."""
        import pandas as pd

        lo = max(start, self.first_month)
        hi = min(end, self.last_month) if self.last_month else end
        if lo > hi:
            return []
        return list(pd.date_range(f"{lo}-01", f"{hi}-01", freq="MS"))

    @property
    def source_vars(self) -> tuple[str, ...]:
        """The variable(s) read from NASA's files."""
        return self.components or (self.source_var,)


VARIABLES: dict[str, Variable] = {
    v.key: v
    for v in [
        Variable(
            key="precip",
            name="Precipitation",
            definition=(
                "How much rain and snow falls, averaged over the month and shown as "
                "millimeters of water per day. Measured by the GPM satellite constellation."
            ),
            collection="GPM_3IMERGM",
            version="07",
            source_var="precipitation",
            units="mm/day",
            scale=24.0,  # IMERG V07 monthly is mm/hr
            group="Grid",
            related=("t2m", "soil_moisture", "evapotranspiration"),
            mb_per_month=6.7,
            first_month="1998-01",
            dim_order=("lon", "lat"),  # IMERG stores precipitation as (time, lon, lat)
            cloud_seconds_per_month=0.35,  # finer 0.1 degree grid: ~38 s for 120 months
        ),
        Variable(
            key="t2m",
            category="Temperature",
            name="Air temperature (2 m)",
            definition=(
                "The temperature of the air about 2 meters above the ground, the height "
                "a weather station thermometer sits at. From the MERRA-2 reanalysis model."
            ),
            collection="M2TMNXSLV",
            version="5.12.4",
            source_var="T2M",
            units="°C",
            offset=-273.15,  # Kelvin -> Celsius
            percent_meaningful=False,
            related=("precip", "soil_moisture", "evapotranspiration", "ndvi"),
            mb_per_month=0.65,
            first_month="1980-01",
        ),
        Variable(
            key="soil_moisture",
            name="Soil moisture (top 10 cm)",
            definition=(
                "How much water is held in the top 10 cm of soil, in millimeters of water. "
                "Drier soil means drought stress for plants. From the GLDAS land model."
            ),
            collection="GLDAS_NOAH025_M",
            version="2.1",
            source_var="SoilMoi0_10cm_inst",
            units="mm",
            related=("precip", "t2m", "evapotranspiration"),
            mb_per_month=1.6,
            first_month="2000-01",
        ),
        Variable(
            key="evapotranspiration",
            name="Evapotranspiration",
            definition=(
                "Water moving from the land into the air: evaporation from soil and water "
                "plus water released by plants. Shown as millimeters per day. From GLDAS."
            ),
            collection="GLDAS_NOAH025_M",
            version="2.1",
            source_var="Evap_tavg",
            units="mm/day",
            scale=86400.0,  # kg m-2 s-1 -> mm/day
            related=("precip", "t2m", "soil_moisture", "ndvi"),
            mb_per_month=1.6,
            first_month="2000-01",
        ),
        # ---- more from the same GLDAS files (no extra data source)
        Variable(
            key="runoff",
            name="Runoff",
            definition=(
                "Water that flows off the land into streams and rivers instead of soaking in or "
                "evaporating: surface runoff plus groundwater seeping into streams. Shown as "
                "millimeters per day. The closest thing in this tool to streamflow. From GLDAS."
            ),
            collection="GLDAS_NOAH025_M",
            version="2.1",
            source_var="Qs_acc",
            components=("Qs_acc", "Qsb_acc"),  # storm surface runoff + baseflow-groundwater runoff
            units="mm/day",
            scale=8.0,  # monthly files store the average 3-hour accumulation (kg m-2 = mm) -> x8 = mm/day
            related=("precip", "snow_water", "soil_moisture", "t2m"),
            mb_per_month=1.6,
            first_month="2000-01",
        ),
        Variable(
            key="snow_water",
            name="Snow water equivalent",
            definition=(
                "How much water is stored in the snowpack: the depth of water you'd get if all the "
                "snow melted, in millimeters. Mountain snowpack feeds rivers in spring and summer. From GLDAS."
            ),
            collection="GLDAS_NOAH025_M",
            version="2.1",
            source_var="SWE_inst",
            units="mm",
            related=("t2m", "precip"),
            mb_per_month=1.6,
            first_month="2000-01",
        ),
        Variable(
            key="root_zone_moisture",
            name="Root-zone soil moisture",
            definition=(
                "Water held in the soil where plant roots reach (roughly the top 1-2 meters), in "
                "millimeters of water. Changes more slowly than the top 10 cm, so it shows long "
                "droughts. From GLDAS."
            ),
            collection="GLDAS_NOAH025_M",
            version="2.1",
            source_var="RootMoist_inst",
            units="mm",
            related=("precip", "evapotranspiration", "t2m"),
            mb_per_month=1.6,
            first_month="2000-01",
        ),
        Variable(
            key="land_surface_temp",
            category="Temperature",
            name="Land surface temperature",
            definition=(
                "How hot the ground surface itself is (its 'skin' temperature), which can be much "
                "hotter than the air on sunny days, especially over bare ground and cities. From GLDAS."
            ),
            collection="GLDAS_NOAH025_M",
            version="2.1",
            source_var="AvgSurfT_inst",
            units="°C",
            offset=-273.15,  # Kelvin -> Celsius
            percent_meaningful=False,
            related=("soil_moisture", "evapotranspiration", "precip", "ndvi"),
            mb_per_month=1.6,
            first_month="2000-01",
        ),
        # ---- MODIS (satellite) vegetation, streamed from LP DAAC's cloud
        Variable(
            key="ndvi",
            category="Vegetation",
            name="Vegetation greenness (NDVI)",
            definition=(
                "How green and leafy the land is, measured by the MODIS satellite instrument from how "
                "plants reflect red and near-infrared light. Runs from about 0 (bare ground, water, "
                "snow) to 1 (dense, healthy forest). Falling NDVI can mean drought, fire or deforestation."
            ),
            collection="MOD13C2",
            version="061",
            source_var="CMG_0_05_Deg_Monthly_NDVI",
            units="NDVI",
            scale=0.0001,  # stored as integers x 10000
            group="MOD_Grid_monthly_CMG_VI/Data_Fields",
            coord_group="MOD_Grid_monthly_CMG_VI",
            lat_name="Latitude",
            lon_name="Longitude",
            has_time_dim=False,
            manual_scaling=True,  # MODIS scale_factor means "divide by", opposite to the usual convention
            fill_value=-3000,
            global_fetch=False,   # ~98 MB per global file; regions are streamed instead
            related=("precip", "t2m", "soil_moisture"),
            mb_per_month=0.15,
            first_month="2000-02",
            cloud_seconds_per_month=0.3,
        ),
        # ---- AIRS (Aqua satellite), streamed from GES DISC's cloud
        Variable(
            key="airs_surface_temp",
            name="Surface air temperature (AIRS satellite)",
            definition=(
                "Air temperature near the ground measured from space by the AIRS instrument on NASA's "
                "Aqua satellite, which reads the infrared light the atmosphere gives off. Averaged over "
                "its 1:30 pm and 1:30 am passes. A satellite check on the MERRA-2 model temperature."
            ),
            collection="AIRS3STM",
            version="7.0",
            source_var="SurfAirTemp_A",
            components=("ascending/Data_Fields/SurfAirTemp_A", "descending/Data_Fields/SurfAirTemp_D"),
            combine="mean",  # day and night passes; if one is missing, use the other
            units="°C",
            offset=-273.15,
            percent_meaningful=False,
            coord_group="location/Data_Fields",
            lat_name="Latitude",
            lon_name="Longitude",
            coords_2d=True,
            has_time_dim=False,
            global_fetch=False,  # ~200 MB per global file; regions are streamed instead
            related=("soil_moisture", "precip", "ndvi"),
            mb_per_month=0.05,
            first_month="2002-09",
            cloud_seconds_per_month=0.3,
            category="Temperature",
        ),
        Variable(
            key="water_vapor",
            name="Total water vapor (AIRS satellite)",
            definition=(
                "All the water vapor in a column of air from the ground to space, measured by the AIRS "
                "satellite instrument, in millimeters (the depth of water if it all rained out). Warmer "
                "air holds more water vapor, which is itself a greenhouse gas."
            ),
            collection="AIRS3STM",
            version="7.0",
            source_var="TotH2OVap_A",
            components=("ascending/Data_Fields/TotH2OVap_A", "descending/Data_Fields/TotH2OVap_D"),
            combine="mean",
            units="mm",
            coord_group="location/Data_Fields",
            lat_name="Latitude",
            lon_name="Longitude",
            coords_2d=True,
            has_time_dim=False,
            global_fetch=False,
            related=("t2m", "evapotranspiration", "precip"),
            mb_per_month=0.05,
            first_month="2002-09",
            cloud_seconds_per_month=0.3,
            category="Atmosphere",
        ),
        # ---- OMI (Aura satellite): the whole record is one small file, read locally
        Variable(
            key="tropospheric_ozone",
            name="Lower-atmosphere ozone (OMI/MLS)",
            definition=(
                "Ozone in the lowest ~10-15 km of the atmosphere, in Dobson units, from the OMI and MLS "
                "instruments on NASA's Aura satellite. Unlike the protective ozone layer higher up, ozone "
                "down here is a pollutant and the main ingredient of smog, formed when sunlight cooks "
                "car and factory exhaust. Covers about 60°S to 60°N."
            ),
            collection="TrCO3_Monthly_OMIMLS",
            version="2",
            source_var="TropoO3",
            units="DU",
            lat_name="Latitude",
            lon_name="Longitude",
            single_file=True,
            global_fetch=False,
            related=("t2m", "humidity"),
            mb_per_month=0.0,
            first_month="2004-10",
            cloud_seconds_per_month=0.0,
            category="Air quality",
        ),
        # ---- OCO-2 carbon dioxide (GEOS assimilation), streamed from GES DISC's cloud
        Variable(
            key="co2",
            name="Carbon dioxide (OCO-2)",
            definition=(
                "The average amount of carbon dioxide in the air from the ground to the top of the "
                "atmosphere, in parts per million (ppm), from NASA's Orbiting Carbon Observatory-2 "
                "satellite blended into the GEOS model. CO2 is the main greenhouse gas driving global "
                "warming. It mixes around the whole planet within about a year, so its long-term rise "
                "looks similar everywhere; the yearly wiggle is plants breathing in and out."
            ),
            collection="OCO2_GEOS_L3CO2_MONTH",
            version="10r",
            source_var="XCO2",
            units="ppm",
            scale=1e6,  # mol CO2 / mol dry air -> parts per million
            related=("ndvi", "t2m"),
            mb_per_month=0.65,
            first_month="2015-01",
            last_month="2022-02",  # this product's record ends here
            cloud_seconds_per_month=0.25,
            category="Greenhouse gases",
        ),
        # ---- more from the same MERRA-2 file as air temperature
        Variable(
            key="humidity",
            category="Atmosphere",
            name="Humidity (2 m)",
            definition=(
                "How much water vapor is in the air near the ground, in grams of water per kilogram "
                "of air. Warmer air can hold more water vapor. From the MERRA-2 reanalysis model."
            ),
            collection="M2TMNXSLV",
            version="5.12.4",
            source_var="QV2M",
            units="g/kg",
            scale=1000.0,  # kg/kg -> g/kg
            related=("t2m", "evapotranspiration", "precip"),
            mb_per_month=0.65,
            first_month="1980-01",
        ),
        Variable(
            key="sea_level_pressure",
            category="Atmosphere",
            name="Sea-level air pressure",
            definition=(
                "The weight of the air above, adjusted to sea level, in hectopascals (1013 hPa is "
                "average). High pressure usually brings dry, calm weather; low pressure brings storms. "
                "From the MERRA-2 reanalysis model."
            ),
            collection="M2TMNXSLV",
            version="5.12.4",
            source_var="SLP",
            units="hPa",
            scale=0.01,  # Pa -> hPa
            percent_meaningful=False,
            related=("t2m", "precip"),
            mb_per_month=0.65,
            first_month="1980-01",
        ),
    ]
}


def get(key: str) -> Variable:
    try:
        return VARIABLES[key]
    except KeyError:
        raise SystemExit(f"Unknown variable '{key}'. Choose from: {', '.join(VARIABLES)}")
