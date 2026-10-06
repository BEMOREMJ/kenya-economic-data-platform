# Public dashboard preview

The public dashboard is a weather-only historical reporting snapshot generated
from the trusted weather export for `release_a74a4772ee3b0338a041`. Its static
publication boundary is [`site/`](../site/); screenshots and broader project
documentation remain outside that directory.

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

## Publish later with GitHub Pages

The checked-in workflow `.github/workflows/pages.yml` is manual-only. Merely
pushing it does not create a Pages deployment.

After this commit has been reviewed:

1. Push the reviewed commit to the repository's default branch.
2. On GitHub, open **Settings → Pages** and select **GitHub Actions** as the
   source. Do not select a branch directory: the workflow deliberately uploads
   only `site/`.
3. Open **Actions → Publish public dashboard to Pages → Run workflow**, select
   the reviewed default branch, and confirm the run.
4. Wait for the `github-pages` environment deployment to succeed, open the URL
   shown by the deployment, and verify the two charts, coverage and exact-value
   table at desktop and mobile widths.
5. Add that verified URL to the README in a later commit. Until then, no hosted
   dashboard URL is claimed.

This follows GitHub's documented custom-workflow pattern: configure Pages,
upload a Pages artifact from the chosen directory, and deploy that artifact.
