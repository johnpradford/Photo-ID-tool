import { createClient } from "@/lib/supabase/server";
import { redirect } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Download } from "lucide-react";
import CsvDownloadButton from "@/components/CsvDownloadButton";

export default async function ResultsPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  // Join assignments with photos for filename
  const { data: rows } = await supabase
    .from("assignments")
    .select(`
      *,
      photos (filename, uploaded_at)
    `)
    .eq("user_id", user.id)
    .order("assigned_at", { ascending: false });

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const assignments: any[] = rows ?? [];

  return (
    <div className="min-h-screen flex flex-col">
      <nav className="border-b border-border px-6 py-3 flex items-center gap-4">
        <Link href="/dashboard" className="text-muted-foreground hover:text-foreground">
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <h1 className="font-semibold flex-1">Results</h1>
        <CsvDownloadButton assignments={assignments} />
      </nav>

      <main className="flex-1 p-6 overflow-x-auto">
        {assignments.length === 0 ? (
          <div className="text-center py-20 text-muted-foreground">
            No assignments yet. Review some photos first.
          </div>
        ) : (
          <table className="text-sm w-full border-collapse">
            <thead>
              <tr className="border-b border-border text-left text-muted-foreground">
                <th className="py-2 pr-4 font-medium">Filename</th>
                <th className="py-2 pr-4 font-medium">Classification</th>
                <th className="py-2 pr-4 font-medium">Taxon</th>
                <th className="py-2 pr-4 font-medium">Common Name</th>
                <th className="py-2 pr-4 font-medium">Date</th>
                <th className="py-2 pr-4 font-medium">Lat</th>
                <th className="py-2 pr-4 font-medium">Lon</th>
                <th className="py-2 pr-4 font-medium">Abundance</th>
                <th className="py-2 pr-4 font-medium">Notes</th>
              </tr>
            </thead>
            <tbody>
              {assignments.map((a) => (
                <tr
                  key={a.id}
                  className="border-b border-border/50 hover:bg-accent/30"
                >
                  <td className="py-1.5 pr-4 text-muted-foreground text-xs">
                    {a.photos?.filename ?? "—"}
                  </td>
                  <td className="py-1.5 pr-4 capitalize">{a.classification}</td>
                  <td className="py-1.5 pr-4 italic">{a.taxon_name ?? "—"}</td>
                  <td className="py-1.5 pr-4">{a.common_name ?? "—"}</td>
                  <td className="py-1.5 pr-4 text-muted-foreground">
                    {a.date_obs ?? "—"}
                  </td>
                  <td className="py-1.5 pr-4 text-muted-foreground">
                    {a.latitude ?? "—"}
                  </td>
                  <td className="py-1.5 pr-4 text-muted-foreground">
                    {a.longitude ?? "—"}
                  </td>
                  <td className="py-1.5 pr-4">{a.abundance}</td>
                  <td className="py-1.5 pr-4 text-muted-foreground text-xs">
                    {a.notes ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </main>
    </div>
  );
}
