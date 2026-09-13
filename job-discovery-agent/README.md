# Job Discovery & Verification Agent (n8n workflow)

An n8n workflow that:

1. Reads a resume/profile and extracts a ranked job-title taxonomy (AI Agent).
2. Builds Apify job-board search queries from that taxonomy x target locations.
3. Runs those queries against an Apify job-board actor.
4. Deduplicates and age-filters the results.
5. Verifies each listing is a **live posting on the company's real careers page** using Exa.
6. Enriches verified listings with AI company research.
7. Writes verified rows to Google Sheets (`Job Pipeline`), logs unverified listings to `Unverified`, and logs API failures to `Error Log`.

The workflow has already been built and published in your n8n instance as
**"Job Discovery & Verification Agent"**. `workflow.json` in this folder is an
importable snapshot of that build, kept here for version control / portability.

## Architecture

```
Manual Trigger
  -> Config (Set: actor id, locations, caps)
  -> Resume Text (Set: candidate profile)
  -> Extract Job Title Taxonomy (AI Agent, DeepSeek + structured output)
  -> Build Apify Queries (Code: taxonomy x locations, capped at 30)
  -> Clear Raw Listings Table (Data Table, fresh slate per run)
  -> Apify Query Loop (Split In Batches, size 1)
       -> Run Apify Actor (sync)          [HTTP, run-sync-get-dataset-items]
       -> Tag Raw Listings with Query Meta (Code)
       -> Insert Raw Listings              [Data Table: job_discovery_raw_listings]
       -> (loop)
     onDone:
       -> Get All Raw Listings             [Data Table, returnAll]
       -> Dedupe and Filter Listings        (Code: company+title key, postedWithinDays)
       -> Listings Loop (Split In Batches, size 1)
            -> Exa Verify Search            [HTTP -> api.exa.ai/search]
            -> Check Verified URL           (Code: domain + path heuristics)
            -> Verified? (IF)
                 true  -> Company Research Agent (AI Agent) -> Upsert Job Pipeline Row (Google Sheets, upsert on Verified URL)
                 false -> Log Unverified Listing (Google Sheets append)
```

Error handling: the two external HTTP calls (Apify, Exa) use
`onError: continueErrorOutput`, routing failures to a `Format ... Error` Set
node and then an append to the `Error Log` sheet tab. Each error branch then
reconnects into its loop's `Split In Batches` node (acting as `nextBatch`),
so a single bad request logs and moves on to the next query/listing instead
of silently stalling the rest of the run.

### Why "run-sync" instead of a manual poll loop

The original spec described POST run -> Wait -> poll status -> GET dataset as
separate steps. This build uses Apify's
`run-sync-get-dataset-items` endpoint instead, which runs the actor and
blocks (up to the `timeout` query param, set to 120s here) until it finishes,
then returns the dataset directly. This gives the same result with far fewer
moving parts and no risk of an infinite/undercounted poll loop. If you have
actors that reliably run longer than ~5 minutes, switch back to the
async run + poll pattern (POST `/runs`, `Wait`, GET `/actor-runs/{id}`, then
GET `/datasets/{id}/items`) inside the "Apify Query Loop".

### Why a Data Table for raw listings

n8n's `Split In Batches` loop body doesn't accumulate results across
iterations back into the "done" output. To dedupe across *all* Apify queries
in one run (not just within a single query), listings are staged in a
Data Table (`job_discovery_raw_listings`) during the query loop, then read
back in full once the loop finishes. This table is cleared at the start of
each run, so it only ever holds the current run's raw data.

## Setup

### 1. Credentials (n8n)

The workflow references these n8n credentials by name — create/confirm them
under **n8n > Credentials**:

| Node(s) | Credential type | Name used in this workflow |
|---|---|---|
| Run Apify Actor (sync) | Header Auth (`httpHeaderAuth`) | `Apify` |
| Exa Verify Search | Header Auth (`httpHeaderAuth`) | `Exa Search` |
| DeepSeek Model (Taxonomy), DeepSeek Model (Research) | DeepSeek API (`deepSeekApi`) | `DeepSeek account` |
| Upsert Job Pipeline Row, Log Unverified Listing, Log Apify/Exa Error to Sheet | Google Service Account (`googleApi`) | `Google Service Account account` |

Notes:
- **Apify** header credential should send `Authorization: Bearer <APIFY_TOKEN>`.
- **Exa Search** header credential should send `x-api-key: <EXA_API_KEY>`.
- Because these two are *generic* (Header Auth) credential types, n8n does not
  auto-attach them to the HTTP Request nodes on import/creation — open
  **Run Apify Actor (sync)** and **Exa Verify Search** in the editor and pick
  the credential manually if the field is empty.
- The Google Sheets nodes use a **Service Account**. Share your target
  spreadsheet with the service account's email as an Editor.
- Swap the DeepSeek model nodes for `@n8n/n8n-nodes-langchain.lmChatAnthropic`
  or `@n8n/n8n-nodes-langchain.lmChatOpenAi` if you'd rather use Claude/GPT —
  see `.env.example` for the relevant key names.

### 2. Google Sheet

Create one spreadsheet with three tabs (exact names matter — the workflow
looks them up by name):

- **Job Pipeline** — columns: `Date Found | Job Title | Company | Location | Tier | Verified URL | Company Summary | Industry | Size | HQ | Fit Score | Status | Notes`
- **Unverified** — columns: `Date Found | Job Title | Company | Location | Tier | Candidate URL | Reason`
- **Error Log** — columns: `Timestamp | Source | Query | Message`

