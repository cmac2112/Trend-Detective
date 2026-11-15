# Trend Detective

## Summary

Trend Detective lets anyone draw a region on a map and find out what is really changing there, where, how fast, and why. Not sure where to start? Answer two quick questions, or scan all 15 variables (from GPM IMERG, MERRA-2, GLDAS, MODIS, AIRS, OMI/MLS and OCO-2) at once to see them ranked by how clearly they're changing. Each variable gets a monthly series with a trend line. A trend map colors every grid cell by its own trend, so opposite trends inside one region stay visible. The app never eyeballs trends. It removes the seasonal cycle and calls a trend significant only when an autocorrelation-adjusted t-test and a Mann-Kendall test agree. It corrects for lucky results whenever it tests many things at once, and for a trend that isn't significant yet, it estimates how many more years of data would settle it. To explain a trend, it tests other NASA variables as drivers, and Claude writes a cautious, plain-language explanation. A React map calls a FastAPI service built on my Python library, which streams only the pixels inside your shape from NASA's cloud. A guided demo and three offline example regions make it easy to start. Built solo in 36 hours. In the Amazon, vegetation fell significantly in 1,139 grid cells and rose in 278: a pattern one regional average would hide.

## Project Details

### What it does and how it works

Trend Detective lets anyone draw a shape on a map and find out what is really changing there, where, how fast, and what might be driving it.

NASA holds decades of satellite and model data on rainfall, temperature, vegetation, soil moisture, ozone and carbon dioxide. Asking a simple question of it, like "is my watershed getting drier?", normally means finding the right product, downloading gigabytes of global files, cutting out a region and running statistics by hand. Trend Detective turns that into six steps in a web browser:

1. **Draw.** Sketch up to five regions on an interactive map, labeled A to E. A region can be a farm, a lake basin, a rainforest or a patch of the Arctic Ocean.
2. **Discover.** Not sure what to look at? Answer two questions ("What kind of place is this?" and "What are you curious about?") and the app suggests the variables most likely to show a trend there, each with a one-line reason. Or **scan** all 15 variables at once: the app ranks them by significance and by how big the change is compared with that variable's normal ups and downs.
3. **Detect.** Choose a variable and a date range. The app builds a monthly time series by averaging every NASA pixel inside the shape, weighted by area. It reports the rate of change per decade, a confidence interval and a plain verdict: significant or not. If a trend isn't significant yet, it estimates how many more years of data would likely make it so, and if the dataset goes back further, it offers a one-click re-run on the longer record.
4. **Locate.** A trend map colors every grid cell inside the shape by its own trend, so you can see *where* the change is happening, including places where part of a region rises while another part falls.
5. **Compare.** Plot several regions on one chart over the same period. Is the Amazon warming as fast as the Arctic? Is one basin drying while its neighbor holds steady?
6. **Explain.** Ask why the trend is happening. The app tests the other NASA variables over the same region as possible drivers and ranks them by how much of the trend each one accounts for. Claude, an AI model, then writes a short, plain-language explanation that sticks to what the evidence supports.

The variables come from all six sources the challenge names (MODIS, OMI, AIRS, GPM, MERRA-2 and GLDAS), plus NASA's OCO-2 satellite for carbon dioxide. New users can click **Watch a guided demo**: the app runs a full investigation of the Brazilian Amazon live, one step at a time, explaining each result as it appears. Every result can be downloaded as CSV.

### Benefits

- **No expertise required.** Users don't need to know file formats, programming or which NASA product holds which variable. They don't even need to know which variable to pick: the questions and the scan point them to what's changing.
- **No downloads.** The app reads only the pixels inside the user's shape, straight from NASA's cloud. A question about one region costs megabytes, not gigabytes.
- **Answers you can trust.** Charts alone mislead: a single drought year or a seasonal cycle can look like a trend. Trend Detective removes the seasonal cycle, corrects for months that resemble their neighbors, and calls a trend significant only when two independent tests agree. When it tests many things at once (thousands of grid cells, 15 variables or several regions), it corrects for the lucky "trends" that would otherwise appear by chance. Every rate comes with a confidence interval.
- **Where, not just whether.** The trend map shows where inside a region things are changing, so a regional average can't hide opposite trends.
- **"Not significant yet" is still an answer.** The app estimates how many more years of data a weak trend would need, using a standard method from climate science (Weatherhead et al., 1998).
- **Context, not just a number.** Comparing regions shows whether a change is local or global. Worldwide trends such as carbon dioxide are labeled as such, so they don't crowd out what's special about a place. Cause analysis points users toward a likely explanation, then suggests what to look at next.
- **Fast and reliable.** Repeat questions are answered instantly from a cache. Three example regions (the Brazilian Amazon, Lake Mead and the Barents Sea) are stored locally, so the guided demo or a classroom lesson works even without internet.
- **Works with other tools.** Monthly data, trend maps, comparisons and scans download as CSV for Excel, Python, GIS software or hydrology tools such as CUAHSI's HydroShare.

### Intended impact

My goal is to make NASA's Earth record answer local questions for people who will never open a data file. The intended users include:

- Local planners checking whether rainfall or snowpack in their basin is truly declining
- Farmers and land managers watching soil moisture and vegetation
- Students and teachers learning how climate change shows up differently from place to place
- Journalists who want to check a claim before they publish it

The real results show why this matters:

