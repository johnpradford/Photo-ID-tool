import { createClient } from "@/lib/supabase/server";
import { redirect } from "next/navigation";
import Link from "next/link";
import PhotoCard from "@/components/PhotoCard";
import type { Photo } from "@/lib/types";
import SignOutButton from "@/components/SignOutButton";

export default async function DashboardPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  const { data: photos } = await supabase
    .from("photos")
    .select("*")
    .eq("user_id", user.id)
    .order("uploaded_at", { ascending: false });

  const allPhotos = (photos ?? []) as Photo[];
  const pending = allPhotos.filter((p) => p.status === "pending").length;
  const assigned = allPhotos.filter((p) => p.status !== "pending").length;

  return (
    <div className="min-h-screen flex flex-col">
      {/* Nav */}
      <nav className="border-b border-border px-6 py-3 flex items-center justify-between">
        <h1 className="font-semibold text-foreground">Fauna Photo-ID</h1>
        <div className="flex items-center gap-4">
          <Link
            href="/upload"
            className="bg-primary text-primary-foreground rounded px-3 py-1.5 text-sm hover:opacity-90"
          >
            Upload Photos
          </Link>
          <Link href="/results" className="text-sm text-muted-foreground hover:text-foreground">
            Export CSV
          </Link>
          <SignOutButton />
        </div>
      </nav>

      {/* Stats bar */}
      <div className="border-b border-border px-6 py-3 flex gap-6 text-sm">
        <span>
          <span className="text-muted-foreground">Total: </span>
          <span className="font-medium">{allPhotos.length}</span>
        </span>
        <span>
          <span className="text-muted-foreground">Pending: </span>
          <span className="font-medium text-yellow-400">{pending}</span>
        </span>
        <span>
          <span className="text-muted-foreground">Done: </span>
          <span className="font-medium text-green-400">{assigned}</span>
        </span>
      </div>

      {/* Grid */}
      <main className="flex-1 p-6">
        {allPhotos.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-center">
            <p className="text-muted-foreground mb-4">No photos uploaded yet.</p>
            <Link
              href="/upload"
              className="bg-primary text-primary-foreground rounded px-4 py-2 text-sm hover:opacity-90"
            >
              Upload your first batch
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
            {allPhotos.map((photo) => (
              <PhotoCard key={photo.id} photo={photo} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
