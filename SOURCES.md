# Data sources (reconnaissance notes, 2026-10-03)

## d3datacast.com (men's NPI link target; also has women's)

WordPress.com site; every data page embeds one published Google Sheet. No bot challenge.
CSV per tab, CORS `*` on the final response, so the browser or the fetcher can read it:

    https://docs.google.com/spreadsheets/d/e/2PACX-1vR1ycFpv6ciu3cCFcVptinzHtlVFaM4hmZpV0KZSmMCMlb9h39m3n4bByXz3i_SKuE0Me7tXmmhZHYT/pub?gid=<GID>&single=true&output=csv

| Tab | gid | Page | Updated stamp seen |
|---|---|---|---|
| MBB NPI | 1357390615 | https://d3datacast.com/npi/mbb/ | 3/11/26 (2025-26 final) |
| MBB Simulations | 635549745 | https://d3datacast.com/npi/mbb-projections/ | 3/1/26 |
| MBB Bubble Watch | 1333694116 | same | 3/1/26 |
| MBB Efficiency | 201951160 | https://d3datacast.com/efficiency-ratings/ | 10/2/26 (2026-27 preseason) |
| MBB Score Predictions | 788973009 | https://d3datacast.com/efficiency-ratings/score-predictions/ | stale until season |
| MIAA conference tab | 1933734014 | https://d3datacast.com/conference-ratings/miaa/ | MBB and WBB blocks |
| WBB NPI | 331027132 | https://d3datacast.com/npi/wbb/ | 3/1/26 |
| WBB Simulations | 645610244 | https://d3datacast.com/npi/wbb-projections/ | |
| WBB Efficiency | 1475800739 | https://d3datacast.com/efficiency-ratings/wbb-efficiency-ratings/ | 10/2/26 |
| WBB Score Predictions | 1291482172 | https://d3datacast.com/efficiency-ratings/wbb-score-predictions/ | |

CSV shape: banner rows, an "Updated:" row, two header rows, data from about row 8. Find the
header row by text, not by index; there are blank spacer columns. NPI header:
`Rank,Team,Conference,GP,W,L,W,L,ONPI,NPI,Bid,Rank,Seed`; sample
`78,Hope,MIAA,27,18,9,16.1,9.3,54.585,57.693,AQ,-,49`. Team names: Adrian, Albion, Alma,
Calvin, Hope, Kalamazoo, Olivet, Trine. No per-team pages; deep link is the MIAA page or the
national table. Check the "Updated:" cell: NPI stays on last season until new data lands.

Dashboard use (men): NPI rank + value, bid status; preseason efficiency rank (AdjEM) as a
second headline; next-game win % from score predictions once the season starts.

## Domain shortlist (RDAP 2026-10-03, all .com free unless noted)

themissingmiaapage, bettermiaahoops, themiaasiteyouwanted, miaapossession, unofficialmiaahoops,
missingmiaadashboard, betterthanmiaaorg, miaafullcourt, miaahoopsboard, miaadashboard,
abettermiaahoopsdashboard (25 chars). Registered: mittenhoops.com (.net/.org free).
