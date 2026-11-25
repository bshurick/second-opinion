# What this means for you

"What this means for you" is the deep part of the card. The other three fields describe the page. This one works out what the readings do to this person's accounts, and it sits folded, so it has room.

- Write one point per asset class the person owns, largest first by value, up to five. A class no reading touches gets no point.
- Build each point from two results: this run's brief (`allocation`, `sector_weights`, `positions`, `movers`, `events`) and this run's `indices.py` output.
- Each point carries four things: the reading with its number and date, the holding with its value and weight, the mechanism that links the two, and the side that helps and the side that hurts.
- Do the arithmetic when the outputs give both numbers, and show both: a weight times a move is a contribution to the day, and a cash balance times a rate is a year of interest at today's rate. Label the result as arithmetic at today's figures.
- Say where the data stops. A fund is not looked through, so a sector reading reaches an index fund only through the index.
- A point that restates a weight or a day change with no market reading beside it is a recap. Cut it or finish it.

Readings to trace for each asset class:

| The person owns | Readings to trace |
|---|---|
| Cash and money-market funds | The 13-week bill yield and the fed funds rate set what the cash earns. Their change over the week and the year says which way that income is heading. |
| Bonds and bond funds | The 2-, 10- and 30-year yield changes in basis points: a bond fund's price moves against yields. The 10-year against the 13-week spread, for what longer bonds pay over cash. |
| Stock index funds | The S&P 500's move, the three trend gaps in the order 200-, 100- and 50-week, and equal-weight against cap-weight returns for a cap-weighted fund. |
| Single stocks and sector tilts | The person's sector weights against each sector fund's day and week move. |
| International stocks | The dollar index and its week change: a rising dollar cuts the dollar value of foreign shares. |
| Pay and stock awards from one employer | The employer's sector move, as non-numeric context from memory or the profile. |

Before: "Cash and money-market funds are 51.5% and bonds 26.5%, so US stocks (19.4%) carry most of the move."

After: `{"topic": "Bonds", "text": "Bonds are $153,396, 26.5% of the accounts. The 10-year Treasury yield fell 13 basis points today to 4.922%, and a bond fund's price moves against yields, so BND rose 0.69% while the S&P 500 fell 3.11%. The helping side: falling yields lift this quarter of the accounts on days stocks drop. The hurting side: the 10-year is still up 79 basis points over the year."}`
