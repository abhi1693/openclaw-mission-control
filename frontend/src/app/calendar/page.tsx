"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Calendar as CalendarIcon, ChevronLeft, ChevronRight, Clock } from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { useListBoardsApiV1BoardsGet } from "@/api/generated/boards/boards";
import { useListTasksApiV1BoardsBoardIdTasksGet } from "@/api/generated/tasks/tasks";
import type { TaskRead } from "@/api/generated/model/taskRead";
import { cn } from "@/lib/utils";

function getDaysInMonth(year: number, month: number) {
  return new Date(year, month + 1, 0).getDate();
}
function getFirstDayOfMonth(year: number, month: number) {
  return new Date(year, month, 1).getDay();
}

const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
const DAYS = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];

const STATUS_DOT: Record<string, string> = {
  inbox: "bg-slate-400",
  in_progress: "bg-violet-500",
  review: "bg-indigo-500",
  done: "bg-emerald-500",
};

const PRIORITY_BORDER: Record<string, string> = {
  high: "border-l-rose-400",
  medium: "border-l-amber-400",
  low: "border-l-blue-300",
};

type BoardTask = TaskRead & { boardName: string; boardId: string };

function useAllTasks(isSignedIn: boolean | null | undefined) {
  const boardsQuery = useListBoardsApiV1BoardsGet({
    query: { enabled: Boolean(isSignedIn) },
  });
  const boards = boardsQuery.data?.data?.items ?? [];

  // Fetch tasks for each board (up to 8 boards for perf)
  const boardIds = boards.slice(0, 8).map((b: any) => b.id as string);
  const boardNameMap = new Map(boards.map((b: any) => [b.id, b.name]));

  const taskQueries = boardIds.map((boardId) =>
    // eslint-disable-next-line react-hooks/rules-of-hooks
    useListTasksApiV1BoardsBoardIdTasksGet(boardId, {}, {
      query: { enabled: Boolean(isSignedIn) && Boolean(boardId) },
    }),
  );

  const allTasks: BoardTask[] = useMemo(() => {
    const tasks: BoardTask[] = [];
    taskQueries.forEach((q, i) => {
      const items = q.data?.data?.items ?? [];
      items.forEach((t: any) => {
        tasks.push({
          ...t,
          boardName: boardNameMap.get(boardIds[i]) ?? "Board",
          boardId: boardIds[i],
        });
      });
    });
    return tasks;
  }, [taskQueries.map((q) => q.dataUpdatedAt).join(",")]);

  return { allTasks, isLoading: boardsQuery.isLoading };
}

