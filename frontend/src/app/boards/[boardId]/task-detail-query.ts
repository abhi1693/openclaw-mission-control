type SearchParamsInput = string | { toString(): string };

export const withTaskIdSearchParam = (
  searchParams: SearchParamsInput,
  taskId: string | null,
): string => {
  const params = new URLSearchParams(searchParams.toString());
  if (taskId) {
    params.set("taskId", taskId);
  } else {
    params.delete("taskId");
  }
  const next = params.toString();
  return next ? `?${next}` : "";
};

export const buildUrlWithTaskId = (
  pathname: string,
  searchParams: SearchParamsInput,
  taskId: string | null,
): string => `${pathname}${withTaskIdSearchParam(searchParams, taskId)}`;
