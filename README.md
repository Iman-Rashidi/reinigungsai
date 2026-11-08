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


## Email marketing (Listmonk)

The optional email-marketing tab connects to a separately hosted [Listmonk](https://listmonk.app/) instance. Listmonk is free and open source under AGPLv3; the software itself does not include a free SMTP sending service. You must configure an SMTP provider in Listmonk before any real email can be delivered. Hosting, backups, domains and SMTP delivery may have separate costs.

### Start a self-hosted Listmonk instance

A pinned stable Docker Compose example is in `deploy/listmonk/`:

1. Copy `deploy/listmonk/.env.example` to `deploy/listmonk/.env`.
2. Set strong, unique values for `LISTMONK_DB_PASSWORD`, `LISTMONK_ADMIN_USER` and `LISTMONK_ADMIN_PASSWORD`. Never commit the real `.env` file.
3. Run `docker compose --env-file .env up -d` from `deploy/listmonk/`.
4. Put the Listmonk web interface behind HTTPS before exposing it outside the host. The Compose port is bound to localhost by default.
5. In Listmonk, configure an SMTP server, create a restricted API user/token, and create an active list with **Double opt-in** enabled.
6. Grant the API user only the list, subscriber and campaign read/write permissions required for the intended lists. Avoid a super-admin API token.

The Compose file pins Listmonk `v6.2.0` (stable), with PostgreSQL 17 and persistent database/uploads volumes. Check the upstream release notes before upgrading.

### Connect the ReinigungsRadar app

Add these protected Render environment variables (or local environment variables for development):

- `LISTMONK_URL`: the HTTPS base URL reachable by the ReinigungsRadar service, without a trailing slash.
- `LISTMONK_API_USER`: the restricted Listmonk API username.
- `LISTMONK_API_TOKEN`: the API token for that user.

Never add real credentials to `.env.example`, source code, issues or commits. After configuration, use **E-Mail-Marketing → Listmonk-Verbindung testen und Listen laden**.

The integration intentionally:
- does not bulk-import companies or public email addresses from the Radar;
- only creates a subscriber when the operator records prior explicit consent and a reference to its evidence;
- only adds subscribers to an active Double-opt-in list and never pre-confirms a subscription;
- creates Markdown campaign drafts only; the dashboard has no send/schedule action;
- leaves final audience review and sending to a human operator inside Listmonk.

In Germany, email advertising generally requires prior express consent. The existing-customer exception in § 7(3) UWG is narrow and applies only when every statutory condition is met. This technical gate is not legal advice and does not replace documenting the lawful basis, privacy notice, withdrawal process, sender identity and unsubscribe handling.

### Integration tests

Run `python -m unittest discover -s tests -v`. Listmonk API tests use mocked HTTP responses and do not send real emails. A live connection test requires a separately deployed HTTPS Listmonk instance and valid API credentials.
