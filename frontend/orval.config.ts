import { defineConfig } from "orval";

export default defineConfig({
  api: {
    input: {
      target: "http://127.0.0.1:8000/openapi.json",
    },
    output: {
      mode: "tags-split",
      target: "src/api/generated/index.ts",
      schemas: "src/api/generated/model",
      client: "react-query",
      prettier: true,
      override: {
        mutator: {
          path: "src/api/mutator.ts",
          name: "customFetch",
        },
        query: {
          useQuery: true,
          useMutation: true,
        },
      },
    },
  },
});
