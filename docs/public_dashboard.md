# Public dashboard preview

The public dashboard is a weather-only historical reporting snapshot generated
from the trusted weather export for `release_a74a4772ee3b0338a041`. Its static
publication boundary is [`site/`](../site/); screenshots and broader project
documentation remain outside that directory.

The verified deployment is the
[interactive dashboard](https://bemoremj.github.io/kenya-economic-data-platform/)
in the public
[BEMOREMJ/kenya-economic-data-platform](https://github.com/BEMOREMJ/kenya-economic-data-platform)
repository.

## Source policy and attribution

The public snapshot follows the reuse finding recorded in the
[source inventory](source_inventory.md#nasa-power-daily-weather): NASA Earth
science data are generally free and open, NASA should be acknowledged, and the
dataset/API provenance should be cited. No restriction appeared in the verified
NASA POWER API payload.

The applicable policy reference is the
[NASA Earthdata data-use policy](https://www.earthdata.nasa.gov/engage/open-data-services-software/data-use-policy).
The dashboard also links to the NASA POWER Daily API documentation and source
methodology. It identifies the values as gridded MERRA-2/GEOS-IT estimates at
representative points, not station observations or city-wide measurements.

## Regenerate and view locally

No network or cloud access is used by this command:

```powershell
$ReleaseId = "release_a74a4772ee3b0338a041"
uv run python -m kenya_economic_data render-public-dashboard `
  --report-dir "data\reports\$ReleaseId" `
  --output "site\index.html"
Start-Process "site\index.html"
```

The renderer opens only `weather_summary.csv` and
`weather_summary.metadata.json`. Plotly is embedded in `site/index.html`, so the
page needs no CDN, API call, credential or local service. September remains
null for Mombasa and Kisumu rather than being filled with zero.

## GitHub publication record

The repository was published from `main`. The first remote
[offline CI run](https://github.com/BEMOREMJ/kenya-economic-data-platform/actions/runs/37473137469)
passed without cloud credentials. The manual
[GitHub Pages run](https://github.com/BEMOREMJ/kenya-economic-data-platform/actions/runs/37474129917)
then deployed only `site/` successfully.

The checked-in workflow `.github/workflows/pages.yml` remains manual-only. It
uses the `github-pages` environment and only the permissions needed to read the
repository, attest the deployment identity and write Pages. It does not run
ingestion, access BigQuery or rebuild the pipeline.

Post-deployment verification confirmed the historical release identifier, both
Plotly charts, Nairobi September hover value `21.658`, coverage text and the
exact-value content. Mombasa and Kisumu September remain null. The page renders
without horizontal overflow at a 390-pixel mobile viewport as well as desktop
width. Because the publication workflow is manually dispatched, ordinary
documentation commits do not redeploy the unchanged `site/` directory.

This follows GitHub's documented custom-workflow pattern: configure Pages,
upload a Pages artifact from the chosen directory, and deploy that artifact.
