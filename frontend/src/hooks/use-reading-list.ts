"use client";

import { useCallback, useEffect, useState } from "react";

export type ReadingItemType = "paper" | "book" | "article" | "course";
export type ReadingItemStatus = "to-read" | "reading" | "completed";

export type ReadingItem = {
  id: string;
  title: string;
  url?: string;
  type: ReadingItemType;
  status: ReadingItemStatus;
  notes?: string;
  addedAt: string;
  completedAt?: string;
};

const STORAGE_KEY = "openclaw-reading-list";

function loadItems(): ReadingItem[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as ReadingItem[]) : [];
  } catch {
    return [];
  }
}

function saveItems(items: ReadingItem[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  } catch {
    // storage full or unavailable
  }
}

export function useReadingList() {
  const [items, setItems] = useState<ReadingItem[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setItems(loadItems());
    setLoaded(true);
  }, []);

  useEffect(() => {
    if (loaded) saveItems(items);
  }, [items, loaded]);

  const addItem = useCallback(
    (item: Omit<ReadingItem, "id" | "addedAt">) => {
      const newItem: ReadingItem = {
        ...item,
        id: crypto.randomUUID(),
        addedAt: new Date().toISOString(),
      };
      setItems((prev) => [newItem, ...prev]);
    },
    [],
  );

  const updateItem = useCallback(
    (id: string, updates: Partial<Omit<ReadingItem, "id" | "addedAt">>) => {
      setItems((prev) =>
        prev.map((item) => {
          if (item.id !== id) return item;
          const updated = { ...item, ...updates };
          if (updates.status === "completed" && !item.completedAt) {
            updated.completedAt = new Date().toISOString();
          }
          if (updates.status && updates.status !== "completed") {
            updated.completedAt = undefined;
          }
          return updated;
        }),
      );
    },
    [],
  );

  const removeItem = useCallback((id: string) => {
    setItems((prev) => prev.filter((item) => item.id !== id));
  }, []);

  return { items, loaded, addItem, updateItem, removeItem };
}
