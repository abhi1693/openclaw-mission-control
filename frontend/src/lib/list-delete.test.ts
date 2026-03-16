import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { createOptimisticListDeleteMutation } from "./list-delete";

type Item = { id: string; label: string };
type Response = {
  status: number;
  data: {
    items: Item[];
    total: number;
  };
};

describe("createOptimisticListDeleteMutation", () => {
  it("optimistically removes an item and restores on error", async () => {
    const queryClient = new QueryClient();
    const key = ["items"];
    const previous: Response = {
      status: 200,
      data: {
        items: [
          { id: "a", label: "A" },
          { id: "b", label: "B" },
        ],
        total: 2,
      },
    };
    queryClient.setQueryData(key, previous);

    const callbacks = createOptimisticListDeleteMutation<
      Item,
      Response,
      { id: string }
    >({
      queryClient,
      queryKey: key,
      getItemId: (item) => item.id,
      getDeleteId: ({ id }) => id,
    });

    const context = await callbacks.onMutate({ id: "a" });
    const updated = queryClient.getQueryData<Response>(key);

    expect(updated?.data.items.map((item) => item.id)).toEqual(["b"]);
    expect(updated?.data.total).toBe(1);

    callbacks.onError(new Error("boom"), { id: "a" }, context);
    expect(queryClient.getQueryData<Response>(key)).toEqual(previous);
  });

  it("runs success callback and invalidates configured query keys", async () => {
    const queryClient = new QueryClient();
    const keyA = ["items"];
    const keyB = ["boards"];
    const onSuccess = vi.fn();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const callbacks = createOptimisticListDeleteMutation<
      Item,
      Response,
      { id: string }
    >({
      queryClient,
      queryKey: keyA,
      getItemId: (item) => item.id,
      getDeleteId: ({ id }) => id,
      onSuccess,
      invalidateQueryKeys: [keyA, keyB],
    });

    callbacks.onSuccess();
    callbacks.onSettled();

    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: keyA });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: keyB });
  });
});
