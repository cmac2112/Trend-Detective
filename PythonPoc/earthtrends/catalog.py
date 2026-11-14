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
        ),
        Variable(
            key="t2m",
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
            related=("precip", "soil_moisture", "evapotranspiration"),
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
            related=("precip", "t2m", "soil_moisture"),
            mb_per_month=1.6,
            first_month="2000-01",
        ),
    ]
}


def get(key: str) -> Variable:
    try:
        return VARIABLES[key]
    except KeyError:
        raise SystemExit(f"Unknown variable '{key}'. Choose from: {', '.join(VARIABLES)}")
