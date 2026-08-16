# Issuer Holdings Endpoints — Survey Notes

**Status:** in progress. Recorded so the survey is not repeated from scratch.

Goal: attribute the unattributed SPY FLEX legs found in OCC open interest
(`2026-09-30 765.66 C`, `597.42 P`, `2026-10-30 579.76 P`, `2026-11-30 580.90 P`,
`2026-12-31 765.86 C`, `2027-05-21 865.49 C`) to a named programme. The month-end
expiries and the deep-OTM put strikes are consistent with a buffer or collar
structure rather than a covered-call overlay.

## Confirmed

| Issuer | Pattern | Notes |
|---|---|---|
| YieldMax / Tidal | `yieldmaxetfs.com/wp-content/uploads/funds/{TICKER}/TidalFG_Holdings_{TICKER}.csv` | Registered. Latest file only, no history. Contains option legs with signed contract counts. |
| Global X | `assets.globalxetfs.com/funds/holdings/{ticker}_full-holdings_{YYYYMMDD}.csv` | **Dated URLs resolve for past dates** — verified 2026-08-13 and a second fund. This is the only issuer found so far offering retrievable history rather than a latest-only file. |

The Global X dated pattern matters beyond Global X: it means part of the panel can be
back-filled rather than only accumulated forward. Worth testing how far back it goes
before assuming it is limited.

Caveat: the QYLD file lists equity holdings and a written index call; the header rows
(fund name, as-of date) precede the real header, so it needs its own parser rather
than the Tidal one.

## Not yet resolved

| Issuer | Obstacle |
|---|---|
| Innovator | Fund pages render holdings via JavaScript; no CSV link in the served HTML. |
| First Trust / FT Vest | Holdings page returned no matching link from the served HTML. |
| Neos | Publishes quarterly PDF portfolio holdings, not a daily machine-readable file. |
| Roundhill | No CSV link in the served HTML. |

None of these are necessarily dead. Each likely has a JSON endpoint behind the page,
which is worth locating before falling back to N-PORT.

## Fallback

SEC N-PORT covers every registered fund uniformly and includes strike, expiry, right
and counterparty. It is quarterly-public with a roughly 60-day lag, so it cannot
attribute a currently-open FLEX leg in real time, but it can identify *which issuers*
hold SPY FLEX at buffer-like strikes, which is enough to prioritise the endpoint hunt.
