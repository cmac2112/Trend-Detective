# Trend Detective: Presentation Plan

A living document: talking points, demo script, likely judge questions and the remaining
schedule. Early draft; expect to rewrite as the project settles. For how everything
works, see [ARCHITECTURE.md](../ARCHITECTURE.md).

---

## 1. The pitch

### One sentence

> **Trend Detective lets anyone draw a region on a map, pick a NASA dataset, and find out
> whether it's really changing, how fast, whether that's statistically significant, and
> what might be driving it.**

### 30-second version

> Earth is changing, but "is it really changing *here*?" is a hard question. NASA has
> decades of satellite and model data, but finding the right variable, cutting out your
> region and testing whether a change is real takes a scientist's toolkit.
>
> Trend Detective turns that into three clicks. Draw a region, pick a variable such as
> rainfall, temperature or vegetation, and I stream just that slice of NASA's data, remove
> the seasons, and run two independent significance tests. You get a plain-English verdict.
> Then ask "why is it changing?", and the app tests the likely drivers and explains the
> evidence, honestly, including when the evidence is weak.

### Who it's for

High-school and college students and curious members of the public: **data detectives**,
in the challenge's own words. Every variable has a plain-language definition, every result
has a plain-English verdict, and the statistics are there for anyone who wants to dig in.

---

## 2. How I meet the challenge

| Challenge objective | What Trend Detective does |
|---|---|
| Identify Earth-science variables that may show trends | 15 variables from **all six named sources (MODIS, OMI, AIRS, GPM, MERRA-2, GLDAS)** plus **OCO-2** carbon dioxide, grouped by topic, each with a student-friendly definition |
| Acquire data for a particular region | Draw any polygon or rectangle; I stream **only that region** from NASA Earthdata Cloud |
| Generate and visualize a time series | Monthly series, seasonal-removed anomalies, trend line, data table |
| Rate of change + significance (t-test, Mann-Kendall, confidence intervals) | **All three**: slope per decade with 95% CI, an autocorrelation-adjusted t-test **and** Mann-Kendall; "significant" only when both agree |
| Same process, opposite trends in different regions | **Compare up to 5 regions** side by side |
| Seasonal cycles hide trends | Seasonal cycle removed before every test |
| "A trend may need a longer record to become significant" | Change the years and watch significance change (Lake Mead demo) |
| Audience: students, data detectives | Plain-language verdicts and definitions, guided 3-step sidebar, one-click examples |
| Optional: AI to suggest causes | Cause analysis (correlation, regression, machine learning) + **Claude** explaining the evidence for students |
| Demonstration examples | Three built-in demo regions that work offline |

---

## 3. Talking points

### A. The problem is real and hard

- NASA's archive is huge, so even choosing a variable is a barrier.
- Most trends are **regional**, and the same variable can go up in one place and down in
  another.
- Raw monthly data is dominated by the seasons; a real trend hides inside it.
- "It looks like it's going up" isn't science. You need a significance test, and the
  standard one is over-confident on climate data (explained under B).

### B. I took the statistics seriously

- **Seasonal cycle removed** before any test, so summer heat isn't mistaken for warming.
- **Two independent tests must agree:** a regression t-test and Mann-Kendall. One assumes
  a straight line with bell-curve noise; the other assumes neither.
- **Autocorrelation correction.** This month resembles last month, so 288 months aren't
  288 independent data points. Without the correction, the Barents Sea p-value would be
  0.0000007; corrected, it's 0.005. Still significant, but honest.
- I say **"not significant"** when it isn't, and explain that a longer record might change that.

### C. Smart about data: stream, don't store

- I never download whole files. NASA's cloud cuts out **just the polygon's grid cells**
  for each month: about 10 MB instead of 17 GB for 24 years of temperature.
- **Nothing is written to disk** per user, so the server can't fill up however many people
  use it.
- Repeat requests come from a **cache**: 40 seconds → 0.3 seconds.
- The demo regions are stored locally (33 MB), so **the presentation works offline**.

### D. Compare regions: the challenge's "opposite trends" point

- Up to 5 regions, each with its own colour, on the same charts and table.
- Example: Arctic, desert and rainforest all warming significantly, at different rates.

### E. "Why is it changing?" Honest cause analysis

- **Statistics first, AI second.** I compute correlations, a regression and a random
  forest; Claude explains **those numbers**. It doesn't invent its own.
- **Direction matters.** Correlation doesn't show cause, so I encode known physics (rain
  drives soil moisture, not the reverse).
