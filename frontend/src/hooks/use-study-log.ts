"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

export type StudyCategory =
  | "studying"
  | "reading"
  | "project-work"
  | "coding"
  | "writing";

export type StudyEntry = {
  id: string;
  date: string; // YYYY-MM-DD
  hours: number;
  category: StudyCategory;
  topic?: string;
  notes?: string;
};

const STORAGE_KEY = "openclaw-study-log";

const LEARNING_CATEGORIES: StudyCategory[] = ["studying", "reading", "writing"];
const PROJECT_CATEGORIES: StudyCategory[] = ["project-work", "coding"];

function loadEntries(): StudyEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as StudyEntry[]) : [];
  } catch {
    return [];
  }
}

function saveEntries(entries: StudyEntry[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // storage full or unavailable
  }
}

function getWeekStart(date: Date): string {
  const d = new Date(date);
  const day = d.getDay();
  d.setDate(d.getDate() - day);
  return d.toISOString().slice(0, 10);
}

function todayString(): string {
  return new Date().toISOString().slice(0, 10);
}

export type BalanceLevel = "balanced" | "project-heavy" | "danger";

export function useStudyLog() {
  const [entries, setEntries] = useState<StudyEntry[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setEntries(loadEntries());
    setLoaded(true);
  }, []);

  useEffect(() => {
    if (loaded) saveEntries(entries);
  }, [entries, loaded]);

  const addEntry = useCallback(
    (entry: Omit<StudyEntry, "id">) => {
      const newEntry: StudyEntry = {
        ...entry,
        id: crypto.randomUUID(),
      };
      setEntries((prev) => [newEntry, ...prev]);
    },
    [],
  );

  const updateEntry = useCallback(
    (id: string, updates: Partial<Omit<StudyEntry, "id">>) => {
      setEntries((prev) =>
        prev.map((entry) =>
          entry.id === id ? { ...entry, ...updates } : entry,
        ),
      );
    },
    [],
  );

  const removeEntry = useCallback((id: string) => {
    setEntries((prev) => prev.filter((entry) => entry.id !== id));
  }, []);

  const weekStart = getWeekStart(new Date());

  const weekEntries = useMemo(
    () => entries.filter((e) => e.date >= weekStart),
    [entries, weekStart],
  );

  const weekStats = useMemo(() => {
    let learningHours = 0;
    let projectHours = 0;
    const daysSet = new Set<string>();

    for (const entry of weekEntries) {
      daysSet.add(entry.date);
      if (LEARNING_CATEGORIES.includes(entry.category)) {
        learningHours += entry.hours;
      } else if (PROJECT_CATEGORIES.includes(entry.category)) {
        projectHours += entry.hours;
      }
    }

    const totalHours = learningHours + projectHours;
    const learningPct = totalHours > 0 ? (learningHours / totalHours) * 100 : 50;

    let balanceLevel: BalanceLevel = "balanced";
    if (totalHours > 0) {
      if (learningPct < 20) balanceLevel = "danger";
      else if (learningPct < 40) balanceLevel = "project-heavy";
    }

    let balanceLabel = "Balanced";
    if (balanceLevel === "project-heavy") balanceLabel = "Project-heavy";
    else if (balanceLevel === "danger") balanceLabel = "Way too much project time!";

    return {
      totalHours,
      learningHours,
      projectHours,
      learningPct,
      daysLogged: daysSet.size,
      balanceLevel,
      balanceLabel,
    };
  }, [weekEntries]);

  return {
    entries,
    loaded,
    addEntry,
    updateEntry,
    removeEntry,
    weekStats,
    todayString,
  };
}
