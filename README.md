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


## Opportunity Engine v2

The multi-source engine stores procurement opportunities, source observations, source-run health and field-level change history in SQLite.

### Sources

- **Bekanntmachungsservice (BKMS) Open Data**: official daily OCDS ZIP exports. The engine reads completed publication days (yesterday and earlier), filters service categories locally, and retains uncertain locations as reviewable candidates. Source data is published under CC0.
- **TED Search API**: public active-notice search with iteration-token pagination. NRW is constrained through the existing NUTS-1 query.
- **Tavily**: optional public-index discovery using TAVILY_API_KEY; these are leads/signals, not confirmed orders.
- **Auftragsbank, MyHammer, LinkedIn and Facebook** remain manual-only until a documented and authorized API/partner integration exists.

### Run manually

```bash
python -m src.opportunity_engine.cli --city NRW --category Reinigung --days-back 7
```

Use --no-tavily to run only the official sources. The Streamlit tab Opportunity Engine exposes the same workflow, source health, cross-source deduplication, changes and CSV export.

### Persistence on Render

The default local database path is data/opportunities.sqlite3. Render's free web-service filesystem is ephemeral, so this default path is **not durable across restarts/deploys**. For durable production history, attach a Render Persistent Disk (or use an external managed database) and set:

```text
OPPORTUNITY_DB_PATH=/var/data/reinigungsradar-opportunities.sqlite3
```

No paid infrastructure is provisioned automatically by this code. The dashboard displays a warning when it detects a Render deployment without a mounted persistent path.

### Data quality and operating boundaries

- A procurement notice, a private service-request signal and an employment advertisement are classified separately. Job ads are hidden from the default opportunity list.
- Cross-source matches are merged only using a conservative title/buyer/location identity key; each source observation remains linked to the canonical opportunity.
- Deadline, value, buyer and document links are shown only when present in the source. Missing fields are not invented.
- A changed deadline/title/value/location is kept in the change history.
- Each source has its own status and errors; one provider failure does not stop the others.
- The engine does not log in to restricted platforms, bypass access controls, contact companies or submit bids.
- Always verify the original notice and tender documents before acting on an opportunity.
