# ReinigungsRadar NRW

Streamlit dashboard for NRW company discovery, provider directories, public procurement notices and potential B2B opportunity signals.

## Job & Project Radar

The optional public-web search adapter uses the Tavily Search API. Set `TAVILY_API_KEY` as a protected environment secret in Render to enable automated indexed-web search.

The Radar:
- searches public indexed pages for cleaning, security, facility-management and construction-related opportunity signals;
- deduplicates URLs and ranks results by topic, location and intent phrases;
- shows source URLs, snippets, provider publication dates (when supplied) and the search timestamp;
- labels results as unverified signals, not confirmed buying intent;
- does not automatically contact businesses or write to Notion.

## Restricted platforms

LinkedIn, Facebook, MyHammer, Indeed, StepStone and XING are available as manual portal shortcuts only. This app does not scrape these platforms, automate logged-in accounts, bypass access controls or collect private group/profile data. Integrations require an explicitly authorized API or partner arrangement.

## Configuration

See `.env.example`. The existing Notion and app-password variables remain unchanged. `TAVILY_API_KEY` is optional and is only needed for the new public-web search.

## Company discovery (free open data)

The city search combines two independent open-data sources:

- **Overture Maps Places** is the primary global place dataset. The official overturemaps Python client reads only files intersecting the requested city's bounding box from Overture's public cloud dataset. The release is resolved from the STAC catalog at query time.
- **OpenStreetMap / Overpass** supplements Overture with local tagged business and facility records. Photon is used as a fallback when Overpass cannot be reached and to resolve the city bounding box for Overture.
- Results are merged by company name and location, keeping separate branches with different addresses. The dashboard reports the number of records returned by each source before merging.
- No Google Maps key, paid Places API, or bulk local download is required. Overture includes contributions from multiple providers, including Foursquare and AllThePlaces. A separate Foursquare OS Places import is not enabled because its current distribution requires a portal account and access token.
- Open data does not guarantee a complete or current directory. Phone, email and website fields may be missing; check the source before using a record. Overture Places is licensed under CDLA Permissive 2.0 and Apache 2.0. OpenStreetMap data is licensed under ODbL 1.0 and requires attribution.

The live search limit is configurable up to 1,000 rows per query in the dashboard. Streamlit caches results for 30 minutes to avoid repeating the same external reads.
