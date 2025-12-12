import { useEffect, useState } from "react";
import type { MapData } from "../types";
import { loadMapData } from "../utils/loaders";

interface MapDataState {
  loading: boolean;
  error?: string;
  data?: MapData;
}

export function useMapData(): MapDataState {
  const [state, setState] = useState<MapDataState>({ loading: true });

  useEffect(() => {
    let cancelled = false;
    loadMapData()
      .then((data) => {
        if (!cancelled) {
          setState({ loading: false, data });
        }
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setState({ loading: false, error: error.message });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