export default function CalendarPage() {
  const { isSignedIn } = useAuth();
  useOrganizationMembership(isSignedIn);
  const [currentDate, setCurrentDate] = useState(new Date());
  const year = currentDate.getFullYear();
  const month = currentDate.getMonth();

  const { allTasks, isLoading } = useAllTasks(isSignedIn);

  // Index tasks by date string (YYYY-MM-DD)
  const tasksByDate = useMemo(() => {
    const map = new Map<string, BoardTask[]>();
    allTasks.forEach((t) => {
      if (!t.due_at) return;
      const d = new Date(t.due_at);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      const arr = map.get(key) ?? [];
      arr.push(t);
      map.set(key, arr);
    });
    return map;
  }, [allTasks]);

  // Upcoming tasks sorted by due date
  const upcoming = useMemo(() => {
    const now = new Date();
    return allTasks
      .filter((t) => t.due_at && new Date(t.due_at) >= now && t.status !== "done")
      .sort((a, b) => new Date(a.due_at!).getTime() - new Date(b.due_at!).getTime())
      .slice(0, 10);
  }, [allTasks]);

  // Overdue tasks
  const overdue = useMemo(() => {
    const now = new Date();
    return allTasks
      .filter((t) => t.due_at && new Date(t.due_at) < now && t.status !== "done")
      .sort((a, b) => new Date(a.due_at!).getTime() - new Date(b.due_at!).getTime());
  }, [allTasks]);

  const daysInMonth = getDaysInMonth(year, month);
  const firstDay = getFirstDayOfMonth(year, month);
  const today = new Date();
  const isToday = (day: number) =>
    today.getFullYear() === year && today.getMonth() === month && today.getDate() === day;

  const prevMonth = () => setCurrentDate(new Date(year, month - 1, 1));
  const nextMonth = () => setCurrentDate(new Date(year, month + 1, 1));
  const goToToday = () => setCurrentDate(new Date());

  const calendarDays: (number | null)[] = [];
  for (let i = 0; i < firstDay; i++) calendarDays.push(null);
  for (let d = 1; d <= daysInMonth; d++) calendarDays.push(d);
  while (calendarDays.length % 7 !== 0) calendarDays.push(null);

  function getDateKey(day: number) {
    return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  }

  return (
    <DashboardPageLayout
      signedOut={{ message: "Sign in to view your calendar.", forceRedirectUrl: "/calendar" }}
      title="Calendar"
      description="Task deadlines and scheduled work at a glance."
      headerActions={
        <div className="flex items-center gap-2">
          {overdue.length > 0 ? (
            <span className="rounded-full bg-rose-100 px-2.5 py-1 text-xs font-semibold text-rose-700">
              {overdue.length} overdue
            </span>
          ) : null}
          <button onClick={goToToday} className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 transition">
            Today
          </button>
        </div>
      }
    >
      <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <button onClick={prevMonth} className="rounded-lg p-2 hover:bg-slate-50 transition">
            <ChevronLeft className="h-4 w-4 text-slate-500" />
          </button>
          <h2 className="text-lg font-semibold text-slate-900">{MONTHS[month]} {year}</h2>
          <button onClick={nextMonth} className="rounded-lg p-2 hover:bg-slate-50 transition">
            <ChevronRight className="h-4 w-4 text-slate-500" />
          </button>
        </div>

        <div className="grid grid-cols-7 border-b border-slate-100">
          {DAYS.map((d) => (
            <div key={d} className="px-2 py-2 text-center text-[11px] font-semibold uppercase tracking-wider text-slate-400">{d}</div>
          ))}
        </div>

        <div className="grid grid-cols-7">
          {calendarDays.map((day, idx) => {
            const events = day ? tasksByDate.get(getDateKey(day)) ?? [] : [];
            const isPast = day !== null && new Date(year, month, day) < new Date(today.getFullYear(), today.getMonth(), today.getDate());
            return (
              <div key={idx} className={cn(
                "min-h-[90px] border-b border-r border-slate-100 p-1.5",
                day === null && "bg-slate-50/50",
              )}>
                {day !== null ? (
                  <>
                    <span className={cn(
                      "inline-flex h-6 w-6 items-center justify-center rounded-full text-xs",
                      isToday(day) ? "bg-blue-600 text-white font-bold" : isPast ? "text-slate-400" : "text-slate-700",
                    )}>{day}</span>
                    <div className="mt-0.5 space-y-0.5">
                      {events.slice(0, 3).map((t) => (
                        <Link key={t.id} href={`/boards/${t.boardId}`} className={cn(
                          "block truncate rounded border-l-2 bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-700 hover:bg-blue-50 transition",
                          PRIORITY_BORDER[t.priority ?? "medium"] ?? "border-l-slate-300",
                        )}>
                          <span className={cn("mr-1 inline-block h-1.5 w-1.5 rounded-full", STATUS_DOT[t.status ?? "inbox"])} />
                          {t.title}
                        </Link>
                      ))}
                      {events.length > 3 ? (
                        <span className="text-[10px] text-slate-400 pl-1">+{events.length - 3} more</span>
                      ) : null}
                    </div>
                  </>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>

      {/* Upcoming deadlines */}
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Clock className="h-4 w-4 text-blue-500" /> Upcoming Deadlines
          </h3>
          {upcoming.length > 0 ? (
            <div className="mt-3 space-y-2">
              {upcoming.map((t) => (
                <Link key={t.id} href={`/boards/${t.boardId}`} className="flex items-center justify-between rounded-lg border border-slate-100 px-3 py-2 hover:bg-slate-50 transition">
                  <div className="min-w-0">
                    <p className="truncate text-sm text-slate-800">{t.title}</p>
                    <p className="text-[11px] text-slate-400">{t.boardName}</p>
                  </div>
                  <span className="shrink-0 text-xs text-slate-500">
                    {new Date(t.due_at!).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                  </span>
                </Link>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-xs text-slate-400">No upcoming deadlines. Set due dates on tasks to track them here.</p>
          )}
        </div>

        {overdue.length > 0 ? (
          <div className="rounded-xl border border-rose-200 bg-rose-50/50 p-5 shadow-sm">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-rose-800">
              <CalendarIcon className="h-4 w-4 text-rose-500" /> Overdue
            </h3>
            <div className="mt-3 space-y-2">
              {overdue.map((t) => (
                <Link key={t.id} href={`/boards/${t.boardId}`} className="flex items-center justify-between rounded-lg border border-rose-100 bg-white px-3 py-2 hover:bg-rose-50 transition">
                  <div className="min-w-0">
                    <p className="truncate text-sm text-slate-800">{t.title}</p>
                    <p className="text-[11px] text-slate-400">{t.boardName}</p>
                  </div>
                  <span className="shrink-0 text-xs text-rose-600 font-medium">
                    {new Date(t.due_at!).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                  </span>
                </Link>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </DashboardPageLayout>
  );
}
