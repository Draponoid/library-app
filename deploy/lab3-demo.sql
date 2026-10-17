-- Add labelled educational catalog records without replacing existing catalog or accounts.
BEGIN;
SELECT pg_advisory_xact_lock(20261003);

INSERT INTO public.authors (name)
VALUES ('Учебные материалы DevOps')
ON CONFLICT (name) DO NOTHING;

INSERT INTO public.branches (name, address)
VALUES ('Учебный филиал ЛР3', 'Учебный стенд DevOps, виртуальные машины ЛР3')
ON CONFLICT (name) DO NOTHING;

INSERT INTO public.books (title, author_id, year, isbn)
SELECT 'ЛР3: автоматические проверки и резервное копирование', id, 2026, 'LAB3-DEVOPS-2026'
FROM public.authors WHERE name = 'Учебные материалы DevOps'
ON CONFLICT (isbn) DO NOTHING;

INSERT INTO public.copies (book_id, branch_id, inventory_number)
SELECT book.id, branch.id, inventory.number
FROM public.books book
CROSS JOIN public.branches branch
CROSS JOIN (VALUES ('LAB3-DEMO-001'), ('LAB3-DEMO-002')) inventory(number)
WHERE book.isbn = 'LAB3-DEVOPS-2026' AND branch.name = 'Учебный филиал ЛР3'
ON CONFLICT (inventory_number) DO NOTHING;

INSERT INTO public.audit_events (actor_id, action, entity, entity_id, created_at)
SELECT NULL, 'seed_demo', 'lab3_catalog', book.id,
       to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
FROM public.books book
WHERE book.isbn = 'LAB3-DEVOPS-2026'
  AND NOT EXISTS (
      SELECT 1 FROM public.audit_events audit
      WHERE audit.action = 'seed_demo' AND audit.entity = 'lab3_catalog' AND audit.entity_id = book.id
  );

COMMIT;
