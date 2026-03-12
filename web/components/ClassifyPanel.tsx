"use client";

import { useState, useEffect, useRef, useTransition, useCallback } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import SpeciesSearch from "@/components/SpeciesSearch";
import type { Classification, Assignment, Species } from "@/lib/types";
import { cn } from "@/lib/utils";

type QuickSpecies = { taxon_name: string; common_name: string | null };

interface Props {
  photoId: string;
  prevId: string | null;
  nextId: string | null;
  existing: Assignment | null;
}

const NON_ANIMAL: { value: Classification; label: string; key: string; color: string }[] = [
  { value: "blank",         label: "Blank",         key: "B", color: "bg-secondary hover:bg-accent" },
  { value: "human",         label: "Human",         key: "H", color: "bg-orange-700 hover:bg-orange-600" },
  { value: "vehicle",       label: "Vehicle",       key: "V", color: "bg-blue-700 hover:bg-blue-600" },
  { value: "false_trigger", label: "False trigger", key: "F", color: "bg-secondary hover:bg-accent" },
];

export default function ClassifyPanel({ photoId, prevId, nextId, existing }: Props) {
  const router = useRouter();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const supabase = useRef(createClient()).current;
  const [, startTransition] = useTransition();

  const [quickSpecies, setQuickSpecies] = useState<QuickSpecies[]>([]);
  const [abundance, setAbundance] = useState(existing?.abundance ?? 1);
  const [notes, setNotes] = useState(existing?.notes ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedLabel, setSavedLabel] = useState<string | null>(
    existing
      ? (existing.common_name ?? existing.taxon_name ?? existing.classification)
      : null
  );

  // Load top-used species from assignment history
  useEffect(() => {
    supabase
      .from("assignments")
      .select("taxon_name, common_name")
      .eq("classification", "animal")
      .not("taxon_name", "is", null)
      .then(({ data }) => {
        if (!data?.length) return;
        const freq = new Map<string, { count: number; common_name: string | null }>();
        for (const r of data) {
          if (!r.taxon_name) continue;
          const cur = freq.get(r.taxon_name);
          if (cur) cur.count++;
          else freq.set(r.taxon_name, { count: 1, common_name: r.common_name });
        }
        setQuickSpecies(
          [...freq.entries()]
            .sort((a, b) => b[1].count - a[1].count)
            .slice(0, 10)
            .map(([taxon_name, { common_name }]) => ({ taxon_name, common_name }))
        );
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const navigate = useCallback(
    (id: string | null) => {
      if (!id) return;
      startTransition(() => {
        router.push(`/review/${id}`);
        router.refresh();
      });
    },
    [router] // eslint-disable-line react-hooks/exhaustive-deps
  );

  // Stable refs so keyboard handler doesn't need to re-subscribe
  const savingRef   = useRef(saving);    savingRef.current   = saving;
  const notesRef    = useRef(notes);     notesRef.current    = notes;
  const abundRef    = useRef(abundance); abundRef.current    = abundance;
  const quickRef    = useRef(quickSpecies); quickRef.current = quickSpecies;
  const prevRef     = useRef(prevId);    prevRef.current     = prevId;
  const nextRef     = useRef(nextId);    nextRef.current     = nextId;
  const navigateRef = useRef(navigate);  navigateRef.current = navigate;

  const save = useCallback(
    async (cls: Classification, species?: { taxon_name: string; common_name: string | null }) => {
      if (savingRef.current) return;
      setSaving(true);
      setError(null);

      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) { setSaving(false); return; }

      if (existing) {
        await supabase.from("assignments").delete().eq("id", existing.id);
      }

      const { error: err } = await supabase.from("assignments").insert({
        photo_id:       photoId,
        user_id:        user.id,
        classification: cls,
        taxon_name:     cls === "animal" ? (species?.taxon_name ?? null) : null,
        common_name:    cls === "animal" ? (species?.common_name ?? null) : null,
        abundance:      cls === "animal" ? abundRef.current : 1,
        notes:          notesRef.current || null,
      });

      if (err) { setError(err.message); setSaving(false); return; }

      await supabase
        .from("photos")
        .update({ status: cls === "animal" ? "assigned" : cls })
        .eq("id", photoId);

      setSaving(false);
      setSavedLabel(
        cls === "animal"
          ? (species?.common_name ?? species?.taxon_name ?? "Animal")
          : cls.replace("_", " ")
      );
      navigateRef.current(nextRef.current);
    },
    [supabase, photoId, existing] // eslint-disable-line react-hooks/exhaustive-deps
  );

  const saveRef = useRef(save);
  saveRef.current = save;

  // Keyboard shortcuts — stable effect using refs
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      switch (e.key) {
        case "ArrowLeft":  e.preventDefault(); navigateRef.current(prevRef.current); break;
        case "ArrowRight": e.preventDefault(); navigateRef.current(nextRef.current); break;
        case "b": case "B": saveRef.current("blank"); break;
        case "h": case "H": saveRef.current("human"); break;
        case "v": case "V": saveRef.current("vehicle"); break;
        case "f": case "F": saveRef.current("false_trigger"); break;
        default: {
          const n = e.key === "0" ? 9 : parseInt(e.key) - 1;
          if (!isNaN(n) && n >= 0 && n < quickRef.current.length) {
            saveRef.current("animal", quickRef.current[n]);
          }
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []); // intentionally stable — all state accessed via refs

  return (
    <div className="p-4 space-y-4">

      {/* Quick species grid */}
      <div>
        <p className="text-xs text-muted-foreground uppercase tracking-wide mb-2">
          Quick ID <span className="normal-case text-muted-foreground/50">· keys 1–0</span>
        </p>
        {quickSpecies.length === 0 ? (
          <p className="text-xs text-muted-foreground/40 italic">
            Your most-used species will appear here.
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-1">
            {quickSpecies.map((sp, i) => (
              <button
                key={sp.taxon_name}
                onClick={() => save("animal", sp)}
                disabled={saving}
                title={sp.taxon_name}
                className="text-left bg-green-900/40 hover:bg-green-800/60 border border-green-800/30 rounded px-2 py-1.5 text-xs leading-tight transition-colors disabled:opacity-40"
              >
                <span className="font-mono text-[10px] text-green-500 mr-1.5">
                  {i === 9 ? "0" : i + 1}
                </span>
                {sp.common_name ?? sp.taxon_name}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Species search */}
      <div>
        <p className="text-xs text-muted-foreground uppercase tracking-wide mb-2">
          Search species
        </p>
        <SpeciesSearch onSelect={(s: Species) => save("animal", s)} selectedTaxon={null} />
        <div className="mt-2 flex items-center gap-2">
          <label className="text-xs text-muted-foreground">Abundance</label>
          <input
            type="number"
            min={1}
            value={abundance}
            onChange={(e) => setAbundance(Math.max(1, parseInt(e.target.value) || 1))}
            className="w-16 bg-input border border-border rounded px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </div>
      </div>

      {/* Non-animal buttons */}
      <div>
        <p className="text-xs text-muted-foreground uppercase tracking-wide mb-2">
          No animal
        </p>
        <div className="grid grid-cols-2 gap-1">
          {NON_ANIMAL.map((c) => (
            <button
              key={c.value}
              onClick={() => save(c.value)}
              disabled={saving}
              className={cn(
                "rounded px-3 py-2 text-sm font-medium text-left transition-colors disabled:opacity-40",
                c.color
              )}
            >
              <span className="font-mono text-xs opacity-40 mr-1">{c.key}</span>
              {c.label}
            </button>
          ))}
        </div>
      </div>

      {/* Notes */}
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

      {error && <p className="text-destructive text-xs">{error}</p>}
      {savedLabel && !error && (
        <p className="text-green-400 text-xs">✓ {savedLabel}</p>
      )}

      {/* Skip link when no next */}
      {!nextId && (
        <button
          onClick={() => router.push("/dashboard")}
          className="text-sm text-muted-foreground hover:text-foreground w-full text-center pt-1"
        >
          ← Back to dashboard
        </button>
      )}

      {/* Keyboard hint */}
      <div className="text-[10px] text-muted-foreground/40 space-y-0.5 pt-2 border-t border-border">
        <p>← → Navigate · B Blank · H Human · V Vehicle · F False trigger</p>
        {quickSpecies.length > 0 && (
          <p>1–{quickSpecies.length < 10 ? quickSpecies.length : "0"} Quick species</p>
        )}
      </div>
    </div>
  );
}
