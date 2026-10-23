# Prior-Art Sweep — 2026-08-17

Re-run of the novelty check before committing further effort. The question at risk:
whether anyone has published the *dynamic* claim — that the price impact of a newly
created, fully disclosed, calendar-scheduled option flow decays at a measurable rate
toward a positive floor.

## Verdict

**No kill found. Novelty verdict unchanged: HIGH (Level C).**

## What was searched

Launch event studies on option-income and buffer ETFs; absorption and half-life of
predictable-flow impact; defined-outcome FLEX price impact on the S&P 500; the AFA
2027 programme.

## Findings

**Nothing new on option-income ETF market impact.** Park & Kurucak (2025) remains the
only located study, and it remains monthly, mutual-fund, level-only — no launches, no
strike localisation, no decay, no costs.

**Nothing empirical on buffer / defined-outcome ETF price impact.** Searches return
prospectuses and product explainers only. The mechanism is described in every filing
and studied by nobody located here.

**One framing to confront directly.** Zhao (2026) summarises the existing literature
as: predictable uninformed flow attracts anticipatory liquidity provision, so impact
is "modest and declining **in predictability**". That is a *cross-sectional* claim —
more predictable flows have smaller impact. The claim here is *dynamic* — the same
flow's impact shrinks as the programme ages and capital organises around it. The two
are related and must be distinguished explicitly in the paper, because a referee will
read them as the same sentence. They are not: Brøgger's VIX result is the endpoint of
the process, and the question is the path to it and whether the endpoint is zero.

**AFA 2027 programme not yet published.** Only the 2026 programme is reachable. Re-run
this check when it appears; it is the most likely early warning of a competing paper.

## Limitation of this sweep, stated plainly

Conducted through general web search. Google Scholar and SSRN's own search interface
both refused automated requests (403), and the Semantic Scholar API rate-limited.
So this sweep is weaker than a direct database query and should not be read as
exhaustive. Absence of evidence here is genuinely weak evidence of absence.

Before posting, the sweep must be re-run manually against Google Scholar, SSRN and
NBER, plus the AFA/WFA programmes. That is a prerequisite for any novelty claim in the
paper, not an optional extra.

## Standing race-risk estimate

Unchanged at roughly 32%, dominated by the ~18% that someone extends Huang (2025)-style
launch-event designs from leveraged single-stock ETFs to option-income ones. Nothing in
this sweep raises or lowers it.

## Addendum, same day: OpenAlex

Scholar and SSRN block automated access, so the sweep was repeated against OpenAlex,
a free open scholarly API with no auth.

A first query sorted by publication date, which overrode relevance ranking and
returned unrelated work; that result is discarded. Re-run on relevance, the only
covered-call-ETF hit is a volatility-*forecasting* paper (HAR-RV-CARMA, *Risks*, 2025)
that uses QYLD/XYLD/RYLD/JEPI/JEPQ as forecasting subjects and does not examine market
impact at all.

No competitor found. But OpenAlex indexes journals far better than it indexes SSRN and
NBER working papers, which is exactly where a competing paper would first appear. This
raises confidence only slightly and does not replace the manual sweep.
