// -----------------------------------------------------------------------
// Database type definitions matching the Supabase schema in
// supabase/migrations/001_initial.sql
// -----------------------------------------------------------------------

export type Classification =
  | "animal"
  | "blank"
  | "human"
  | "vehicle"
  | "false_trigger";

export type PhotoStatus =
  | "pending"
  | "assigned"
  | "blank"
  | "human"
  | "vehicle"
  | "false_trigger";

export type Photo = {
  id: string;
  user_id: string;
  storage_path: string;
  filename: string;
  uploaded_at: string;
  status: PhotoStatus;
};

export type Species = {
  id: string;
  taxon_name: string;
  common_name: string | null;
  family: string | null;
  order_name: string | null;
  genus: string | null;
  kingdom: string | null;
  phylum: string | null;
  class_name: string | null;
  biologic_name: string | null;
};

export type Assignment = {
  id: string;
  photo_id: string;
  user_id: string;
  classification: Classification;
  taxon_name: string | null;
  common_name: string | null;
  assigned_at: string;
  date_obs: string | null;
  time_obs: string | null;
  latitude: number | null;
  longitude: number | null;
  camera_make: string | null;
  camera_model: string | null;
  abundance: number;
  behaviour: string | null;
  notes: string | null;
  survey_name: string | null;
  location: string | null;
};

export type AuditLog = {
  id: string;
  user_id: string | null;
  photo_id: string | null;
  action: string;
  details: Record<string, unknown> | null;
  created_at: string;
};

// -----------------------------------------------------------------------
// Supabase database shape for typed client
// -----------------------------------------------------------------------
export type Database = {
  public: {
    Tables: {
      photos: {
        Row: Photo;
        Insert: Omit<Photo, "id" | "uploaded_at">;
        Update: Partial<Omit<Photo, "id">>;
        Relationships: [];
      };
      species: {
        Row: Species;
        Insert: Omit<Species, "id">;
        Update: Partial<Omit<Species, "id">>;
        Relationships: [];
      };
      assignments: {
        Row: Assignment;
        Insert: {
          photo_id: string;
          user_id: string;
          classification: Classification;
          taxon_name?: string | null;
          common_name?: string | null;
          abundance?: number;
          behaviour?: string | null;
          notes?: string | null;
          date_obs?: string | null;
          time_obs?: string | null;
          latitude?: number | null;
          longitude?: number | null;
          camera_make?: string | null;
          camera_model?: string | null;
          survey_name?: string | null;
          location?: string | null;
        };
        Update: Partial<Omit<Assignment, "id">>;
        Relationships: [];
      };
      audit_log: {
        Row: AuditLog;
        Insert: Omit<AuditLog, "id" | "created_at">;
        Update: Partial<Omit<AuditLog, "id">>;
        Relationships: [];
      };
    };
    Views: Record<string, never>;
    Functions: Record<string, never>;
    Enums: Record<string, never>;
  };
};
