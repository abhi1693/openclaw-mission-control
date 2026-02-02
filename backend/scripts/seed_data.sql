-- Mission Control seed data (minimal)
-- Keep this data-only seed small and deterministic.
-- NOTE: Do NOT include alembic_version here; migrations manage it.

SET client_min_messages = warning;
SET row_security = off;

-- Disable triggers to avoid FK ordering issues during seed.
ALTER TABLE public.employees DISABLE TRIGGER ALL;
ALTER TABLE public.departments DISABLE TRIGGER ALL;
ALTER TABLE public.teams DISABLE TRIGGER ALL;
ALTER TABLE public.projects DISABLE TRIGGER ALL;
ALTER TABLE public.tasks DISABLE TRIGGER ALL;
ALTER TABLE public.task_comments DISABLE TRIGGER ALL;
ALTER TABLE public.project_members DISABLE TRIGGER ALL;
ALTER TABLE public.activities DISABLE TRIGGER ALL;

-- Employees (keep only Jarvis + Abhimanyu)
INSERT INTO public.employees (id, name, employee_type, department_id, manager_id, title, status, openclaw_session_key, notify_enabled, team_id)
VALUES
  (1, 'Jarvis', 'agent', NULL, NULL, 'CTO', 'active', NULL, true, NULL),
  (2, 'Abhimanyu', 'human', NULL, NULL, 'CEO', 'active', NULL, false, NULL)
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name,
  employee_type = EXCLUDED.employee_type,
  department_id = EXCLUDED.department_id,
  manager_id = EXCLUDED.manager_id,
  title = EXCLUDED.title,
  status = EXCLUDED.status,
  openclaw_session_key = EXCLUDED.openclaw_session_key,
  notify_enabled = EXCLUDED.notify_enabled,
  team_id = EXCLUDED.team_id;

-- Fix sequences (avoid PK reuse after explicit ids)
SELECT setval('employees_id_seq', (SELECT COALESCE(max(id), 1) FROM public.employees));
SELECT setval('departments_id_seq', (SELECT COALESCE(max(id), 1) FROM public.departments));
SELECT setval('teams_id_seq', (SELECT COALESCE(max(id), 1) FROM public.teams));
SELECT setval('projects_id_seq', (SELECT COALESCE(max(id), 1) FROM public.projects));
SELECT setval('tasks_id_seq', (SELECT COALESCE(max(id), 1) FROM public.tasks));
SELECT setval('task_comments_id_seq', (SELECT COALESCE(max(id), 1) FROM public.task_comments));
SELECT setval('project_members_id_seq', (SELECT COALESCE(max(id), 1) FROM public.project_members));
SELECT setval('activities_id_seq', (SELECT COALESCE(max(id), 1) FROM public.activities));

ALTER TABLE public.employees ENABLE TRIGGER ALL;
ALTER TABLE public.departments ENABLE TRIGGER ALL;
ALTER TABLE public.teams ENABLE TRIGGER ALL;
ALTER TABLE public.projects ENABLE TRIGGER ALL;
ALTER TABLE public.tasks ENABLE TRIGGER ALL;
ALTER TABLE public.task_comments ENABLE TRIGGER ALL;
ALTER TABLE public.project_members ENABLE TRIGGER ALL;
ALTER TABLE public.activities ENABLE TRIGGER ALL;
