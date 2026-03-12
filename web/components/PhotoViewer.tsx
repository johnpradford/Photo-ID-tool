"use client";

import { useState } from "react";
import { ZoomIn, ZoomOut, RotateCcw } from "lucide-react";

interface Props {
  imageUrl: string | null;
  filename: string;
}

export default function PhotoViewer({ imageUrl, filename }: Props) {
  const [zoom, setZoom] = useState(1);

  if (!imageUrl) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        Image unavailable
      </div>
    );
  }

  return (
    <div className="relative w-full h-full flex flex-col">
      {/* Controls */}
      <div className="absolute top-3 right-3 z-10 flex gap-2">
        <button
          onClick={() => setZoom((z) => Math.min(z + 0.25, 4))}
          className="bg-black/60 hover:bg-black/80 text-white rounded p-1.5"
          title="Zoom in"
        >
          <ZoomIn className="w-4 h-4" />
        </button>
        <button
          onClick={() => setZoom((z) => Math.max(z - 0.25, 0.25))}
          className="bg-black/60 hover:bg-black/80 text-white rounded p-1.5"
          title="Zoom out"
        >
          <ZoomOut className="w-4 h-4" />
        </button>
        <button
          onClick={() => setZoom(1)}
          className="bg-black/60 hover:bg-black/80 text-white rounded p-1.5"
          title="Reset zoom"
        >
          <RotateCcw className="w-4 h-4" />
        </button>
      </div>

      {/* Image */}
      <div className="flex-1 overflow-auto flex items-center justify-center">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={imageUrl}
          alt={filename}
          style={{ transform: `scale(${zoom})`, transformOrigin: "center", transition: "transform 0.15s" }}
          className="max-w-none"
          draggable={false}
        />
      </div>

      {/* Zoom indicator */}
      {zoom !== 1 && (
        <div className="absolute bottom-3 left-3 bg-black/60 text-white text-xs rounded px-2 py-1">
          {Math.round(zoom * 100)}%
        </div>
      )}
    </div>
  );
}
