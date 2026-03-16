"use client";

import * as React from "react";
import * as RechartsPrimitive from "recharts";
import type { DefaultLegendContentProps, TooltipContentProps } from "recharts";

import { cn } from "@/lib/utils";

const THEMES = { light: "", dark: ".dark" } as const;

export type ChartConfig = {
  [k in string]: {
    label?: React.ReactNode;
    icon?: React.ComponentType;
  } & (
    | { color?: string; theme?: never }
    | { color?: never; theme: Record<keyof typeof THEMES, string> }
  );
};

export type ChartLegendState = {
  hiddenKeys: Set<string>;
  isSeriesHidden: (key: string) => boolean;
  toggleSeries: (key: string) => void;
};

type ChartContextProps = {
  config: ChartConfig;
} & ChartLegendState;

const ChartContext = React.createContext<ChartContextProps | null>(null);

function useChart() {
  const context = React.useContext(ChartContext);

  if (!context) {
    throw new Error("useChart must be used within a <ChartContainer />");
  }

  return context;
}

/**
 * Recharts wrapper that:
 * - Provides a shared `ChartConfig` via context (labels/icons/colors)
 * - Exposes a small legend state (hide/toggle series)
 * - Injects CSS variables (`--color-*`) scoped to this chart instance
 */
function ChartContainer({
  id,
  className,
  children,
  config,
  legend,
  ...props
}: Omit<React.ComponentProps<"div">, "children"> & {
  config: ChartConfig;
  children:
    | React.ComponentProps<
        typeof RechartsPrimitive.ResponsiveContainer
      >["children"]
    | ((state: ChartLegendState) => React.ReactNode);
  legend?: React.ReactNode | ((state: ChartLegendState) => React.ReactNode);
}) {
  const uniqueId = React.useId();
  const chartId = `chart-${id || uniqueId.replace(/:/g, "")}`;
  const [hiddenKeys, setHiddenKeys] = React.useState<Set<string>>(
    () => new Set(),
  );
  const toggleSeries = React.useCallback((key: string) => {
    setHiddenKeys((previous) => {
      const next = new Set(previous);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);
  const isSeriesHidden = React.useCallback(
    (key: string) => hiddenKeys.has(key),
    [hiddenKeys],
  );
  const legendState = React.useMemo(
    () => ({ hiddenKeys, isSeriesHidden, toggleSeries }),
    [hiddenKeys, isSeriesHidden, toggleSeries],
  );
  const resolvedChildren =
    typeof children === "function" ? children(legendState) : children;
  const resolvedLegend =
    typeof legend === "function" ? legend(legendState) : legend;

  return (
    <ChartContext.Provider value={{ config, ...legendState }}>
      <>
        <div
          data-slot="chart"
          data-chart={chartId}
          className={cn(
            "[&_.recharts-cartesian-axis-tick_text]:fill-muted-foreground [&_.recharts-cartesian-grid_line[stroke='#ccc']]:stroke-border/50 [&_.recharts-curve.recharts-tooltip-cursor]:stroke-border [&_.recharts-polar-grid_[stroke='#ccc']]:stroke-border [&_.recharts-radial-bar-background-sector]:fill-muted [&_.recharts-rectangle.recharts-tooltip-cursor]:fill-muted [&_.recharts-reference-line_[stroke='#ccc']]:stroke-border flex aspect-video justify-center text-xs [&_.recharts-dot[stroke='#fff']]:stroke-transparent [&_.recharts-layer]:outline-hidden [&_.recharts-sector]:outline-hidden [&_.recharts-sector[stroke='#fff']]:stroke-transparent [&_.recharts-surface]:outline-hidden",
            className,
          )}
          {...props}
        >
          <ChartStyle id={chartId} config={config} />
          <RechartsPrimitive.ResponsiveContainer>
            {resolvedChildren}
          </RechartsPrimitive.ResponsiveContainer>
        </div>
        {resolvedLegend}
      </>
    </ChartContext.Provider>
  );
}

/**
 * Emits scoped theme-aware CSS variables so Recharts series can use
 * `var(--color-<key>)` without hardcoding colors in every chart.
 */
const ChartStyle = ({ id, config }: { id: string; config: ChartConfig }) => {
  const colorConfig = Object.entries(config).filter(
    ([, config]) => config.theme || config.color,
  );

  if (!colorConfig.length) {
    return null;
  }

  return (
    <style
      dangerouslySetInnerHTML={{
        __html: Object.entries(THEMES)
          .map(
            ([theme, prefix]) => `
${prefix} [data-chart=${id}] {
${colorConfig
  .map(([key, itemConfig]) => {
    const color =
      itemConfig.theme?.[theme as keyof typeof itemConfig.theme] ||
      itemConfig.color;
    return color ? `  --color-${key}: ${color};` : null;
  })
  .join("\n")}
}
`,
          )
          .join("\n"),
      }}
    />
  );
};

const ChartTooltip = RechartsPrimitive.Tooltip;

type ChartTooltipValue = number | string | Array<number | string>;
type ChartTooltipName = number | string;
type ChartTooltipContentProps = Partial<
  TooltipContentProps<ChartTooltipValue, ChartTooltipName>
> &
  React.ComponentProps<"div"> & {
    hideLabel?: boolean;
    hideIndicator?: boolean;
    indicator?: "line" | "dot" | "dashed";
    nameKey?: string;
    labelKey?: string;
  };

function ChartTooltipContent({
  active,
  payload,
  className,
  indicator = "dot",
  hideLabel = false,
  hideIndicator = false,
  label,
  labelFormatter,
  labelClassName,
  formatter,
  color,
  nameKey,
  labelKey,
}: ChartTooltipContentProps) {
  const { config } = useChart();

  const tooltipLabel = React.useMemo(() => {
    if (hideLabel || !payload?.length) {
      return null;
    }

    const [item] = payload;
    const key = `${labelKey || item?.dataKey || item?.name || "value"}`;
    const itemConfig = getPayloadConfigFromPayload(config, item, key);
    const value =
      !labelKey && typeof label === "string"
        ? config[label as keyof typeof config]?.label || label
        : itemConfig?.label;

    if (labelFormatter) {
      return (
        <div className={cn("font-medium", labelClassName)}>
          {labelFormatter(value, payload)}
        </div>
      );
    }

    if (!value) {
      return null;
    }

    return <div className={cn("font-medium", labelClassName)}>{value}</div>;
  }, [
    label,
    labelFormatter,
    payload,
    hideLabel,
    labelClassName,
    config,
    labelKey,
  ]);

  if (!active || !payload?.length) {
    return null;
  }

  const nestLabel = payload.length === 1 && indicator !== "dot";

  return (
    <div
      className={cn(
        "border-border/50 bg-background grid min-w-[8rem] items-start gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs shadow-xl",
        className,
      )}
    >
      {!nestLabel ? tooltipLabel : null}
      <div className="grid gap-1.5">
        {payload
          .filter((item) => item.type !== "none")
          .map((item, index) => {
            const key = `${nameKey || item.name || item.dataKey || "value"}`;
            const itemConfig = getPayloadConfigFromPayload(config, item, key);
            const indicatorColor = color || item.payload.fill || item.color;

            return (
              <div
                key={item.dataKey}
                className={cn(
                  "[&>svg]:text-muted-foreground flex w-full flex-wrap items-stretch gap-2 [&>svg]:h-2.5 [&>svg]:w-2.5",
                  indicator === "dot" && "items-center",
                )}
              >
                {formatter && item?.value !== undefined && item.name ? (
                  formatter(item.value, item.name, item, index, item.payload)
                ) : (
                  <>
                    {itemConfig?.icon ? (
                      <itemConfig.icon />
                    ) : (
                      !hideIndicator && (
                        <div
                          className={cn(
                            "shrink-0 rounded-[2px] border-(--color-border) bg-(--color-bg)",
                            {
                              "h-2.5 w-2.5": indicator === "dot",
                              "w-1": indicator === "line",
                              "w-0 border-[1.5px] border-dashed bg-transparent":
                                indicator === "dashed",
                              "my-0.5": nestLabel && indicator === "dashed",
                            },
                          )}
                          style={
                            {
                              "--color-bg": indicatorColor,
                              "--color-border": indicatorColor,
                            } as React.CSSProperties
                          }
                        />
                      )
                    )}
                    <div
                      className={cn(
                        "flex flex-1 justify-between leading-none",
                        nestLabel ? "items-end" : "items-center",
                      )}
                    >
                      <div className="grid gap-1.5">
                        {nestLabel ? tooltipLabel : null}
                        <span className="text-muted-foreground">
                          {itemConfig?.label || item.name}
                        </span>
                      </div>
                      {item.value && (
                        <span className="text-foreground font-mono font-medium tabular-nums">
                          {item.value.toLocaleString()}
                        </span>
                      )}
                    </div>
                  </>
                )}
              </div>
            );
          })}
      </div>
    </div>
  );
}

function ChartTooltipCard({
  className,
  labelClassName,
  ...props
}: ChartTooltipContentProps) {
  return (
    <ChartTooltipContent
      {...props}
      className={cn(
        "border border-gray-200 bg-white px-3 py-2 text-sm shadow-lg",
        className,
      )}
      labelClassName={cn("text-sm font-semibold text-gray-900", labelClassName)}
    />
  );
}

const ChartLegend = RechartsPrimitive.Legend;

function ChartLegendContent({
  className,
  hideIcon = false,
  payload,
  verticalAlign = "bottom",
  nameKey,
}: React.ComponentProps<"div"> &
  Pick<DefaultLegendContentProps, "payload" | "verticalAlign"> & {
    hideIcon?: boolean;
    nameKey?: string;
  }) {
  const { config, isSeriesHidden, toggleSeries } = useChart();

  if (!payload?.length) {
    return null;
  }

  return (
    <div
      className={cn(
        "flex items-center justify-center gap-4",
        verticalAlign === "top" ? "pb-3" : "pt-3",
        className,
      )}
    >
      {payload
        .filter((item) => item.type !== "none")
        .map((item) => {
          const key = `${nameKey || item.dataKey || "value"}`;
          const itemConfig = getPayloadConfigFromPayload(config, item, key);
          const seriesKey =
            typeof item.dataKey === "string"
              ? item.dataKey
              : typeof item.value === "string"
                ? item.value
                : key;
          const isHidden = isSeriesHidden(seriesKey);
          const indicatorColor =
            item.color ?? itemConfig?.color ?? `var(--color-${seriesKey})`;

          return (
            <button
              key={seriesKey}
              type="button"
              onClick={() => toggleSeries(seriesKey)}
              aria-pressed={!isHidden}
              className={cn(
                "[&>svg]:text-muted-foreground flex items-center gap-1.5 transition-opacity [&>svg]:h-3 [&>svg]:w-3 cursor-pointer",
                isHidden && "opacity-50",
              )}
            >
              {itemConfig?.icon && !hideIcon ? (
                <itemConfig.icon />
              ) : (
                <div
                  className="h-2 w-2 shrink-0 rounded-[2px]"
                  style={{
                    backgroundColor: indicatorColor,
                  }}
                />
              )}
              <span
                className={cn(
                  "text-muted-foreground",
                  isHidden && "line-through text-muted-foreground/70",
                )}
              >
                {itemConfig?.label ?? item.value}
              </span>
            </button>
          );
        })}
    </div>
  );
}

type ChartLegendItemProps = React.ComponentProps<"button"> & {
  seriesKey: string;
  label?: React.ReactNode;
  color?: string;
  icon?: React.ComponentType;
  hideIcon?: boolean;
};

function ChartLegendItem({
  seriesKey,
  label,
  color,
  icon,
  hideIcon = false,
  className,
  onClick,
  ...props
}: ChartLegendItemProps) {
  const { config, isSeriesHidden, toggleSeries } = useChart();
  const itemConfig = config[seriesKey];
  const resolvedLabel = label ?? itemConfig?.label ?? seriesKey;
  const resolvedColor =
    color ?? itemConfig?.color ?? `var(--color-${seriesKey})`;
  const Icon = icon ?? itemConfig?.icon;
  const isHidden = isSeriesHidden(seriesKey);

  const handleClick = (event: React.MouseEvent<HTMLButtonElement>) => {
    onClick?.(event);
    if (!event.defaultPrevented) {
      toggleSeries(seriesKey);
    }
  };

  return (
    <button
      type="button"
      aria-pressed={!isHidden}
      onClick={handleClick}
      className={cn(
        "flex items-center gap-2 text-gray-600 transition-opacity [&>svg]:h-3 [&>svg]:w-3 cursor-pointer disabled:cursor-not-allowed disabled:opacity-60",
        isHidden && "opacity-50",
        className,
      )}
      {...props}
    >
      {Icon && !hideIcon ? (
        <Icon />
      ) : (
        <span
          className="h-2.5 w-2.5 shrink-0 rounded-full"
          style={{ backgroundColor: resolvedColor }}
        />
      )}
      <span className={cn(isHidden && "line-through text-gray-400")}>
        {resolvedLabel}
      </span>
    </button>
  );
}

function getPayloadConfigFromPayload(
  config: ChartConfig,
  payload: unknown,
  key: string,
) {
  if (typeof payload !== "object" || payload === null) {
    return undefined;
  }

  const payloadPayload =
    "payload" in payload &&
    typeof payload.payload === "object" &&
    payload.payload !== null
      ? payload.payload
      : undefined;

  let configLabelKey: string = key;

  if (
    key in payload &&
    typeof payload[key as keyof typeof payload] === "string"
  ) {
    configLabelKey = payload[key as keyof typeof payload] as string;
  } else if (
    payloadPayload &&
    key in payloadPayload &&
    typeof payloadPayload[key as keyof typeof payloadPayload] === "string"
  ) {
    configLabelKey = payloadPayload[
      key as keyof typeof payloadPayload
    ] as string;
  }

  return configLabelKey in config
    ? config[configLabelKey]
    : config[key as keyof typeof config];
}

export {
  ChartContainer,
  ChartLegendItem,
  useChart,
  ChartTooltip,
  ChartTooltipContent,
  ChartTooltipCard,
  ChartLegend,
  ChartLegendContent,
  ChartStyle,
};
