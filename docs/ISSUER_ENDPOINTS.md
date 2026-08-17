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
back-filled rather than only accumulated forward.

**History depth, probed 2026-08-17.** An initial pass suggested a boundary around
October 2024. That was wrong: the 2024-09-02 miss was Labor Day, a market holiday, and
carries no information. Re-probing puts the true boundary in **early August 2024**:

| date | result |
|---|---|
| 2024-08-05 | 404 |
| 2024-08-12 onward (08-15, 08-16, 08-19, 08-26, 09-03 … 2026-06) | 200 |

So roughly **24 months of daily history** are retrievable.

### This is a rolling retention window, and the early files are expiring

Today is 2026-08-17. Exactly two years earlier is 2024-08-17. The boundary sits within
a few days of that, at roughly 735–741 days back. A fixed adoption date landing inside
a one-week window of exactly-two-years-ago would be a large coincidence; a **rolling
~2-year retention** explains it directly.

Consequence: **every day of delay permanently loses a day off the back of the panel.**
Back-filling the ~500 available trading days is urgent, not optional, and should be
done before any further collector work. The cost is one bulk download.

This is index-level covered call only (QYLD, XYLD, RYLD), so it does not back-fill the
single-name programmes the study leans on. It supplies a pre-period for the index arm
and a second, independent issuer for cross-checking the measurement chain.

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
