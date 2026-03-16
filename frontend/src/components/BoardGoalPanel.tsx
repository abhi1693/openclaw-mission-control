"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { parseApiDatetime } from "@/lib/datetime";
import { cn } from "@/lib/utils";

type BoardGoal = {
  board_type?: string;
  objective?: string | null;
  success_metrics?: Record<string, unknown> | null;
  target_date?: string | null;
  goal_confirmed?: boolean;
};

type BoardGoalPanelProps = {
  board?: BoardGoal | null;
  onStartOnboarding?: () => void;
  onEdit?: () => void;
};

const formatTargetDate = (value?: string | null) => {
  if (!value) return "—";
  const date = parseApiDatetime(value);
  if (!date) return value;
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
};

export function BoardGoalPanel({
  board,
  onStartOnboarding,
  onEdit,
}: BoardGoalPanelProps) {
  const metricsEntries = (() => {
    if (!board?.success_metrics) return [];
    if (Array.isArray(board.success_metrics)) {
      return board.success_metrics.map((value, index) => [
        `Metric ${index + 1}`,
        value,
      ]);
    }
    if (typeof board.success_metrics === "object") {
      return Object.entries(board.success_metrics);
    }
    return [["Metric", board.success_metrics]];
  })();

  const isGoalBoard = board?.board_type !== "general";
  const isConfirmed = Boolean(board?.goal_confirmed);

  return (
    <Card>
      <CardHeader className="flex flex-col gap-4 border-b border-[color:var(--border)] pb-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-muted">
              Board goal
            </p>
            <p className="mt-1 text-lg font-semibold text-strong">
              {board ? "Mission overview" : "Loading board goal"}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {board ? (
              <>
                <Badge variant={isGoalBoard ? "accent" : "outline"}>
                  {isGoalBoard ? "Goal board" : "General board"}
                </Badge>
                {isGoalBoard ? (
                  <Badge variant={isConfirmed ? "success" : "warning"}>
                    {isConfirmed ? "Confirmed" : "Needs confirmation"}
                  </Badge>
                ) : null}
              </>
            ) : null}
          </div>
        </div>
        {board ? (
          <p className="text-sm text-muted">
            {isGoalBoard
              ? "Track progress against the board objective and keep agents aligned."
              : "General boards focus on tasks without formal success metrics."}
          </p>
        ) : (
          <div className="h-4 w-32 animate-pulse rounded-full bg-[color:var(--surface-muted)]" />
        )}
      </CardHeader>
      <CardContent className="space-y-4 pt-5">
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted">
            Objective
          </p>
          <p
            className={cn(
              "text-sm",
              board?.objective ? "text-strong" : "text-muted",
            )}
          >
            {board?.objective ||
              (isGoalBoard ? "No objective yet." : "Not required.")}
          </p>
        </div>
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted">
            Success metrics
          </p>
          {metricsEntries.length > 0 ? (
            <ul className="space-y-1 text-sm text-strong">
              {metricsEntries.map(([key, value]) => (
                <li key={`${key}`} className="flex gap-2">
                  <span className="font-medium text-strong">{key}:</span>
                  <span className="text-muted">{String(value)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">
              {isGoalBoard ? "No metrics defined yet." : "Not required."}
            </p>
          )}
        </div>
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted">
            Target date
          </p>
          <p className="text-sm text-strong">
            {formatTargetDate(board?.target_date)}
          </p>
        </div>
        {onStartOnboarding || onEdit ? (
          <div className="flex flex-wrap gap-2">
            {onStartOnboarding && isGoalBoard && !isConfirmed ? (
              <Button variant="primary" onClick={onStartOnboarding}>
                Start onboarding
              </Button>
            ) : null}
            {onEdit ? (
              <Button variant="secondary" onClick={onEdit}>
                Edit board
              </Button>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

export default BoardGoalPanel;
