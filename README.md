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
