"use client";

import { useMemo, useState } from "react";
import { Calendar as CalendarIcon, ChevronLeft, ChevronRight } from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { useListBoardsApiV1BoardsGet } from "@/api/generated/boards/boards";
import { useListTasksApiV1BoardsBoardIdTasksGet } from "@/api/generated/tasks/tasks";
import { cn } from "@/lib/utils";

function getDaysInMonth(year: number, month: number) {
  return new Date(year, month + 1, 0).getDate();
}

function getFirstDayOfMonth(year: number, month: number) {
  return new Date(year, month, 1).getDay();
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

type TaskEvent = {
  id: string;
  title: string;
  date: string;
  status: string;
  priority: string;
  boardName: string;
};

export default function CalendarPage() {
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);

  const [currentDate, setCurrentDate] = useState(new Date());
  const year = currentDate.getFullYear();
  const month = currentDate.getMonth();

  const boardsQuery = useListBoardsApiV1BoardsGet({
    query: { enabled: Boolean(isSignedIn) },
  });

  const boards = boardsQuery.data?.data?.items ?? [];

  // Collect tasks with due dates from all boards
  const taskEvents = useMemo(() => {
    const events: TaskEvent[] = [];
    // Note: In a real implementation, we'd fetch tasks across all boards
    // For now, this page provides the UI structure
    return events;
  }, []);

  const daysInMonth = getDaysInMonth(year, month);
  const firstDay = getFirstDayOfMonth(year, month);
  const today = new Date();
  const isToday = (day: number) =>
    today.getFullYear() === year && today.getMonth() === month && today.getDate() === day;

  const prevMonth = () => setCurrentDate(new Date(year, month - 1, 1));
  const nextMonth = () => setCurrentDate(new Date(year, month + 1, 1));
  const goToToday = () => setCurrentDate(new Date());

  // Build calendar grid
  const calendarDays: (number | null)[] = [];
  for (let i = 0; i < firstDay; i++) calendarDays.push(null);
  for (let d = 1; d <= daysInMonth; d++) calendarDays.push(d);
  while (calendarDays.length % 7 !== 0) calendarDays.push(null);

  return (
    <DashboardPageLayout
      signedOut={{ message: "Sign in to view your calendar.", forceRedirectUrl: "/calendar" }}
      title="Calendar"
      description="Scheduled tasks, deadlines, and cron jobs at a glance."
      headerActions={
        <div className="flex items-center gap-2">
          <button
            onClick={goToToday}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 transition"
          >
            Today
          </button>
        </div>
      }
    >
      <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
        {/* Month header */}
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <button onClick={prevMonth} className="rounded-lg p-2 hover:bg-slate-50 transition">
            <ChevronLeft className="h-4 w-4 text-slate-500" />
          </button>
          <h2 className="text-lg font-semibold text-slate-900">
            {MONTH_NAMES[month]} {year}
          </h2>
          <button onClick={nextMonth} className="rounded-lg p-2 hover:bg-slate-50 transition">
            <ChevronRight className="h-4 w-4 text-slate-500" />
          </button>
        </div>

        {/* Day names */}
        <div className="grid grid-cols-7 border-b border-slate-100">
          {DAY_NAMES.map((day) => (
            <div key={day} className="px-3 py-2 text-center text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              {day}
            </div>
          ))}
        </div>

        {/* Calendar grid */}
        <div className="grid grid-cols-7">
          {calendarDays.map((day, idx) => (
            <div
              key={idx}
              className={cn(
                "min-h-[100px] border-b border-r border-slate-100 p-2 transition",
                day === null && "bg-slate-50/50",
                day !== null && "hover:bg-blue-50/30 cursor-pointer",
              )}
            >
              {day !== null ? (
                <div>
                  <span
                    className={cn(
                      "inline-flex h-7 w-7 items-center justify-center rounded-full text-sm",
                      isToday(day)
                        ? "bg-blue-600 text-white font-semibold"
                        : "text-slate-700",
                    )}
                  >
                    {day}
                  </span>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </div>

      {/* Upcoming deadlines */}
      <div className="mt-6 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-900">Upcoming Deadlines</h3>
        <p className="mt-1 text-xs text-slate-500">
          Tasks with due dates will appear here. Set due dates on tasks in your boards to populate the calendar.
        </p>
        <div className="mt-4 flex items-center justify-center rounded-lg border border-dashed border-slate-200 py-12">
          <div className="text-center">
            <CalendarIcon className="mx-auto h-8 w-8 text-slate-300" />
            <p className="mt-2 text-sm text-slate-400">No upcoming deadlines</p>
          </div>
        </div>
      </div>
    </DashboardPageLayout>
  );
}
