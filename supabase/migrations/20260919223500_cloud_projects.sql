-- PhotoForge cloud projects
-- Private per-user metadata + Storage paths. Safe to apply more than once.

create table if not exists public.projects (
  id uuid primary key,
  user_id uuid not null default (select auth.uid()) references auth.users(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 200),
  file_path text not null,
  thumb_path text,
  size_bytes bigint not null default 0 check (size_bytes >= 0),
  width integer not null check (width > 0),
  height integer not null check (height > 0),
  updated_at timestamptz not null default now()
);

create index if not exists projects_user_updated_idx
  on public.projects (user_id, updated_at desc);

alter table public.projects enable row level security;

grant select, insert, update, delete on public.projects to authenticated;

drop policy if exists "projects_select_own" on public.projects;
create policy "projects_select_own"
on public.projects
for select
to authenticated
using ((select auth.uid()) is not null and (select auth.uid()) = user_id);

drop policy if exists "projects_insert_own" on public.projects;
create policy "projects_insert_own"
on public.projects
for insert
to authenticated
with check ((select auth.uid()) is not null and (select auth.uid()) = user_id);

drop policy if exists "projects_update_own" on public.projects;
create policy "projects_update_own"
on public.projects
for update
to authenticated
using ((select auth.uid()) is not null and (select auth.uid()) = user_id)
with check ((select auth.uid()) is not null and (select auth.uid()) = user_id);

drop policy if exists "projects_delete_own" on public.projects;
create policy "projects_delete_own"
on public.projects
for delete
to authenticated
using ((select auth.uid()) is not null and (select auth.uid()) = user_id);

insert into storage.buckets (id, name, public, file_size_limit)
values ('projects', 'projects', false, 52428800)
on conflict (id) do update
set public = excluded.public,
    file_size_limit = excluded.file_size_limit;

drop policy if exists "projects_storage_select_own" on storage.objects;
create policy "projects_storage_select_own"
on storage.objects
for select
to authenticated
using (
  bucket_id = 'projects'
  and (storage.foldername(name))[1] = (select auth.uid()::text)
);

drop policy if exists "projects_storage_insert_own" on storage.objects;
create policy "projects_storage_insert_own"
on storage.objects
for insert
to authenticated
with check (
  bucket_id = 'projects'
  and (storage.foldername(name))[1] = (select auth.uid()::text)
);

drop policy if exists "projects_storage_update_own" on storage.objects;
create policy "projects_storage_update_own"
on storage.objects
for update
to authenticated
using (
  bucket_id = 'projects'
  and (storage.foldername(name))[1] = (select auth.uid()::text)
)
with check (
  bucket_id = 'projects'
  and (storage.foldername(name))[1] = (select auth.uid()::text)
);

drop policy if exists "projects_storage_delete_own" on storage.objects;
create policy "projects_storage_delete_own"
on storage.objects
for delete
to authenticated
using (
  bucket_id = 'projects'
  and (storage.foldername(name))[1] = (select auth.uid()::text)
);
