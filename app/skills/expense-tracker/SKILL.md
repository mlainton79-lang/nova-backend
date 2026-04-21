---
name: expense-tracker
description: Extracts structured data from Matthew's receipt/bill photos and tracks spending. Use when Matthew uploads a photo of a receipt, invoice, bill, or asks about his spending, expenses, where his money went, or what he spent on something.
version: 0.1.0
triggers:
  - how much did I spend
  - expense
  - receipt
  - invoice
  - bill
  - what did I spend
  - where did my money go
  - my spending
  - my expenses
  - spent on
---

# Expense Tracker

Extracts structured data from receipt/bill photos and maintains a spending log.

## When Matthew uploads a receipt photo

Call `/api/v1/expenses/extract` with the image base64. Structure returned:
  merchant, purchase_date, total, currency, category, items[], notes

Confirm briefly with Matthew — don't read the whole thing back. Something like:
  "Got it. Tesco, £23.47, groceries."

If confidence is low or anything looks wrong, flag that one detail:
  "Got it. Merchant looks like Tesco, £23.47 groceries. The date was fuzzy — is that right?"

## When Matthew asks about spending

Call `/api/v1/expenses/summary` for totals. Call `/api/v1/expenses` for the list.

Keep summaries SHORT. No tables unless asked. Example:
  "Last 30 days: £847. Biggest chunks: groceries £320, petrol £180, kids stuff £120. Anything specific you want broken down?"

## What to NOT do

- NEVER fabricate merchant names, amounts, dates, or items. If the receipt is unreadable, say so and ask Matthew to confirm.
- Don't lecture about budgeting unless asked.
- Don't flag normal spending as problematic. Matthew lives a normal life with kids.
- Don't pull expense data unprompted into unrelated conversations.
