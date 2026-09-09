---
name: faq-from-questions
description: Turn the questions people keep asking into an answer you only write once. Use when asked for an FAQ, help documentation, or common questions.
allowed-tools: gmail documents
metadata:
  tags: documents, writing
---

# Build an FAQ

## Steps

1. `search_emails` for the questions that recur, and count them.
2. Write each as the question a person would actually type, with a short
   direct answer.
3. Produce it with `create_document`, ordered by how often it was asked.

## Rules

- Use their words for the question, not the internally correct phrasing.
  People search with the words they have.
- Answer in the first sentence, then the detail. An FAQ that builds to the
  answer is unusable.
- Include the awkward ones. An FAQ that answers only the easy questions gets
  no trust.
