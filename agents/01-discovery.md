# Discovery Agent

Finds job postings. Does not score or tailor anything — hand results to
`02-matching.md` for that. Read `profile/personal-info.md` first for
location/role defaults and dealbreakers (e.g. sponsorship requirement)
before searching, so obvious mismatches don't waste a search cycle.

## Sources to cover

Cover the highest-signal sources first so the search produces usable
matches quickly before widening:

1. **Direct company / ATS boards** — Greenhouse, Lever, Ashby, Workday, and
   SmartRecruiters. Prefer the canonical posting URL over aggregator copies.
2. **LinkedIn Jobs** — formal job-postings search. Use it for volume and
   freshness, but verify each promising listing at the original company/ATS
   URL before handing it to Matching.
3. **LinkedIn feed** — organic posts from people hiring for their team
   ("we're hiring," "my team is growing"). Needs a live, logged-in browser
   session (Playwright MCP) to read.
4. **Google X-ray search across ATS platforms** — postings that never made
   it to LinkedIn, found via site-scoped search. Template:
   `"{role}" site:{ats-domain} {location}`, filtered by recency where the
   search tool supports it.
   Common ATS domains to check: `boards.greenhouse.io`, `jobs.lever.co`,
   `jobs.ashbyhq.com`, `myworkdayjobs.com`, `smartrecruiters.com`.
5. **Glassdoor**
6. **Non-standard postings** — some companies post via a plain Notion page
   or a Google Form instead of a real ATS. Flag these for doc-handoff mode
   later (see `04-application.md`) rather than assuming Playwright can
   automate them.
7. **Startup / funding-stage sources** — Wellfound, Y Combinator's Work at
   a Startup, VC portfolio job boards (a16z and similar). A recent funding
   announcement (Series A/B news) is also worth treating as a signal to
   check whether that company is hiring for the role.

## Search filter contract
Accept both natural language and structured filters:
```
job_title:"Product Designer" jobboard:"Workday,Greenhouse"
company_page:true not_on_linkedin:true
```
- `job_title` is the title family to search. Search close employer variants
  such as Product Designer, UX/Product Designer, and Product Designer II only
  when they remain inside the requested seniority/function.
- `jobboard` is a comma-separated allowlist. Normalize common spelling and
  capitalization variants such as `ICIMS` -> `iCIMS`. Empty or omitted means
  search every supported direct ATS/company source.
- `company_page:true` prioritizes employer career pages and follows their
  canonical ATS links.
- `not_on_linkedin:true` is an exclusion that must be proven using the
  source-exclusion procedure below; it is not a preference.

For direct-source searches, use both title-first and ATS-first queries. Example:
`"Product Designer" site:myworkdayjobs.com` plus company career pages found
from current hiring signals. Do not add a result from a search snippet alone.
Use `scripts/job_command.py` to normalize board names and generate the initial
site-scoped query set instead of rebuilding those strings in an LLM.

## Freshness and dedup
- Prefer postings from the last 24-48 hours where the source allows
  filtering by recency — early applications tend to rank better.
- The same posting often appears via more than one source (LinkedIn +
  Greenhouse X-ray, for instance). Dedup by company + title + location
  before handing results forward.
- Exclude postings that are clearly closed, archived, repost spam,
  staffing-agency duplicates, unpaid/commission-only, or outside the
  profile's stated location/work-authorization constraints.
- If the same role appears in multiple cities, keep one row when it is the
  same requisition and list all relevant locations. Keep separate rows only
  when the requisition IDs or job descriptions differ.

## Live and source verification

Before handing a role to Matching, verify it from the canonical company/ATS
page. Confirm that the title and JD are present and that an apply path exists.
Use the ATS's public posting/board API when available, then reconcile it with
the rendered page for application-only fields. A cached search result is a
lead, not proof that a role is active.

A direct-source result is eligible only when the canonical page confirms:
- employer, title, location, full JD, and a usable apply path;
- active/available state rather than closed, expired, archived, or 404;
- requisition ID when the platform exposes one; and
- the verification method and timestamp.

Record the canonical URL separately from discovery URLs. Add verified roles
to the result set and local discovery/application index. Keep unverifiable
snippets out of Matching.

When the request says `not on LinkedIn`:
1. Search LinkedIn Jobs for the exact company and title.
2. Run an exact web/X-ray check such as
   `site:linkedin.com/jobs/view "{company}" "{title}"`.
3. Compare location and requisition ID when available so similarly named roles
   are not treated as duplicates.
4. Exclude a role when an equivalent LinkedIn Jobs posting is found. Otherwise
   record `linkedin_status: no_equivalent_listing_found`, the check date, and
   the queries/sources used. Do not claim absolute absence beyond the checks.

User-facing wording must be precise: `LinkedIn check: no equivalent listing
found as of {date}`. Never shorten this to `not on LinkedIn`, which claims more
than the checks establish.

## Feasibility signals to capture
Discovery should not score the job, but it should capture signals that
affect whether Application can succeed:
- Apply path: direct ATS, LinkedIn Easy Apply, company portal account,
  email-to-apply, Google Form, Notion/other handoff, or unknown.
- Account wall: yes/no/unknown.
- Work mode: remote, hybrid, on-site, and required office days if stated.
- Compensation: range if posted, otherwise "not listed."
- Sponsorship/work authorization language.
- Posted date and whether the page appears active.
- Any unusual form notes visible before apply, such as portfolio upload
  requirements or long written-response sections.

## What to pull per posting
Don't stop at the title/snippet. Fetch the **full job description text** —
matching and tailoring both need the real requirements, not a summary. If a
source only exposes a summary, follow the original posting link and extract
the real JD there. If the full JD cannot be reached, mark the result
`incomplete_jd: true` and keep it out of auto-apply until reviewed.

## Output format
A list (or table, if presenting directly to the user) with: role, company,
source, canonical link, location, work mode, posted date if available,
compensation if available, apply path, account wall, feasibility notes, and
the full JD text attached for each — ready for Matching to score. Also include
`active_verified_at`, `active_verification_method`, and `linkedin_status` when
the request contains a LinkedIn exclusion.

Also include `canonical_url`, `requisition_id` when available, and
`linkedin_checked_at`. These keys feed deterministic dedupe before later runs.
