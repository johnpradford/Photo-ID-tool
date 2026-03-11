"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import SpeciesSearch from "@/components/SpeciesSearch";
import type { Classification, Assignment, Species } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  photoId: string;
  nextId: string | null;
  existing: Assignment | null;
}

const classifications: { value: Classification; label: string; color: string }[] = [
  { value: "animal",        label: "Animal",        color: "bg-green-700 hover:bg-green-600" },
  { value: "blank",         label: "Blank",         color: "bg-secondary hover:bg-accent" },
  { value: "human",         label: "Human",         color: "bg-orange-700 hover:bg-orange-600" },
  { value: "vehicle",       label: "Vehicle",       color: "bg-blue-700 hover:bg-blue-600" },
  { value: "false_trigger", label: "False trigger", color: "bg-secondary hover:bg-accent" },
];

export default function ClassifyPanel({ photoId, nextId, existing }: Props) {
  const router = useRouter();
  const supabase = createClient();
  const [isPending, startTransition] = useTransition();

  const [classification, setClassification] = useState<Classification | null>(
    existing?.classification ?? null
  );
  const [selectedSpecies, setSelectedSpecies] = useState<Species | null>(null);
  const [taxonName, setTaxonName]   = useState(existing?.taxon_name ?? "");
  const [commonName, setCommonName] = useState(existing?.common_name ?? "");
  const [abundance, setAbundance]   = useState(existing?.abundance ?? 1);
  const [behaviour, setBehaviour]   = useState(existing?.behaviour ?? "");
  const [notes, setNotes]           = useState(existing?.notes ?? "");
  const [saving, setSaving]         = useState(false);
  const [error, setError]           = useState<string | null>(null);

  function handleSpeciesSelect(s: Species) {
    setSelectedSpecies(s);
    setTaxonName(s.taxon_name);
    setCommonName(s.common_name ?? "");
  }

  async function handleSave() {
    if (!classification) return;
    setSaving(true);
    setError(null);

    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) { setSaving(false); return; }

    const row = {
      photo_id:       photoId,
      user_id:        user.id,
      classification,
      taxon_name:     classification === "animal" ? taxonName || null : null,
      common_name:    classification === "animal" ? commonName || null : null,
      abundance:      classification === "animal" ? abundance : 1,
      behaviour:      behaviour || null,
      notes:          notes || null,
    };

    // Upsert: delete existing then insert (Supabase RLS safe)
    if (existing) {
      await supabase.from("assignments").delete().eq("id", existing.id);
    }
    const { error: insertErr } = await supabase.from("assignments").insert(row);
    if (insertErr) {
      setError(insertErr.message);
      setSaving(false);
      return;
    }

    // Update photo status
    const photoStatus = classification === "animal" ? "assigned" : classification;
    await supabase.from("photos").update({ status: photoStatus }).eq("id", photoId);

    setSaving(false);
    startTransition(() => {
      if (nextId) {
        router.push(`/review/${nextId}`);
      } else {
        router.push("/dashboard");
      }
      router.refresh();
    });
  }

  return (
    <div className="p-4 space-y-5">
      <div>
        <p className="text-xs text-muted-foreground uppercase tracking-wide mb-2">
          Classification
        </p>
        <div className="grid grid-cols-1 gap-2">
          {classifications.map((c) => (
            <button
              key={c.value}
              onClick={() => setClassification(c.value)}
              className={cn(
                "rounded px-3 py-2 text-sm font-medium text-left transition-colors",
                c.color,
                classification === c.value
                  ? "ring-2 ring-ring"
                  : "opacity-70 hover:opacity-100"
              )}
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>

      {/* Species section — only shown for animal */}
      {classification === "animal" && (
        <div className="space-y-3">
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wide mb-1">
              Species
            </p>
            <SpeciesSearch
              onSelect={handleSpeciesSelect}
              selectedTaxon={taxonName || null}
            />
          </div>

          {taxonName && (
            <div className="bg-accent/50 rounded px-3 py-2 text-sm">
              <p className="italic font-medium">{taxonName}</p>
              {commonName && (
                <p className="text-muted-foreground text-xs">{commonName}</p>
              )}
            </div>
          )}

          <div>
            <label className="block text-xs text-muted-foreground mb-1">
              Abundance
            </label>
            <input
              type="number"
              min={1}
              value={abundance}
              onChange={(e) => setAbundance(Math.max(1, parseInt(e.target.value) || 1))}
              className="w-20 bg-input border border-border rounded px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>

          <div>
            <label className="block text-xs text-muted-foreground mb-1">
              Behaviour
            </label>
            <input
              type="text"
              value={behaviour}
              onChange={(e) => setBehaviour(e.target.value)}
              placeholder="e.g. foraging"
              className="w-full bg-input border border-border rounded px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
        </div>
      )}

      {/* Notes — always shown */}
      <div>
        <label className="block text-xs text-muted-foreground mb-1">Notes</label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          placeholder="Optional notes…"
          className="w-full bg-input border border-border rounded px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-ring resize-none"
        />
      </div>

      {error && <p className="text-destructive text-sm">{error}</p>}

      {/* Save / Skip */}
      <div className="flex gap-2 pt-1">
        <button
          onClick={handleSave}
          disabled={!classification || saving || isPending}
          className="flex-1 bg-primary text-primary-foreground rounded px-3 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-40 transition-opacity"
        >
          {saving || isPending ? "Saving…" : nextId ? "Save & Next →" : "Save & Finish"}
        </button>
        {nextId && (
          <button
            onClick={() => router.push(`/review/${nextId}`)}
            className="text-sm text-muted-foreground hover:text-foreground px-2"
            title="Skip"
          >
            Skip
          </button>
        )}
      </div>
    </div>
  );
}
