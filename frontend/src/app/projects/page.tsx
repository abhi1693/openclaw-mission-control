"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

import {
  useCreateProjectProjectsPost,
  useListProjectsProjectsGet,
} from "@/api/generated/projects/projects";

export default function ProjectsPage() {
  const [name, setName] = useState("");

  const projects = useListProjectsProjectsGet();
  const createProject = useCreateProjectProjectsPost({
    mutation: {
      onSuccess: () => {
        setName("");
        projects.refetch();
      },
    },
  });

  const sorted = useMemo(() => {
    return (projects.data ?? []).slice().sort((a, b) => a.name.localeCompare(b.name));
  }, [projects.data]);

  return (
    <main className="mx-auto max-w-5xl p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
          <p className="mt-1 text-sm text-muted-foreground">Create and manage projects.</p>
        </div>
        <Button variant="outline" onClick={() => projects.refetch()} disabled={projects.isFetching}>
          Refresh
        </Button>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Create project</CardTitle>
            <CardDescription>Minimal fields for v1</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input
              placeholder="Project name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <Button
              onClick={() => createProject.mutate({ data: { name, status: "active" } })}
              disabled={!name.trim() || createProject.isPending}
            >
              Create
            </Button>
            {createProject.error ? (
              <div className="text-sm text-destructive">{(createProject.error as Error).message}</div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>All projects</CardTitle>
            <CardDescription>{sorted.length} total</CardDescription>
          </CardHeader>
          <CardContent>
            {projects.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
            {projects.error ? (
              <div className="text-sm text-destructive">{(projects.error as Error).message}</div>
            ) : null}
            {!projects.isLoading && !projects.error ? (
              <ul className="space-y-2">
                {sorted.map((p) => (
                  <li key={p.id ?? p.name} className="flex items-center justify-between rounded-md border p-3">
                    <div className="font-medium">{p.name}</div>
                    <div className="text-xs text-muted-foreground">{p.status}</div>
                  </li>
                ))}
                {sorted.length === 0 ? <li className="text-sm text-muted-foreground">No projects yet.</li> : null}
              </ul>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
