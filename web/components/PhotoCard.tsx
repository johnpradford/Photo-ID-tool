"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";
import type { Photo, PhotoStatus } from "@/lib/types";

const statusColors: Record<PhotoStatus, string> = {
  pending: "bg-yellow-500/20 text-yellow-300 border-yellow-500/30",
  assigned: "bg-green-500/20 text-green-300 border-green-500/30",
  blank: "bg-muted text-muted-foreground border-border",
  human: "bg-orange-500/20 text-orange-300 border-orange-500/30",
  vehicle: "bg-blue-500/20 text-blue-300 border-blue-500/30",
  false_trigger: "bg-muted text-muted-foreground border-border",
};

const statusLabel: Record<PhotoStatus, string> = {
  pending: "Pending",
  assigned: "Assigned",
  blank: "Blank",
  human: "Human",
  vehicle: "Vehicle",
  false_trigger: "False trigger",
};

interface Props {
  photo: Photo;
}

export default function PhotoCard({ photo }: Props) {
  return (
    <Link href={`/review/${photo.id}`}>
      <div className="group rounded-lg border border-border overflow-hidden hover:border-primary transition-colors cursor-pointer">
        {/* Placeholder thumbnail — no public URL needed, clicking loads signed URL */}
        <div className="aspect-square bg-muted flex items-center justify-center relative">
          <svg
            className="w-8 h-8 text-muted-foreground/40"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          >
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <circle cx="8.5" cy="8.5" r="1.5" />
            <polyline points="21 15 16 10 5 21" />
          </svg>
          <span
            className={cn(
              "absolute top-2 right-2 text-xs px-1.5 py-0.5 rounded border",
              statusColors[photo.status]
            )}
          >
            {statusLabel[photo.status]}
          </span>
        </div>

        {/* Filename */}
        <div className="px-2 py-1.5">
          <p className="text-xs text-muted-foreground truncate">{photo.filename}</p>
        </div>
      </div>
    </Link>
  );
}
