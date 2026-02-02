"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

import { Select } from "@/components/ui/select";

import {
  useCreateEmployeeEmployeesPost,
  useListDepartmentsDepartmentsGet,
  useListEmployeesEmployeesGet,
} from "@/api/generated/org/org";

export default function PeoplePage() {
  const [name, setName] = useState("");
  const [employeeType, setEmployeeType] = useState<"human" | "agent">("human");
  const [title, setTitle] = useState("");
  const [departmentId, setDepartmentId] = useState<string>("");
  const [managerId, setManagerId] = useState<string>("");

  const employees = useListEmployeesEmployeesGet();
  const departments = useListDepartmentsDepartmentsGet();
  const departmentList = useMemo(() => departments.data ?? [], [departments.data]);
  const employeeList = useMemo(() => employees.data ?? [], [employees.data]);

  const createEmployee = useCreateEmployeeEmployeesPost({
    mutation: {
      onSuccess: () => {
        setName("");
        setTitle("");
        setDepartmentId("");
        setManagerId("");
        employees.refetch();
      },
    },
  });

  const deptNameById = useMemo(() => {
    const m = new Map<number, string>();
    for (const d of departmentList) {
      if (d.id != null) m.set(d.id, d.name);
    }
    return m;
  }, [departmentList]);

  const empNameById = useMemo(() => {
    const m = new Map<number, string>();
    for (const e of employeeList) {
      if (e.id != null) m.set(e.id, e.name);
    }
    return m;
  }, [employeeList]);

  return (
    <main className="mx-auto max-w-5xl p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">People</h1>
          <p className="mt-1 text-sm text-muted-foreground">Employees and agents share the same table.</p>
        </div>
        <Button variant="outline" onClick={() => employees.refetch()} disabled={employees.isFetching}>
          Refresh
        </Button>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Add person</CardTitle>
            <CardDescription>Create an employee (human) or an agent.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
            <Select value={employeeType} onChange={(e) => setEmployeeType(e.target.value === "agent" ? "agent" : "human")}>
              <option value="human">human</option>
              <option value="agent">agent</option>
            </Select>
            <Input placeholder="Title (optional)" value={title} onChange={(e) => setTitle(e.target.value)} />
            <Select value={departmentId} onChange={(e) => setDepartmentId(e.target.value)}>
              <option value="">(no department)</option>
              {departmentList.map((d) => (
                <option key={d.id ?? d.name} value={d.id ?? ""}>
                  {d.name}
                </option>
              ))}
            </Select>
            <Select value={managerId} onChange={(e) => setManagerId(e.target.value)}>
              <option value="">(no manager)</option>
              {employeeList.map((e) => (
                <option key={e.id ?? e.name} value={e.id ?? ""}>
                  {e.name}
                </option>
              ))}
            </Select>
            <Button
              onClick={() =>
                createEmployee.mutate({
                  data: {
                    name,
                    employee_type: employeeType,
                    title: title.trim() ? title : null,
                    department_id: departmentId ? Number(departmentId) : null,
                    manager_id: managerId ? Number(managerId) : null,
                    status: "active",
                  },
                })
              }
              disabled={!name.trim() || createEmployee.isPending}
            >
              Create
            </Button>
            {createEmployee.error ? (
              <div className="text-sm text-destructive">{(createEmployee.error as Error).message}</div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Directory</CardTitle>
            <CardDescription>{employeeList.length} total</CardDescription>
          </CardHeader>
          <CardContent>
            {employees.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
            {employees.error ? (
              <div className="text-sm text-destructive">{(employees.error as Error).message}</div>
            ) : null}
            {!employees.isLoading && !employees.error ? (
              <ul className="space-y-2">
                {employeeList.map((e) => (
                  <li key={e.id ?? e.name} className="rounded-md border p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium">{e.name}</div>
                      <Badge variant={e.employee_type === "agent" ? "secondary" : "outline"}>
                        {e.employee_type}
                      </Badge>
                    </div>
                    <div className="mt-2 text-sm text-muted-foreground">
                      {e.title ? <span>{e.title} · </span> : null}
                      {e.department_id ? <span>{deptNameById.get(e.department_id) ?? `Dept#${e.department_id}`} · </span> : null}
                      {e.manager_id ? <span>Mgr: {empNameById.get(e.manager_id) ?? `Emp#${e.manager_id}`}</span> : <span>No manager</span>}
                    </div>
                  </li>
                ))}
                {employeeList.length === 0 ? (
                  <li className="text-sm text-muted-foreground">No people yet.</li>
                ) : null}
              </ul>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
