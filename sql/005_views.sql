-- Additive migration: clean read-only views for the text-to-SQL lane.
-- Human-readable names, no surprises, base tables untouched. The rag_reader
-- role (scripts/setup_ro_role.py) gets SELECT on exactly these views.

CREATE OR REPLACE VIEW v_jobs AS
SELECT j.job_id,
       j.job_name,
       j.account_name AS customer,
       j.salesperson,
       j.city,
       j.process_name,
       j.job_status_name AS status,
       j.creation_date
FROM jobs j;

CREATE OR REPLACE VIEW v_job_areas AS
SELECT a.job_id,
       j.job_name,
       a.area_name,
       a.room_type,
       a.sq_ft,
       a.material_name,
       a.supplier,
       a.edge,
       a.backsplash,
       a.sink
FROM job_areas a
JOIN jobs j USING (job_id);

CREATE OR REPLACE VIEW v_invoices AS
SELECT i.doc_number,
       i.customer_name,
       i.txn_date,
       i.total_amt,
       i.balance,
       i.status
FROM invoices i;

CREATE OR REPLACE VIEW v_job_invoices AS
SELECT ji.job_id,
       j.job_name,
       ji.doc_number,
       i.txn_date,
       i.total_amt,
       i.balance,
       i.status
FROM job_invoices ji
JOIN jobs j USING (job_id)
LEFT JOIN invoices i USING (doc_number);

CREATE OR REPLACE VIEW v_activities AS
SELECT a.activity_id,
       a.job_id,
       j.job_name,
       a.type_name,
       a.status_name,
       a.activity_date,
       a.phase,
       (SELECT string_agg(aa.assignee_name, ', ')
        FROM activity_assignees aa
        WHERE aa.activity_id = a.activity_id) AS assignees,
       a.notes AS note
FROM activities a
JOIN jobs j USING (job_id);
