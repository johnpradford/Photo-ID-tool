"use client";

import { useState, useEffect, useRef } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Species } from "@/lib/types";
import { Search } from "lucide-react";

interface Props {
  onSelect: (species: Species) => void;
  selectedTaxon?: string | null;
}

export default function SpeciesSearch({ onSelect, selectedTaxon }: Props) {
  const supabase = createClient();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Species[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!query.trim()) {
      setResults([]);
      setOpen(false);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      const term = query.trim().toLowerCase();
      const { data } = await supabase
        .from("species")
        .select("*")
        .or(
          `taxon_name.ilike.%${term}%,common_name.ilike.%${term}%,family.ilike.%${term}%,genus.ilike.%${term}%`
        )
        .limit(20);
      setResults((data ?? []) as Species[]);
      setOpen(true);
      setLoading(false);
    }, 250);
  }, [query]);

  function handleSelect(species: Species) {
    setQuery(species.taxon_name);
    setOpen(false);
    onSelect(species);
  }

  return (
    <div className="relative">
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => results.length > 0 && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder={selectedTaxon ?? "Search species…"}
          className="w-full bg-input border border-border rounded px-3 py-2 pl-8 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
        />
        {loading && (
          <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
            …
          </span>
        )}
      </div>

      {open && results.length > 0 && (
        <ul className="absolute z-50 mt-1 w-full bg-secondary border border-border rounded shadow-lg max-h-60 overflow-y-auto">
          {results.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                onMouseDown={() => handleSelect(s)}
                className="w-full text-left px-3 py-2 text-sm hover:bg-accent transition-colors"
              >
                <span className="font-medium italic">{s.taxon_name}</span>
                {s.common_name && (
                  <span className="text-muted-foreground ml-2">
                    — {s.common_name}
                  </span>
                )}
                {s.family && (
                  <span className="text-muted-foreground text-xs block">
                    {s.family}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}

      {open && query.trim() && results.length === 0 && !loading && (
        <div className="absolute z-50 mt-1 w-full bg-secondary border border-border rounded px-3 py-2 text-sm text-muted-foreground">
          No species found for &quot;{query}&quot;
        </div>
      )}
    </div>
  );
}
