-- Additive migration: keep the QuickBooks "Line Items" display string verbatim
-- on the invoice, alongside the best-effort parsed rows in invoice_lines.
-- Never edit 001; migrations are append-only.

ALTER TABLE invoices ADD COLUMN IF NOT EXISTS line_summary_raw text;
