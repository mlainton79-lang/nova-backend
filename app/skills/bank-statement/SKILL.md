---
name: bank-statement
description: Reads a photographed or uploaded bank statement and summarises where Matthew's money went. Use when Matthew uploads a statement screenshot, a PDF of his banking, or asks to 'go through my statement' / 'check my transactions'.
version: 0.1.0
triggers:
  - my statement
  - my bank statement
  - go through my transactions
  - check my transactions
  - my spending this month
  - what went out of my account
  - review my bank
---

# Bank Statement Reader

When Matthew shows a statement (screenshot, PDF scan, or photo), extract the transactions and give him a useful summary — not a dump of every line.

## What to produce

1. **Total in / Total out** for the period shown
2. **Big transactions** (over £50) — by size, with merchant
3. **Top 5 merchants by spend**
4. **Anything unusual** — duplicate charges, subscriptions he might've forgotten, direct debits

Not a list of every £1.50 coffee. Matthew doesn't need an accountant's printout.

## Format

Keep it tight:

  Period: [dates visible]
  In: £X  Out: £Y  Net: £Z
  
  Big ones:
  - £N DATE Merchant — [if suspicious: flagged]
  - £N DATE Merchant
  
  Top merchants:
  1. X — £N
  2. Y — £N
  
  Worth flagging: [only if something truly unusual]

## Privacy and accuracy

- Extract ONLY what's visible. Don't infer account numbers, sort codes, or balances you can't see clearly.
- Don't guess amounts. If a digit is unclear, say "approx £N" or skip the line.
- Don't save this data anywhere — Matthew sees it, uses it, done.
- Don't make assumptions about whether a transaction is 'good' or 'bad' unless asked.

## What NOT to do

- Don't lecture about his spending
- Don't suggest budget changes unless asked
- Don't compare to "typical spending for someone in your situation"
- Don't flag normal things (groceries, fuel, utilities) as concerns
- Don't invent interest rates or fees you don't see

## Cross-reference

If he's got receipts logged in the expense tracker (`tony_expenses`), optionally note:
  "Your receipt log has Tesco £47 on [date] — matches the statement entry."
  
This builds confidence in both systems. But only mention this if there's a clear match.