Then, in the n8n editor, open **Upsert Job Pipeline Row**, **Log Unverified
Listing**, **Log Apify Error to Sheet**, and **Log Exa Error to Sheet**, and
pick your spreadsheet in the **Document** field (it is left blank/placeholder
in the build since spreadsheet IDs are account-specific).

### 3. Config node

Open the **Config** node to adjust, without touching any other node:

- `apifyActorId` — Apify actor to run (default: `curious_coder~linkedin-jobs-scraper`,
  a pay-per-result actor — see below for why).
- `apifyMaxResultsPerQuery` — results requested per query (default 50).
- `maxApifyQueries` — hard cap on total Apify queries per run (default 30).
- `postedWithinDays` — drop listings older than this (default 30).
- `exaNumResults` — Exa results to inspect per verification search (default 5).
- `locations` — array of locations to combine with each taxonomy title
  (default `["Hong Kong", "Singapore", "Remote", "Australia"]`).

### 4. Apify actor: `curious_coder~linkedin-jobs-scraper`

The build originally targeted `bebity~linkedin-jobs-scraper`, but that actor's
free trial had expired on this account ("You must rent a paid Actor..."),
and its rental model doesn't draw from Apify's free monthly platform credit.
`curious_coder/linkedin-jobs-scraper` is priced **pay-per-event** (~$0.001–
0.002 per result), so it runs entirely off Apify's $5/month free credit for
low-to-moderate volumes (roughly 2,500–5,000 results/month) with no separate
rental step. Verified live against a real query during setup (5 real Hong
Kong-based "Trade Commissioner" search results returned successfully).

Its input fields (confirmed from the actor's live input schema), wired into
**Run Apify Actor (sync)**'s `jsonBody`:

```json
{ "keywords": "<title>", "location": "<location>", "limitPerSource": <apifyMaxResultsPerQuery>, "scrapeCompany": false }
```

Its output fields (confirmed from a live run) are `title`, `companyName`,
`location`, `link`, `descriptionText`, `postedAt` — all already covered by
the fallback chains in **Tag Raw Listings with Query Meta**, so no code
changes were needed there.

If you swap to a different actor, update `apifyActorId` in Config, then:
- Update `jsonBody` on **Run Apify Actor (sync)** to that actor's real input
  field names (check the actor's page on the Apify Store, "Input" tab, or
  fetch `GET https://api.apify.com/v2/acts/{actorId}/builds/latest` with your
  Apify credential and read the `data.inputSchema` field).
- Add that actor's actual output field names to the fallback chains in
  **Tag Raw Listings with Query Meta** if none of the existing ones
  (`title`/`jobTitle`/`position`, `companyName`/`company`/`organization`,
  `jobUrl`/`url`/`link`, `description`/`descriptionText`,
  `postedAt`/`datePosted`/`postedDate`) match.

### 5. Resume / candidate profile

Edit the **Resume Text** Set node's `resumeText` field to update the
candidate profile fed into the taxonomy agent. The target job tiers
(Tier 1/2/3 definitions) are embedded directly in the **Extract Job Title
Taxonomy** node's prompt — see `prompts/taxonomy_prompt.txt` for the exact
text and how to edit it.

## Running it

1. Click **Execute Workflow** (Manual Trigger) in the n8n editor.
2. Watch the **Extract Job Title Taxonomy** node output — it should return
   `tier1_direct` / `tier2_adjacent` / `tier3_stretch` arrays with realistic
   alternate titles and search keywords.
3. The **Apify Query Loop** will run once per taxonomy-title x location
   combination (capped at `maxApifyQueries`). This is the slowest part of the
   run — each Apify call can take up to ~2 minutes.
4. Once all queries finish, the **Listings Loop** verifies each deduped
   listing via Exa and writes to your Google Sheet.
5. Check the `Job Pipeline`, `Unverified`, and `Error Log` tabs.

For production use, replace the Manual Trigger with a **Schedule Trigger**
(e.g. weekly) once you've validated a few manual runs.

## Guardrails already built in

- **Cost caps**: `maxApifyQueries` (30) and `apifyMaxResultsPerQuery` (50) in Config,
  and a pay-per-event actor that runs on Apify's free monthly credit at low volumes.
- **Loop resilience**: a failed Apify or Exa call is logged to `Error Log` and
  the batch loop continues to the next item, rather than the whole run silently
  stopping partway through.
- **Rate limiting**: `Split In Batches` (size 1) serializes Apify and Exa
  calls one at a time; Apify's own request batching/interval options are
  also available on the HTTP Request node if you need extra throttling.
- **Deduplication**: raw listings are deduped by `company + title` before
  verification, and `Upsert Job Pipeline Row` upserts on `Verified URL`, so
  re-running the workflow never creates duplicate rows in `Job Pipeline`.
- **Verification-first**: only listings with a `verifiedUrl` from Exa reach
  `Job Pipeline`; everything else goes to `Unverified` for manual review
  rather than being silently dropped.
- **Error handling**: Apify/Exa call failures are caught (`continueErrorOutput`)
  and logged to `Error Log` instead of failing the whole execution.
- **No direct LinkedIn scraping**: job search goes through the Apify actor
  only; the workflow never calls linkedin.com directly.

## Deliverables in this folder

- `workflow.json` — importable n8n workflow (Menu > Import from File in n8n).
- `README.md` — this file.
- `prompts/taxonomy_prompt.txt` — the taxonomy-extraction system/user prompts and schema.
- `prompts/company_research_prompt.txt` — the company-research system/user prompts and schema.
- `.env.example` — placeholder keys and where each one is used.
