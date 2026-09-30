import { RefObject, useEffect, useRef } from "react";
import type { MapRef } from "react-map-gl/mapbox";
import { t } from "@lingui/core/macro";

interface MapCompassProps {
  mapRef: RefObject<MapRef | null>;
  /** Flips to true once the map has loaded, so we can subscribe to it. */
  ready: boolean;
}

/** Compass needle that follows the map's bearing; click to face north and flatten. */
export function MapCompass({ mapRef, ready }: MapCompassProps) {
  const needleRef = useRef<SVGSVGElement>(null);
  // Mapbox reports bearing wrapped to [-180, 180]. Rotating the needle to the
  // raw value makes the CSS transition swing the long way round whenever the
  // map turns across south (e.g. 170° -> -170° spins back 340°). Keep an
  // unwrapped angle and always step it by the shortest turn instead.
  const angleRef = useRef(0);

  useEffect(() => {
    const map = mapRef.current?.getMap();
    if (!ready || !map) return;

    // Written straight to the DOM: rotating the map fires this every frame,
    // and nothing else needs to re-render for it.
    const update = () => {
      const target = -map.getBearing();
      const delta = ((((target - angleRef.current) % 360) + 540) % 360) - 180;
      angleRef.current += delta;
      if (needleRef.current) {
        needleRef.current.style.transform = `rotate(${angleRef.current}deg)`;
      }
    };
    update();
    map.on("rotate", update);
    return () => {
      map.off("rotate", update);
    };
  }, [mapRef, ready]);

  return (
    <button
      type="button"
      onClick={() => mapRef.current?.getMap().easeTo({ bearing: 0, pitch: 0, duration: 400 })}
      title={t`Reset View (North)`}
      aria-label={t`Reset View (North)`}
      className="flex items-center justify-center w-7 h-7 rounded-lg text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-white/5 transition-colors"
    >
      {/* Compass needle: red half points north. */}
      <svg
        ref={needleRef}
        viewBox="0 0 16 16"
        aria-hidden
        className="w-4 h-4 transition-transform duration-200 ease-out"
      >
        <path d="M8 1.5 10.5 8h-5z" className="fill-red-500" />
        <path d="M8 14.5 5.5 8h5z" className="fill-zinc-400 dark:fill-zinc-500" />
      </svg>
    </button>
  );
}
