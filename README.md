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

See `.env.example`. The staging dashboard is accessed only through the central SteuerPilot Pro SSO integration; standalone trial-password access is disabled.

Set `STEUERPILOT_RADAR_SSO_SECRET` in both the SteuerPilot Pro Staging and ReinigungsRadar Staging Render services. Use the exact same randomly generated value with at least 32 characters in both services. The application temporarily accepts the legacy misspelled key `STEUEERPILOT_RADAR_SSO_SECRET` for backwards compatibility, but new configuration should use the correctly spelled name. Never commit the secret or print it in logs.

`APP_PASSWORD` is no longer used for staging authentication. `TAVILY_API_KEY` is optional and is only needed for the public-web search.
