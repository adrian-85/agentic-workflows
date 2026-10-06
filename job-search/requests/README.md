# Captured requests (LOCAL ONLY — gitignored)

Ground-truth captures used to build adapters for sites whose data
endpoints are invisible from outside (widget APIs, JS shells, bot-gated
pages). Never commit: these contain session cookies and real posting
data. Committed test fixtures stay synthetic (scripts/fixtures/).

Per site, from DevTools -> Network with your filters applied
(remote + US, posted-today where offered), logged in where required:

    requests/<site name>/
      search.curl          "Copy as cURL (bash)" of the job-list request
      search-response.txt  that request's response body (Response tab)
      detail-response.txt  one job-detail response (two-step sites)

Once the adapter is live, the search.curl also seeds auth/<site name>/
curl.txt for curl-feed rotation when the site needs a session.
