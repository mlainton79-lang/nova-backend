---
name: document-search
description: Searches Matthew's accumulated documents (letters, payslips, contracts, forms, etc.) semantically. Use when he asks 'find that letter about...', 'what did the nursery say about...', 'what's in my contract about holiday', or any query that references a past document.
version: 0.1.0
triggers:
  - find that letter
  - that document
  - my contract says
  - what did it say about
  - what was in that
  - remind me what the
  - the letter from
  - my payslip
  - the contract
  - what did the nursery say
  - what did the gp say
  - my letter
---

# Document Search

When Matthew references something he's shown Tony before (a letter, contract, payslip, form), search his document memory semantically.

## Workflow

1. Call `/api/v1/documents/search` with his query
2. If results with high similarity (>0.6): summarise what they say, cite the doc
3. If results are weak (<0.4): say 'I can't find that in what you've shown me. Upload it?'

## Format

Don't dump the document. Give the answer:

  "That's the nursery letter from March. They said Amelia needs a change of clothes by Friday and the Easter party's at 2pm Thursday."

If multiple documents match:
  "Your employment contract (section 12) says 28 days. The HR policy letter from February adds a further 3 after 5 years."

## What NOT to do

- Don't read out the entire document unless asked
- Don't invent content that isn't in the returned chunks
- Don't cite a document you don't have a match for
- Don't say 'it's not in my records' without actually searching first
