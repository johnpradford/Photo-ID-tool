"use client";

import { useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Upload, ArrowLeft, CheckCircle, XCircle } from "lucide-react";

interface FileState {
  file: File;
  status: "pending" | "uploading" | "done" | "error";
  error?: string;
}

const ALLOWED_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/tiff",
  "image/webp",
]);

export default function UploadPage() {
  const router = useRouter();
  const supabase = createClient();
  const [files, setFiles] = useState<FileState[]>([]);
  const [uploading, setUploading] = useState(false);

  const addFiles = useCallback((newFiles: FileList | null) => {
    if (!newFiles) return;
    const filtered = Array.from(newFiles).filter((f) =>
      ALLOWED_TYPES.has(f.type)
    );
    setFiles((prev) => [
      ...prev,
      ...filtered.map((f) => ({ file: f, status: "pending" as const })),
    ]);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      addFiles(e.dataTransfer.files);
    },
    [addFiles]
  );

  async function handleUpload() {
    setUploading(true);
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) {
      router.push("/login");
      return;
    }

    let firstId: string | null = null;

    for (let i = 0; i < files.length; i++) {
      if (files[i].status === "done") continue;
      setFiles((prev) =>
        prev.map((f, idx) =>
          idx === i ? { ...f, status: "uploading" } : f
        )
      );

      const { file } = files[i];
      const storagePath = `${user.id}/${Date.now()}_${file.name}`;

      try {
        const { error: storageError } = await supabase.storage
          .from("photos")
          .upload(storagePath, file, { upsert: false });

        if (storageError) throw storageError;

        const { data: photoRow, error: dbError } = await supabase
          .from("photos")
          .insert({
            user_id: user.id,
            storage_path: storagePath,
            filename: file.name,
            status: "pending",
          })
          .select("id")
          .single();

        if (dbError) throw dbError;
        if (!firstId) firstId = (photoRow as { id: string }).id;

        setFiles((prev) =>
          prev.map((f, idx) =>
            idx === i ? { ...f, status: "done" } : f
          )
        );
      } catch (err) {
        const message = err instanceof Error ? err.message : "Upload failed";
        setFiles((prev) =>
          prev.map((f, idx) =>
            idx === i ? { ...f, status: "error", error: message } : f
          )
        );
      }
    }

    setUploading(false);
    if (firstId) {
      router.push(`/review/${firstId}`);
    }
  }

  const allDone = files.length > 0 && files.every((f) => f.status === "done");
  const hasPending = files.some((f) => f.status === "pending");

  return (
    <div className="min-h-screen flex flex-col">
      <nav className="border-b border-border px-6 py-3 flex items-center gap-4">
        <Link href="/dashboard" className="text-muted-foreground hover:text-foreground">
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <h1 className="font-semibold">Upload Photos</h1>
      </nav>

      <main className="flex-1 p-6 max-w-2xl mx-auto w-full">
        {/* Drop zone */}
        <div
          onDrop={handleDrop}
          onDragOver={(e) => e.preventDefault()}
          onClick={() => document.getElementById("file-input")?.click()}
          className="border-2 border-dashed border-border rounded-lg p-12 text-center cursor-pointer hover:border-primary transition-colors"
        >
          <Upload className="w-10 h-10 mx-auto text-muted-foreground mb-3" />
          <p className="text-sm text-muted-foreground">
            Drag &amp; drop photos here, or click to select
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            JPEG, PNG, TIFF, WebP
          </p>
          <input
            id="file-input"
            type="file"
            multiple
            accept="image/jpeg,image/png,image/tiff,image/webp"
            className="hidden"
            onChange={(e) => addFiles(e.target.files)}
          />
        </div>

        {/* File list */}
        {files.length > 0 && (
          <div className="mt-4 space-y-2">
            {files.map((f, i) => (
              <div
                key={i}
                className="flex items-center gap-3 bg-secondary rounded px-3 py-2 text-sm"
              >
                <span className="flex-1 truncate text-foreground">
                  {f.file.name}
                </span>
                <span className="text-muted-foreground text-xs">
                  {(f.file.size / 1024 / 1024).toFixed(1)} MB
                </span>
                {f.status === "uploading" && (
                  <span className="text-yellow-400 text-xs">Uploading…</span>
                )}
                {f.status === "done" && (
                  <CheckCircle className="w-4 h-4 text-green-400 shrink-0" />
                )}
                {f.status === "error" && (
                  <span title={f.error}>
                    <XCircle className="w-4 h-4 text-destructive shrink-0" />
                  </span>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Actions */}
        <div className="mt-6 flex gap-3">
          {hasPending && !uploading && (
            <button
              onClick={handleUpload}
              className="bg-primary text-primary-foreground rounded px-4 py-2 text-sm font-medium hover:opacity-90"
            >
              Upload {files.filter((f) => f.status === "pending").length} photo
              {files.filter((f) => f.status === "pending").length !== 1 ? "s" : ""}
            </button>
          )}
          {uploading && (
            <button disabled className="bg-primary/50 text-primary-foreground rounded px-4 py-2 text-sm font-medium">
              Uploading…
            </button>
          )}
          {allDone && (
            <button
              onClick={() => router.push("/dashboard")}
              className="bg-green-700 text-white rounded px-4 py-2 text-sm font-medium hover:bg-green-600"
            >
              Done — go to dashboard
            </button>
          )}
          {files.length > 0 && !uploading && (
            <button
              onClick={() => setFiles([])}
              className="text-sm text-muted-foreground hover:text-foreground"
            >
              Clear list
            </button>
          )}
        </div>
      </main>
    </div>
  );
}
