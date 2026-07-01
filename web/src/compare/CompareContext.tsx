import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

const KEY = "ebc.compare";
export const MAX_COMPARE = 4;

interface CompareState {
  ids: string[];
  has: (id: string) => boolean;
  toggle: (id: string) => void;
  remove: (id: string) => void;
  reorder: (fromId: string, toId: string) => void;
  clear: () => void;
  isFull: boolean;
}

const CompareContext = createContext<CompareState | null>(null);

export function CompareProvider({ children }: { children: ReactNode }) {
  const [ids, setIds] = useState<string[]>(() => {
    try {
      const v = JSON.parse(localStorage.getItem(KEY) || "[]");
      return Array.isArray(v) ? v.slice(0, MAX_COMPARE) : [];
    } catch {
      return [];
    }
  });

  useEffect(() => {
    localStorage.setItem(KEY, JSON.stringify(ids));
  }, [ids]);

  const toggle = useCallback((id: string) => {
    setIds((cur) =>
      cur.includes(id)
        ? cur.filter((x) => x !== id)
        : cur.length >= MAX_COMPARE
          ? cur
          : [...cur, id],
    );
  }, []);

  const remove = useCallback((id: string) => setIds((cur) => cur.filter((x) => x !== id)), []);
  const clear = useCallback(() => setIds([]), []);

  // Move `fromId` to `toId`'s slot: after target when dragging down, before it when dragging up.
  const reorder = useCallback((fromId: string, toId: string) => {
    setIds((cur) => {
      if (fromId === toId) return cur;
      const from = cur.indexOf(fromId), to = cur.indexOf(toId);
      if (from < 0 || to < 0) return cur;
      const next = cur.filter((x) => x !== fromId);
      next.splice(next.indexOf(toId) + (from < to ? 1 : 0), 0, fromId);
      return next;
    });
  }, []);

  const value = useMemo<CompareState>(
    () => ({
      ids,
      has: (id) => ids.includes(id),
      toggle,
      remove,
      reorder,
      clear,
      isFull: ids.length >= MAX_COMPARE,
    }),
    [ids, toggle, remove, reorder, clear],
  );

  return <CompareContext.Provider value={value}>{children}</CompareContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useCompare(): CompareState {
  const ctx = useContext(CompareContext);
  if (!ctx) throw new Error("useCompare must be used within CompareProvider");
  return ctx;
}
