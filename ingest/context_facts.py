"""Shared chunk-selection and context-fact building for the semantic layer.

Both build_chunks.py (which hashes the facts into text_hash so a changed job
header re-triggers enrichment) and contextualize.py (which puts the same facts
in the Haiku prompt) import from here, so the two can never drift apart.

Chunk sources and keys:
  * activity_note  / source_id = activity_id   (activities.notes)
  * area_note      / source_id = form_id       (job_areas.notes via its Details
    form, plus the Job Summary form's "Notes" field from area_fields)
    -- keyed on form_id, NOT job_areas.area_id, because job_areas is disposable
    (derive_areas.py truncate+rebuilds it, regenerating area_ids) while
    Moraware form ids are stable.

Selection threshold: trimmed length >= 25 characters. Shorter notes ("done",
"paid", a bare invoice number) carry almost no semantic content beyond what the
structured tables already answer, so embedding them would only add noise to
retrieval; they remain fully queryable in activities/job_areas. The 25-char
line matches the WO3 profiling run (~5.8k activity + ~1.3k area notes).
"""

MIN_CHARS = 25


def _fmt(parts):
    return "; ".join(p for p in parts if p)


def load_job_facts(cur) -> dict:
    """job_id -> one-line fact string about the job (deterministic)."""
    cur.execute("""
        SELECT j.job_id, j.job_name, j.city, j.salesperson, j.account_name,
               j.process_name, j.job_status_name,
               m.materials, m.n_areas
        FROM jobs j
        LEFT JOIN (
            SELECT job_id,
                   string_agg(DISTINCT material_name, ', ') FILTER
                       (WHERE material_name <> '') AS materials,
                   count(*) AS n_areas
            FROM job_areas GROUP BY job_id
        ) m ON m.job_id = j.job_id
    """)
    facts = {}
    for (jid, name, city, sales, account, process, status,
         materials, n_areas) in cur.fetchall():
        parts = [
            f"Job \"{name}\"" if name else f"Job {jid}",
            f"in {city}" if city else None,
            f"salesperson {sales}" if sales else None,
            f"account {account}" if account and account != name else None,
            f"process {process}" if process else None,
            f"status {status}" if status else None,
            f"materials on this job: {materials}" if materials else None,
        ]
        facts[jid] = (_fmt(parts), n_areas or 0)
    return facts


def iter_activity_chunks(cur, job_facts):
    """Yield (source_id, job_id, raw_text, facts) for qualifying activity notes."""
    cur.execute("""
        SELECT activity_id, job_id, type_name, status_name, activity_date,
               phase, notes
        FROM activities
        WHERE notes IS NOT NULL AND notes <> ''
    """)
    for aid, jid, tname, sname, adate, phase, notes in cur.fetchall():
        if len(notes.strip()) < MIN_CHARS:
            continue
        jf, _ = job_facts[jid]
        parts = [
            jf,
            f"this note is on a {tname} activity" if tname else "this note is on an activity",
            f"activity status {sname}" if sname else None,
            f"dated {adate}" if adate else "undated",
            f"phase {phase}" if phase else None,
        ]
        yield aid, jid, notes, _fmt(parts)


def iter_area_chunks(cur, job_facts):
    """Yield (source_id=form_id, job_id, raw_text, facts) for area/summary notes."""
    cur.execute("""
        SELECT form_id, job_id, area_name, room_type, sq_ft_raw,
               material_name, supplier, notes
        FROM job_areas
        WHERE notes IS NOT NULL AND notes <> ''
    """)
    for (fid, jid, aname, room, sqft, material, supplier,
         notes) in cur.fetchall():
        if len(notes.strip()) < MIN_CHARS:
            continue
        jf, n_areas = job_facts[jid]
        if aname:
            where = f"this note is on the \"{aname}\" area"
        elif n_areas == 1:
            where = ("this note is on the job's single area"
                     + (f" (room type: {room})" if room else ""))
        else:
            where = "this note is on one of the job's areas"
        parts = [
            jf,
            where,
            f"room type {room}" if room and aname else None,
            f"{sqft} sq ft" if sqft else None,
            f"area material {material}" if material else None,
            f"supplier {supplier}" if supplier else None,
        ]
        yield fid, jid, notes, _fmt(parts)

    cur.execute("""
        SELECT af.form_id, af.job_id, af.field_value
        FROM area_fields af
        JOIN job_forms f ON f.form_id = af.form_id
        WHERE f.form_template_name = 'Job Summary' AND af.field_name = 'Notes'
          AND af.field_value IS NOT NULL AND af.field_value <> ''
    """)
    for fid, jid, value in cur.fetchall():
        if len(value.strip()) < MIN_CHARS:
            continue
        jf, _ = job_facts[jid]
        yield fid, jid, value, _fmt([jf, "this note is the job's summary-form notes"])


def build_all(cur):
    """Yield (source_type, source_id, job_id, raw_text, facts) for every chunk."""
    job_facts = load_job_facts(cur)
    for sid, jid, text, facts in iter_activity_chunks(cur, job_facts):
        yield "activity_note", sid, jid, text, facts
    for sid, jid, text, facts in iter_area_chunks(cur, job_facts):
        yield "area_note", sid, jid, text, facts