- **The model grades itself.** If the machine-learning model can't predict unseen years,
  I say its scores are unreliable instead of hiding it.
- **Data vs outside knowledge** are labeled separately: "shown by the data" vs "outside
  knowledge, e.g. deforestation".

### F. Carbon dioxide: the global trend behind the local ones

- OCO-2 CO₂ rises about **+25 ppm per decade in every region**: Arctic, desert and rainforest
  alike. It mixes around the planet within about a year, so a regional map can't point to
  local causes.
- Its **seasonal swing** differs, though: about 10 ppm over the Arctic, 2 ppm in the tropics.
  That's the Northern Hemisphere's plants breathing in each summer.
- This contrasts nicely with rain or vegetation, which change very differently from place
  to place, so compare mode shows both kinds of trend.

### G. Built to be trusted

- 37 automated tests with synthetic data where the true answer is known.
- Cloud-streamed values verified identical to NASA's full files.
- Units checked with physics: Rondônia's water budget (rain − evaporation = runoff)
  closes at 1.02.
- Key findings cross-checked across independent sources (satellite vs model rainfall).

---

## 4. Demo script (target: 3 minutes)

> Before presenting: run the **Pre-demo checklist** (section 7). Use the built-in examples:
> they load instantly and work offline.

| # | Time | Do | Say |
|---|---|---|---|
| 1 | 0:00 | Open the app. Point at the map and the 3-step sidebar. | "Draw a region, pick a variable, pick years." |
| 2 | 0:15 | **+ Barents Sea** → Air temperature → **Analyze trend** | "The Arctic north of Norway." |
| 3 | 0:30 | Point at the verdict and the trend line. | "**+0.77 °C per decade** since 2001, about 1.8 °C in 24 years, significant on both tests. The top chart is raw data, dominated by seasons; the bottom has the seasons removed, and that's where the trend appears." |
| 4 | 0:55 | **+ Lake Mead**, **+ Rondônia** → **Compare 3 regions** | "Same question, three very different places." |
| 5 | 1:10 | Table and chart | "All three are warming significantly: rainforest fastest (+0.81), Arctic (+0.77), desert slower (+0.38)." |
| 6 | 1:30 | Remove Barents and Lake Mead → Rondônia → Analyze → **Investigate causes** | "Now the detective part: *why* is Rondônia warming?" |
| 7 | 1:50 | Evidence table | "The strongest links are **drying soil** and **declining vegetation**: MODIS shows the land getting less green. Dry, bare ground can't cool itself by evaporating water." |
| 8 | 2:15 | AI card | "Claude turns that evidence into plain language, and separates what the data shows from outside knowledge like deforestation." |
| 9 | 2:35 | (Optional) Lake Mead with years 2015–2024 | "Over 10 years the desert warming *isn't* significant; over 24 years it is. Sometimes a trend just needs a longer record, exactly as the challenge says." |
| 10 | 2:50 | Close | "Any region, 15 variables from seven NASA instruments and models, honest statistics: become a data detective." |

**Backup plan:** if the network fails, everything above still works (local data + cache),
except the AI card, which shows the evidence with a short note instead.

---

## 5. Numbers worth quoting (all from real NASA data)

| Fact | Value | Notes |
|---|---|---|
| Barents Sea air temperature, 2001–2024 | **+0.77 °C/decade** (95% CI +0.24 to +1.30), p = 0.005 | One of the fastest-warming places on Earth |
| Rondônia air temperature | **+0.81 °C/decade**, p < 0.001 | |
| Lake Mead air temperature | **+0.38 °C/decade** 2001–2024 (significant); not significant over 2015–2024 (p = 0.67) | The "longer record" lesson |
| Rondônia vegetation (MODIS NDVI) | Declining significantly | Consistent with deforestation and drying |
| Rondônia warming ↔ soil moisture | r = −0.67 | Strongest driver |
| Rondônia warming ↔ vegetation | r = −0.53 | Second-strongest driver |
| Data moved for 24 years of temperature | ~10 MB instead of ~17 GB | Cloud subsetting |
| Repeat analysis | 40 s → 0.3 s | Cache |
| CO₂ (OCO-2), 2015–2022 | **+25 ppm/decade** in all three demo regions; seasonal swing 10 ppm (Arctic) vs 2 ppm (Amazon) | Record ends Feb 2022 |

