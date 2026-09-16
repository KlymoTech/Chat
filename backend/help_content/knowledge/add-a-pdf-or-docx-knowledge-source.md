---
slug: add-a-pdf-or-docx-knowledge-source
title: Add a PDF or DOCX knowledge source
summary: Use trusted sources and understand how Northstar retrieves grounded information.
category: knowledge
roles:
- owner
- admin
keywords:
- add
- pdf
- docx
- knowledge
- source
- rag
- retrieval
featured: false
sort_order: 230
---

# Add a PDF or DOCX knowledge source

Upload a document so Northstar can extract, chunk, embed, and retrieve its content for the selected agent.

## Before you start

Workspace **Owner** or **Admin** access is required.

## Steps

1. Open the agent's **Knowledge** tab.
2. Select **Add source** and keep **File upload** selected.
3. Drop a PDF or DOCX into the upload area, or click to browse.
4. Confirm the file is **500 MB or smaller**.
5. Select **Add source**.
6. Watch the source move through **processing** to **ready**.

PDF, DOCX, TXT, and Markdown are accepted by the current upload flow. The backend also limits PDF pages and extracted content to protect the ingestion service.

## Troubleshooting

If a DOCX contains unusually large embedded media or a PDF is extremely long, the backend may reject it even when the compressed upload is under 500 MB.
