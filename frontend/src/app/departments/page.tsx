"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

import { Select } from "@/components/ui/select";

import {
  useCreateDepartmentDepartmentsPost,
  useListDepartmentsDepartmentsGet,
  useUpdateDepartmentDepartmentsDepartmentIdPatch,
} from "@/api/generated/org/org";
import { useListEmployeesEmployeesGet } from "@/api/generated/org/org";

export default function DepartmentsPage() {
  const [name, setName] = useState("");
  const [headId, setHeadId] = useState<string>("");

  const departments = useListDepartmentsDepartmentsGet();
  const departmentList = departments.data ?? [];
  const employees = useListEmployeesEmployeesGet();

  const employeeList = employees.data ?? [];

  const createDepartment = useCreateDepartmentDepartmentsPost({
    mutation: {
      onSuccess: () => {
        setName("");
        setHeadId("");
        departments.refetch();
      },
    },
  });

  const updateDepartment = useUpdateDepartmentDepartmentsDepartmentIdPatch({
    mutation: {
      onSuccess: () => departments.refetch(),
    },
  });

  const sortedEmployees = employeeList.slice().sort((a, b) => (a.name ?? "").localeCompare(b.name ?? ""));

  return (
    <main className="mx-auto max-w-5xl p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Departments</h1>
          <p className="mt-1 text-sm text-muted-foreground">Create departments and assign department heads.</p>
        </div>
        <Button variant="outline" onClick={() => departments.refetch()} disabled={departments.isFetching}>
          Refresh
        </Button>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Create department</CardTitle>
            <CardDescription>Optional head</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input placeholder="Department name" value={name} onChange={(e) => setName(e.target.value)} />
            <Select value={headId} onChange={(e) => setHeadId(e.target.value)}>
              <option value="">(no head)</option>
              {sortedEmployees.map((e) => (
                <option key={e.id ?? e.name} value={e.id ?? ""}>
                  {e.name} ({e.employee_type})
                </option>
              ))}
            </Select>
            <Button
              onClick={() =>
                createDepartment.mutate({
                  data: {
                    name,
                    head_employee_id: headId ? Number(headId) : null,
                  },
                })
              }
              disabled={!name.trim() || createDepartment.isPending}
            >
              Create
            </Button>
            {createDepartment.error ? (
              <div className="text-sm text-destructive">{(createDepartment.error as Error).message}</div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>All departments</CardTitle>
            <CardDescription>{departmentList.length} total</CardDescription>
          </CardHeader>
          <CardContent>
            {departments.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
            {departments.error ? (
              <div className="text-sm text-destructive">{(departments.error as Error).message}</div>
            ) : null}
            {!departments.isLoading && !departments.error ? (
              <ul className="space-y-2">
                {departmentList.map((d) => (
                  <li key={d.id ?? d.name} className="rounded-md border p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium">{d.name}</div>
                      <div className="text-xs text-muted-foreground">id: {d.id}</div>
                    </div>
                    <div className="mt-3 flex items-center gap-2">
                      <span className="text-xs text-muted-foreground">Head:</span>
                      <Select
                        value={d.head_employee_id ? String(d.head_employee_id) : ""}
                        onChange={(e) =>
                          updateDepartment.mutate({
                            departmentId: Number(d.id),
                            data: { head_employee_id: e.target.value ? Number(e.target.value) : null },
                          })
                        }
                      >
                        <option value="">(none)</option>
                        {sortedEmployees.map((e) => (
                          <option key={e.id ?? e.name} value={e.id ?? ""}>
                            {e.name}
                          </option>
                        ))}
                      </Select>
                    </div>
                  </li>
                ))}
                {departmentList.length === 0 ? (
                  <li className="text-sm text-muted-foreground">No departments yet.</li>
                ) : null}
              </ul>
            ) : null}
            {updateDepartment.error ? (
              <div className="mt-3 text-sm text-destructive">{(updateDepartment.error as Error).message}</div>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