- **Global vs. local.** Carbon dioxide rises about 25 ppm per decade in all three example regions, because it mixes around the whole planet. Rainfall and vegetation trends, by contrast, differ sharply from place to place.
- **The Amazon.** A scan of Rondônia, in the Brazilian Amazon, finds 11 of 14 variables changing significantly, all of them still significant after correcting for testing 14 at once. Two independent NASA sources both show significant drying (about 0.7 to 0.95 mm per day per decade). The trend map shows vegetation falling in 1,139 grid cells and rising in 278: patches of clearing among regrowth.
- **The value of a longer record.** At Lake Mead, ten years of warming isn't significant yet, and the app estimates about 29 more years would settle it. Over 24 years, it already is.

A tool that separates global signals from local ones, real trends from noise, and "not yet" from "no" helps people make better-informed decisions about water, land and health.

### Tools, languages and software

Trend Detective has three layers. Each can be used on its own.

- **Web client (TypeScript, React, Vite).** Leaflet draws the map and the per-cell trend map, Geoman handles drawing the shapes, and Recharts draws the time series and comparison charts.
- **API (Python, FastAPI).** A small web service the client calls. It runs long requests as background jobs with live progress, caches finished results, rate-limits each client, and can also be called directly with curl or Postman.
- **Analysis library (Python), which I call earthtrends.** It does all the science: finding data, reading it, averaging it over each shape, testing for trends in the region and in every grid cell, scanning all variables, and analyzing causes.

The main libraries are:

| Job | Tools |
|---|---|
| NASA data access | earthaccess, NASA Earthdata login, the CMR catalog search, OPeNDAP cloud streaming |
| Reading data | xarray, netCDF4, Zarr |
| Shapes and maps | shapely, Leaflet |
| Statistics | NumPy, pandas, SciPy, pymannkendall |
| Machine learning | scikit-learn (random forest) |
| AI explanation | Anthropic's Claude Haiku model, through its Python SDK |
| Testing | pytest (53 automated tests), Playwright for end-to-end checks |

The key design choice is cloud streaming. Instead of downloading whole global files, the library asks NASA's OPeNDAP service for just the rows and columns that cover the shape. The server never stores user data, so many people can use it without the disk filling up. Example regions are stored locally as compact Zarr files for speed and offline demos.

No special hardware was needed. I built and ran everything on a single Windows laptop.

### How it is creative

- **It answers "what", "where" and "why", not just "whether".**
  - **What:** a scan ranks every variable for a place.
  - **Where:** a trend map gives every grid cell its own trend.
  - **Why:** cause analysis tests other variables as drivers, using three methods that check each other: lagged correlation (does rainfall lead vegetation by a few months?), regression (what share of the trend does each driver account for?) and a random forest scored on held-out years. Each driver gets an evidence label from strong to weak.
- **Built for data detectives.** Two simple questions turn "I don't know where to start" into a list of leads, each with a reason a student can follow. A guided demo walks a first-time user through a real investigation, live.
- **AI with guardrails.** Claude never looks at raw data and never makes up a cause. It receives only the computed statistics plus a table of known physical mechanisms, and returns a structured explanation. If the AI is unavailable, the statistics still stand on their own.
- **Statistics that refuse to overclaim.**
  - The app shows "not significant" just as clearly as "significant", and says how many more years of data would likely change that.
  - Whenever it tests many things at once (grid cells, variables, regions, or the time lags in the cause analysis), it corrects for lucky results.
- **Seven instruments as one.** Data from satellites, weather models and land models normally sits in incompatible formats. Here they share one map, one chart and one set of tests, so a user can check a satellite against a model in a single click.
- **Shape-first.** Users ask about the place they care about, drawn freehand, not a fixed grid box or a country border.

### Factors I considered

I built Trend Detective alone in 36 hours, so every choice had to count.

- **Accuracy over flash.** I checked the pipeline against real data before building the interface:
  - Values streamed from the cloud matched downloaded files exactly.
  - GLDAS rainfall, evaporation and runoff balance within 2%, which confirmed the unit conversions.
  - AIRS satellite temperatures track MERRA-2 model temperatures closely, with correlations of 0.88 to 0.997.
  - CO2 averages about 407 ppm, matching global records for 2015 to 2022.
  - The per-cell trend test gives the same result as the regional test on a single cell.
  - On pure noise, the corrected trend map flags essentially no cells.
  - The years-to-detect estimate holds up in simulation: the app's own test detects planted trends 91 to 93% of the time at the predicted record length, against the 90% the formula targets.
- **Honest statistics.**
  - Monthly climate data violates the assumptions of a basic t-test: seasons repeat and neighboring months are alike. I corrected for both, and required two independent tests to agree before calling anything significant.
  - Testing many grid cells or variables at once produces false alarms by chance, so I applied a false-discovery-rate correction (Benjamini–Hochberg) wherever that happens.
- **Scale and cost.** Storing downloads for every user would fill a server quickly. Cloud streaming plus a result cache keeps storage near zero and makes repeat questions instant. Per-client rate limits and a cap on queued jobs protect the service.
- **Messy data.** Every NASA product has its own quirks: file formats, scaling rules, date labels, day and night passes, and records that end (OCO-2 stops in February 2022). I handled them all in one catalog, so adding a variable is a single entry, not new code. Scans automatically use each dataset's own record and skip variables that can't apply, such as soil moisture over the ocean or snow in the tropics.
- **Security.** NASA login details and the AI key stay on the server, are never sent to the browser, and are kept out of the code repository.
- **A demo that can't fail.** Three example regions are stored locally, so the guided demo and the presentation work even if the venue's Wi-Fi does not.
- **Clear limits.** The app says when evidence is weak, states that correlation is not proof of cause, and labels worldwide trends so users don't mistake them for local ones.
