-- ============================================================
-- Fauna Photo-ID Tool — Initial Schema
-- Run this in: Supabase Dashboard → SQL Editor → New query
-- ============================================================

-- ---------------------------------------------------------------
-- 1. Species table (seeded from WAM Excel workbook)
-- ---------------------------------------------------------------
create table if not exists public.species (
  id            uuid primary key default gen_random_uuid(),
  taxon_name    text unique not null,          -- scientific name (unique key)
  common_name   text,
  family        text,
  order_name    text,
  genus         text,
  kingdom       text,
  phylum        text,
  class_name    text,
  biologic_name text                           -- alternate/vernacular scientific name
);

create index if not exists species_taxon_name_idx    on public.species (lower(taxon_name));
create index if not exists species_common_name_idx   on public.species (lower(common_name));
create index if not exists species_family_idx        on public.species (lower("family"));

-- Full-text search index combining all searchable fields
create index if not exists species_search_idx on public.species
  using gin(to_tsvector('english',
    coalesce(taxon_name, '') || ' ' ||
    coalesce(common_name, '') || ' ' ||
    coalesce(family, '') || ' ' ||
    coalesce(genus, '')
  ));

-- ---------------------------------------------------------------
-- 2. Photos table
-- Note: user_id is uuid (no FK to auth.users — RLS enforces ownership)
-- ---------------------------------------------------------------
create table if not exists public.photos (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null,
  storage_path  text not null,                -- path in Supabase Storage bucket
  filename      text not null,
  uploaded_at   timestamptz default now(),
  status        text not null default 'pending'
                  check (status in ('pending','assigned','blank','human','vehicle','false_trigger'))
);

create index if not exists photos_user_id_idx  on public.photos (user_id);
create index if not exists photos_status_idx   on public.photos (status);

-- ---------------------------------------------------------------
-- 3. Assignments table
-- ---------------------------------------------------------------
create table if not exists public.assignments (
  id              uuid primary key default gen_random_uuid(),
  photo_id        uuid references public.photos on delete cascade not null,
  user_id         uuid not null,
  classification  text not null
                    check (classification in ('animal','blank','human','vehicle','false_trigger')),
  -- Species fields (populated when classification = 'animal')
  taxon_name      text,
  common_name     text,
  -- Observation metadata
  date_obs        date,
  time_obs        text,
  latitude        numeric(10,6),
  longitude       numeric(10,6),
  camera_make     text,
  camera_model    text,
  abundance       integer default 1,
  behaviour       text,
  notes           text,
  -- Survey context
  survey_name     text,
  location        text,
  assigned_at     timestamptz default now()
);

create index if not exists assignments_photo_id_idx on public.assignments (photo_id);
create index if not exists assignments_user_id_idx  on public.assignments (user_id);

-- ---------------------------------------------------------------
-- 4. Audit log table
-- ---------------------------------------------------------------
create table if not exists public.audit_log (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid,
  photo_id   uuid references public.photos on delete set null,
  action     text not null,
  details    jsonb,
  created_at timestamptz default now()
);

create index if not exists audit_log_user_id_idx  on public.audit_log (user_id);
create index if not exists audit_log_photo_id_idx on public.audit_log (photo_id);

-- ---------------------------------------------------------------
-- 5. Row-Level Security
-- ---------------------------------------------------------------
alter table public.photos      enable row level security;
alter table public.assignments enable row level security;
alter table public.audit_log   enable row level security;
alter table public.species     enable row level security;

-- Species: anyone authenticated can read
create policy "species_read" on public.species
  for select using (auth.role() = 'authenticated');

-- Photos: users can only see/write their own
create policy "photos_select_own" on public.photos for select using (auth.uid() = user_id);
create policy "photos_insert_own" on public.photos for insert with check (auth.uid() = user_id);
create policy "photos_update_own" on public.photos for update using (auth.uid() = user_id);
create policy "photos_delete_own" on public.photos for delete using (auth.uid() = user_id);

-- Assignments: users can only see/write their own
create policy "assignments_select_own" on public.assignments for select using (auth.uid() = user_id);
create policy "assignments_insert_own" on public.assignments for insert with check (auth.uid() = user_id);
create policy "assignments_update_own" on public.assignments for update using (auth.uid() = user_id);
create policy "assignments_delete_own" on public.assignments for delete using (auth.uid() = user_id);

-- Audit log: users can insert and read their own entries
create policy "audit_log_insert_own" on public.audit_log for insert with check (auth.uid() = user_id);
create policy "audit_log_select_own" on public.audit_log for select using (auth.uid() = user_id);

-- ---------------------------------------------------------------
-- 6. Storage bucket (create manually in Supabase dashboard)
-- Storage → New bucket → Name: photos → Private
-- File size limit: 50MB
-- Allowed MIME types: image/jpeg, image/png, image/tiff, image/webp
-- ---------------------------------------------------------------

-- ---------------------------------------------------------------
-- Notes on running this migration:
-- 1. Go to https://supabase.com/dashboard/project/llbbexjthcbmgkwkekrc/sql/new
-- 2. Paste this entire file and click Run
-- 3. Then run: python web/supabase/seed/seed_species.py
-- 4. Then create the "photos" storage bucket in:
--    Storage → New bucket → Name: photos → Private
-- ---------------------------------------------------------------
