import { createClient } from "@/lib/supabase/server";
import { redirect, notFound } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, ArrowRight } from "lucide-react";
import PhotoViewer from "@/components/PhotoViewer";
import ClassifyPanel from "@/components/ClassifyPanel";
import type { Photo } from "@/lib/types";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function ReviewPage({ params }: Props) {
  const { id } = await params;
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  // Fetch the photo being reviewed
  const { data: photo } = await supabase
    .from("photos")
    .select("*")
    .eq("id", id)
    .eq("user_id", user.id)
    .single() as { data: Photo | null };

  if (!photo) notFound();

  // Fetch prev/next photo IDs for navigation
  const { data: allPhotos } = await supabase
    .from("photos")
    .select("id")
    .eq("user_id", user.id)
    .order("uploaded_at", { ascending: true });

  const photoList: { id: string }[] = allPhotos ?? [];
  const currentIdx = photoList.findIndex((p) => p.id === id);
  const prevId = currentIdx > 0 ? photoList[currentIdx - 1].id : null;
  const nextId =
    currentIdx < photoList.length - 1 ? photoList[currentIdx + 1].id : null;

  // Signed URL for the image (1 hour expiry)
  const { data: signedData } = await supabase.storage
    .from("photos")
    .createSignedUrl(photo.storage_path, 3600);

  const imageUrl = signedData?.signedUrl ?? null;

  // Existing assignment (if any)
  const { data: existing } = await supabase
    .from("assignments")
    .select("*")
    .eq("photo_id", id)
    .eq("user_id", user.id)
    .maybeSingle() as { data: import("@/lib/types").Assignment | null };

  return (
    <div className="min-h-screen flex flex-col">
      {/* Nav */}
      <nav className="border-b border-border px-6 py-3 flex items-center gap-4">
        <Link href="/dashboard" className="text-muted-foreground hover:text-foreground">
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <span className="text-sm text-muted-foreground truncate flex-1">
          {photo.filename}
        </span>
        <span className="text-xs text-muted-foreground">
          {currentIdx + 1} / {photoList.length}
        </span>
        <div className="flex gap-2">
          {prevId && (
            <Link
              href={`/review/${prevId}`}
              className="text-muted-foreground hover:text-foreground"
              title="Previous"
            >
              <ArrowLeft className="w-4 h-4" />
            </Link>
          )}
          {nextId && (
            <Link
              href={`/review/${nextId}`}
              className="text-primary hover:opacity-80"
              title="Next"
            >
              <ArrowRight className="w-4 h-4" />
            </Link>
          )}
        </div>
      </nav>

      {/* Body: image + classify panel side by side */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: image viewer */}
        <div className="flex-1 relative bg-black">
          <PhotoViewer imageUrl={imageUrl} filename={photo.filename} />
        </div>

        {/* Right: classification panel */}
        <div className="w-80 border-l border-border overflow-y-auto">
          <ClassifyPanel
            photoId={photo.id}
            prevId={prevId}
            nextId={nextId}
            existing={existing}
          />
        </div>
      </div>
    </div>
  );
}