⚠ **Handle with care:** Rondônia's rainfall decline is significant in **both** satellite
(−0.95 mm/day per decade) and model (−0.67) data, but the record ends on the extreme
2023–24 Amazon drought, which steepens the line. Say "both independent sources show
significant drying" rather than quoting a percentage. It's also a good point about how
endpoints affect trends, if a judge asks.

---

## 6. Likely judge questions

| Question | Answer |
|---|---|
| *How do you know a trend is real and not noise?* | Seasonal removal, then two independent tests that must both agree, with the t-test corrected for autocorrelation. I show the 95% range too. |
| *Isn't correlation not causation?* | Exactly, and the app says so. I encode physical mechanisms and their direction, label evidence strength, separate data from outside knowledge, and list unmeasured factors. |
| *Why trust the AI?* | It only explains numbers I computed, through a fixed output format; it never produces the statistics. Without it, the evidence still stands on its own. |
| *What about non-linear trends?* | Out of the challenge's scope by design; I fit linear trends and Mann-Kendall (which doesn't need linearity). Non-linear methods are a natural next step. |
| *How does it scale to many users?* | No per-user storage: I stream only the region from NASA's cloud and cache results in memory. Per-IP rate limits and a cap on queued jobs stop abuse; in production, host next to NASA's cloud. |
| *Why these datasets?* | They're all six named in the challenge, covering water, temperature, vegetation, atmosphere and air quality. Each is monthly, gridded and about 20+ years long. |
| *Do satellite and model data agree?* | On the month-to-month ups and downs, very closely (AIRS vs MERRA-2 temperature: r = 0.88–0.997). On the **size** of trends, not always: Rondônia warms +0.36 °C/decade in AIRS vs +0.86 in MERRA-2. Showing that honestly is part of being a data detective; the app lets you compare both. |
| *Why monthly data?* | The challenge recommends daily or monthly, and monthly gives 288 points over 24 years: enough for robust tests, fast to stream. |
| *Reanalysis vs satellite?* | Satellites (MODIS, GPM) measure directly; reanalysis and land models (MERRA-2, GLDAS) fill gaps consistently. I cross-check where possible (e.g. rainfall). |
| *What would you add next?* | Sea ice for the Arctic story, aerosols and NO₂ for cities, groundwater (GRACE), terrain and land-cover context, guided tours. |

---

## 7. Pre-demo checklist

- [ ] Start the API: `cd TrendApi` → activate `.venv` → `uvicorn app.main:app --reload --reload-dir app --reload-dir ../PythonPoc/earthtrends`
- [ ] Start the client: `cd client` → `npm run dev` → open http://localhost:5173 (must be port 5173)
- [ ] `http://127.0.0.1:8000/health` shows `cloud_enabled: true` and `ai_enabled: true`
- [ ] Run the full demo once beforehand, so every step is cached and instant
- [ ] Optional: `POST /cache/clear` (with the `X-Admin-Token` header, or from the server itself) if you *want* to show a live NASA stream (~30 s)
- [ ] Anthropic spend limit set in the Claude Console; API key **not** visible on screen
- [ ] Browser zoom and window size set so the map and results fit the projector

---

## 8. Schedule (reworked)

Feature work is largely done; the priority now is **stability, polish and the story**.

### Must-do (before submission)
1. **Commit and push** everything (a lot is uncommitted right now).
2. **Real Claude test** once the API key is in: check explanation quality on Rondônia and Barents.
3. **Root `README.md`**: what it is, a screenshot, quick start, links to these docs.
4. **Full demo rehearsal** with the script above; time it.
5. **Submission assets**: check the current Space Apps rules for format (demo video/slides
   length), required links, and any disclosure about AI tools and data sources.
6. **Screenshots / GIF** of the three demo moments: single trend, comparison, causes.

### Should-do (if time allows)
7. A guided "Start here" tour for first-time users (the challenge suggests demonstration examples users can watch).
8. A Colorado River headwaters example region (a better snowpack and runoff story than Lake Mead).
9. Sea ice (NSIDC) to explain the Barents Sea warming.

### Nice-to-have
10. MODIS terrain or land-cover context (from `todo.md`).
11. Cause analysis per region in comparison mode.
12. Aerosols / NO₂ for city examples.

### Feature freeze
Pick a time, about **6 hours before the deadline**: after it, only fixes, docs and rehearsal.

---

## 9. Open questions to settle

- Final project name and tagline (current: **Trend Detective**: "become a data detective").
- Who presents, and which demo regions go first?
- Live demo or recorded video as the primary format, with the other as backup?
- Do I show the live NASA stream (impressive, but ~30 s and needs internet) or keep
  everything cached?
