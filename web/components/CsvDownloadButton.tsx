"use client";

import { Download } from "lucide-react";

// Columns matching the desktop app's 31-column IBSA format (Phase 1 subset)
const CSV_COLUMNS = [
  "PhotoID",
  "Filename",
  "DateObserved",
  "TimeObserved",
  "Latitude",
  "Longitude",
  "Classification",
  "TaxonName",
  "CommonName",
  "Family",
  "Order",
  "Class",
  "Abundance",
  "Behaviour",
  "CameraMake",
  "CameraModel",
  "SurveyName",
  "Location",
  "Notes",
  "AssignedAt",
];

interface AssignmentRow {
  id: string;
  photo_id: string;
  classification: string;
  taxon_name: string | null;
  common_name: string | null;
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
  assigned_at: string;
  photos?: { filename: string; uploaded_at: string } | null;
}

interface Props {
  assignments: AssignmentRow[];
}

function escape(val: string | number | null | undefined): string {
  if (val === null || val === undefined) return "";
  const s = String(val);
  if (s.includes(",") || s.includes('"') || s.includes("\n")) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

export default function CsvDownloadButton({ assignments }: Props) {
  function handleDownload() {
    const rows: string[] = [CSV_COLUMNS.join(",")];

    for (const a of assignments) {
      const row = [
        escape(a.photo_id),
        escape(a.photos?.filename),
        escape(a.date_obs),
        escape(a.time_obs),
        escape(a.latitude),
        escape(a.longitude),
        escape(a.classification),
        escape(a.taxon_name),
        escape(a.common_name),
        "", // Family — would come from species join (Phase 2)
        "", // Order
        "", // Class
        escape(a.abundance),
        escape(a.behaviour),
        escape(a.camera_make),
        escape(a.camera_model),
        escape(a.survey_name),
        escape(a.location),
        escape(a.notes),
        escape(a.assigned_at),
      ];
      rows.push(row.join(","));
    }

    const csv = rows.join("\r\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `fauna_photo_id_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <button
      onClick={handleDownload}
      disabled={assignments.length === 0}
      className="flex items-center gap-2 bg-primary text-primary-foreground rounded px-3 py-1.5 text-sm hover:opacity-90 disabled:opacity-40"
    >
      <Download className="w-4 h-4" />
      Download CSV ({assignments.length})
    </button>
  );
}
