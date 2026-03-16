"use client";

import {
  Area,
  AreaChart,
  ResponsiveContainer,
  type TooltipContentProps,
  Tooltip,
  YAxis,
} from "recharts";
import { useId } from "react";

import { cn } from "@/lib/utils";

type MetricSparklineProps = {
  values: number[];
  bucket?: string;
  labels?: string[];
  className?: string;
};

const buildSparkData = (values: number[]) =>
  values.map((value, index) => ({
    index,
    value,
  }));

const formatSparkValue = (value: number) => {
  if (!Number.isFinite(value)) {
    return "--";
  }
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded) ? rounded.toString() : rounded.toFixed(1);
};

const SparklineTooltip = ({
  active,
  payload,
  bucket,
  labels,
}: TooltipContentProps<number, string> & {
  bucket?: string;
  labels?: string[];
}) => {
  if (!active || !payload?.length) {
    return null;
  }
  const entry = payload[0];
  const rawValue = entry?.value;
  if (typeof rawValue !== "number") {
    return null;
  }
  const dayIndex =
    typeof entry.payload?.index === "number" ? entry.payload.index + 1 : null;
  const labelIndex =
    typeof entry.payload?.index === "number" ? entry.payload.index : null;
  const resolvedLabel = labelIndex !== null ? labels?.[labelIndex] : undefined;
  const label =
    bucket === "week"
      ? "Week"
      : bucket === "month"
        ? "Month"
        : bucket === "year"
          ? "Year"
          : "Day";
  const prefix = resolvedLabel ?? (dayIndex ? `${label} ${dayIndex}` : "");
  return (
    <div className="rounded-md border border-gray-200 bg-white px-2 py-1 text-xs font-medium text-gray-700 shadow-sm">
      {prefix ? `${prefix}: ` : ""}
      {formatSparkValue(rawValue)}
    </div>
  );
};

export default function MetricSparkline({
  values,
  bucket,
  labels,
  className,
}: MetricSparklineProps) {
  const gradientId = useId();

  if (!values.length) {
    return null;
  }

  const data = buildSparkData(values);
  const strokeColor = "#60a5fa";
  const fillColor = "#bfdbfe";

  return (
    <div className={cn("h-8 w-full", className)}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={data}
          margin={{ top: 4, right: 0, bottom: 0, left: 0 }}
        >
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={fillColor} stopOpacity={0.35} />
              <stop offset="100%" stopColor={fillColor} stopOpacity={0} />
            </linearGradient>
          </defs>
          <YAxis hide domain={["dataMin", "dataMax"]} />
          <Tooltip<number, string>
            cursor={false}
            content={(props) => (
              <SparklineTooltip {...props} bucket={bucket} labels={labels} />
            )}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke={strokeColor}
            strokeWidth={1.75}
            fill={`url(#${gradientId})`}
            fillOpacity={1}
            dot={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
