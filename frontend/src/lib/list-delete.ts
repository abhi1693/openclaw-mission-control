import type { QueryClient, QueryKey } from "@tanstack/react-query";

type ListPayload<TItem> = {
  items: TItem[];
  total: number;
};

export type OptimisticListDeleteContext<TResponse> = {
  previous?: TResponse;
};

type CreateOptimisticListDeleteMutationOptions<TItem, TVariables> = {
  queryClient: QueryClient;
  queryKey: QueryKey;
  getItemId: (item: TItem) => string;
  getDeleteId: (variables: TVariables) => string;
  onSuccess?: () => void;
  invalidateQueryKeys?: QueryKey[];
};

function isListPayload<TItem>(value: unknown): value is ListPayload<TItem> {
  if (!value || typeof value !== "object") {
    return false;
  }
  const maybe = value as { items?: unknown; total?: unknown };
  return Array.isArray(maybe.items) && typeof maybe.total === "number";
}

function getListPayload<TItem>(response: unknown): ListPayload<TItem> | null {
  if (!response || typeof response !== "object") {
    return null;
  }
  const data = (response as { data?: unknown }).data;
  return isListPayload<TItem>(data) ? data : null;
}

export function createOptimisticListDeleteMutation<
  TItem,
  TResponse extends { status: number },
  TVariables,
>({
  queryClient,
  queryKey,
  getItemId,
  getDeleteId,
  onSuccess,
  invalidateQueryKeys,
}: CreateOptimisticListDeleteMutationOptions<TItem, TVariables>) {
  const keysToInvalidate =
    invalidateQueryKeys && invalidateQueryKeys.length > 0
      ? invalidateQueryKeys
      : [queryKey];

  return {
    onMutate: async (
      variables: TVariables,
    ): Promise<OptimisticListDeleteContext<TResponse>> => {
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<TResponse>(queryKey);

      if (previous && previous.status === 200) {
        const payload = getListPayload<TItem>(previous);
        if (!payload) {
          return { previous };
        }
        const deleteId = getDeleteId(variables);
        const nextItems = payload.items.filter(
          (item) => getItemId(item) !== deleteId,
        );
        const removedCount = payload.items.length - nextItems.length;
        queryClient.setQueryData<TResponse>(queryKey, {
          ...(previous as object),
          data: {
            ...payload,
            items: nextItems,
            total: Math.max(0, payload.total - removedCount),
          },
        } as unknown as TResponse);
      }

      return { previous };
    },
    onError: (
      _error: unknown,
      _variables: TVariables,
      context?: OptimisticListDeleteContext<TResponse>,
    ) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKey, context.previous);
      }
    },
    onSuccess: () => {
      onSuccess?.();
    },
    onSettled: () => {
      for (const key of keysToInvalidate) {
        queryClient.invalidateQueries({ queryKey: key });
      }
    },
  };
}
